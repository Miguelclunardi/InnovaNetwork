#!/usr/bin/env python3
# =============================================================================
#  dashboard/agent/gnb-log-agent.py — envia o log do gNB real ao painel.
#
#  Roda na máquina do core (torre2), não na do gNB: o OCUDU fica livre.
#  Dois modos:
#    - remoto (padrão do projeto): GNB_LOG_SSH=usuario@host => lê o arquivo do
#      gNB com `ssh host tail -F` (só leitura) e reconecta sozinho se cair;
#    - local: sem GNB_LOG_SSH, acompanha um arquivo desta máquina.
#  Manda lotes de linhas por HTTP POST para o painel a cada ~1 s.
#
#  Uso:
#    DASHBOARD_URL=http://127.0.0.1:30998 INGEST_TOKEN=... GNB_LOG_SSH=innova@10.10.0.1 \
#      python3 gnb-log-agent.py /tmp/gnb.log
#
#  O arquivo é o `log: filename:` da configuração do gNB (OCUDU).
#  Só biblioteca padrão. Se o painel cair, guarda até MAX_BUFFER linhas.
# =============================================================================
import collections
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

URL = os.environ.get("DASHBOARD_URL", "").rstrip("/")
TOKEN = os.environ.get("INGEST_TOKEN", "")
SSH = os.environ.get("GNB_LOG_SSH", "").strip()            # usuario@host (vazio = arquivo local)
SSH_OPTS = os.environ.get("GNB_LOG_SSH_OPTS", "-o BatchMode=yes -o ServerAliveInterval=10 -o ServerAliveCountMax=3 -o ConnectTimeout=10")
SOURCE = os.environ.get("SOURCE_NAME", SSH.split("@")[-1] if SSH else socket.gethostname())
# Linhas descartadas aqui (na máquina do core), ex.: PHY nível info, que é ~95% do volume.
DROP = os.environ.get("GNB_LOG_DROP", "")
DROP_RE = re.compile(DROP) if DROP else None
INTERVAL = float(os.environ.get("INTERVAL", "1"))
MAX_BATCH = 5000
MAX_BUFFER = 50000
START_LINES = int(os.environ.get("START_LINES", "500"))  # linhas do fim do arquivo enviadas ao iniciar
# Vínculo RNTI -> UE para o painel: ao iniciar (e quando o painel reinicia) procura nos últimos
# IDENT_BYTES do log as linhas RRC/NGAP que ligam c-rnti e amf_ue. Só leitura, com nice.
IDENT_BYTES = int(os.environ.get("IDENT_BYTES", str(300 * 1024 * 1024)))
IDENT_GREP = ("tail -c %d %s | grep -a -E 'c-rnti=0x|amf_ue=' | grep -a -E '\\[(RRC|CU-CP|NGAP) *\\]' | tail -n 20000")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def last_lines(path, n):
    """Últimas n linhas do arquivo (lendo de trás para frente)."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        end = pos = f.tell()
        data = b""
        while pos > 0 and data.count(b"\n") <= n:
            step = min(65536, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step) + data
        return end, data.decode("utf-8", "replace").splitlines()[-n:]


class Follower:
    def __init__(self, path):
        self.path = path
        self.f = None
        self.ino = None
        self.partial = ""

    def _open(self, start_at_end):
        self.f = open(self.path, "rb")
        st = os.fstat(self.f.fileno())
        self.ino = st.st_ino
        if start_at_end:
            self.f.seek(0, os.SEEK_END)

    def read(self, first):
        out = []
        if self.f is None:
            try:
                if first and START_LINES > 0:
                    end, out = last_lines(self.path, START_LINES)
                    self._open(False)
                    self.f.seek(end)
                else:
                    self._open(first)
            except FileNotFoundError:
                return out
        chunk = self.f.read(4 * 1024 * 1024)
        if chunk:
            text = self.partial + chunk.decode("utf-8", "replace")
            lines = text.split("\n")
            self.partial = lines.pop()
            out.extend(lines)
        else:
            # Arquivo recriado (novo inode) ou truncado: reabre do começo
            try:
                st = os.stat(self.path)
                if st.st_ino != self.ino or st.st_size < self.f.tell():
                    self.f.close()
                    self.f, self.partial = None, ""
                    self._open(False)
                    out.append("--- (agente) arquivo de log recomeçou ---")
            except FileNotFoundError:
                pass
        return out


class SshFollower:
    """`ssh host tail -F` numa thread; reconecta com espera crescente."""

    def __init__(self, path):
        self.path = path
        self.q = collections.deque(maxlen=MAX_BUFFER)
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        backoff, first = 2, True
        while True:
            n = START_LINES if first else 0
            cmd = ["ssh"] + shlex.split(SSH_OPTS) + [SSH, "tail -n %d -F %s" % (n, shlex.quote(self.path))]
            t0 = time.time()
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
                log("ssh conectado:", SSH, self.path)
                for raw in p.stdout:
                    with self.lock:
                        self.q.append(raw.decode("utf-8", "replace").rstrip("\n"))
                err = p.stderr.read().decode("utf-8", "replace").strip()
                p.wait()
                log("ssh terminou (código %s): %s" % (p.returncode, err[-300:]))
            except OSError as e:
                log("ssh falhou:", e)
            first = False
            with self.lock:
                self.q.append("--- (agente) conexão com %s caiu; reconectando ---" % SSH)
            backoff = 2 if time.time() - t0 > 60 else min(backoff * 2, 60)
            time.sleep(backoff)

    def read(self, first):
        with self.lock:
            out = list(self.q)
            self.q.clear()
        return out


def post(lines, ident_only=False):
    body = ("\n".join(lines) + "\n").encode("utf-8")
    req = urllib.request.Request(URL + "/api/ingest/gnb-log", data=body, method="POST")
    req.add_header("Content-Type", "text/plain; charset=utf-8")
    req.add_header("X-Ingest-Token", TOKEN)
    req.add_header("X-Source", SOURCE)
    if ident_only:
        req.add_header("X-Ident-Only", "1")
    with urllib.request.urlopen(req, timeout=30) as r:
        try:
            return json.loads(r.read() or b"{}")
        except ValueError:
            return {}


def ident_bootstrap(path):
    """Manda ao painel as linhas recentes que ligam RNTI ao UE (não aparecem na tela de log)."""
    if IDENT_BYTES <= 0:
        return
    cmd = "nice -n 19 sh -c %s" % shlex.quote(IDENT_GREP % (IDENT_BYTES, shlex.quote(path)))
    argv = (["ssh"] + shlex.split(SSH_OPTS) + [SSH, cmd]) if SSH else ["sh", "-c", cmd]
    try:
        p = subprocess.run(argv, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        lines = p.stdout.decode("utf-8", "replace").splitlines()
        if lines:
            post(lines, ident_only=True)
        log("vínculos RNTI -> UE enviados ao painel: %d linhas" % len(lines))
    except (subprocess.TimeoutExpired, OSError, urllib.error.URLError) as e:
        log("busca de vínculos RNTI -> UE falhou:", e)


def main():
    if len(sys.argv) != 2 or not URL or not TOKEN:
        print("uso: DASHBOARD_URL=... INGEST_TOKEN=... [GNB_LOG_SSH=usuario@host] gnb-log-agent.py <arquivo-de-log>", file=sys.stderr)
        sys.exit(2)
    fol = SshFollower(sys.argv[1]) if SSH else Follower(sys.argv[1])
    buf = collections.deque(maxlen=MAX_BUFFER)
    first, failing = True, False
    last_boot = 0.0
    log("acompanhando", (SSH + ":" if SSH else "") + sys.argv[1], "->", URL)
    while True:
        buf.extend(l for l in fol.read(first) if l.strip() and not (DROP_RE and DROP_RE.search(l)))
        first = False
        while buf:
            batch = [buf.popleft() for _ in range(min(MAX_BATCH, len(buf)))]
            try:
                r = post(batch)
                # Painel sem vínculos (acabou de subir/reiniciar): manda os recentes (no máx. a cada 5 min)
                if r.get("ident") == 0 and time.time() - last_boot > 300:
                    last_boot = time.time()
                    threading.Thread(target=ident_bootstrap, args=(sys.argv[1],), daemon=True).start()
                if failing:
                    log("painel voltou")
                    failing = False
            except (urllib.error.URLError, OSError) as e:
                buf.extendleft(reversed(batch))
                if not failing:
                    log("painel indisponível (%s); guardando até %d linhas" % (e, MAX_BUFFER))
                    failing = True
                break
        time.sleep(INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
