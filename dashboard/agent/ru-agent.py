#!/usr/bin/env python3
# =============================================================================
#  dashboard/agent/ru-agent.py — estado da RU (LiteOn FlexFi) para o painel (aba RU).
#
#  Roda na máquina do core. Mantém UMA sessão SSH interativa na porta de gestão
#  (RJ45) da RU e roda só comandos "show" — nunca altera a configuração.
#  A RU só aceita senha (CLI própria), então a sessão usa um pseudo-terminal.
#
#  Uso:
#    DASHBOARD_URL=http://10.254.254.1:30998 INGEST_TOKEN=... RU_TARGET=user@10.101.131.59 \
#    RU_PASS=... RU_ENABLE=... python3 ru-agent.py
#  RU_PASS/RU_ENABLE vêm de um arquivo só do root e do grupo do usuário
#  (${INSTALL_DIR}/state/ru-credentials), nunca do git.
# =============================================================================
import json
import os
import pty
import re
import select
import sys
import time
import urllib.error
import urllib.request

URL = os.environ.get("DASHBOARD_URL", "").rstrip("/")
TOKEN = os.environ.get("INGEST_TOKEN", "")
TARGET = os.environ.get("RU_TARGET", "")
PASS = os.environ.get("RU_PASS", "")
ENABLE = os.environ.get("RU_ENABLE", "")
POLL = max(2.0, float(os.environ.get("RU_POLL_SECONDS", "10")))
SLOW = 300   # configuração, firmware: a cada 5 min

FAST_CMDS = ["show oru-status", "show sync-trace", "show pm-data", "show eth-info", "show uptime"]
SLOW_CMDS = ["show fw-info", "show running-config", "show dl-ul-layer", "show system"]
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PROMPT = re.compile(rb"(?:^|\n)\s*([>#]) ?$")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def post(payload):
    req = urllib.request.Request(URL + "/api/ingest/ru", data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Ingest-Token", TOKEN)
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()


# ----------------------------------------------------------------------------- sessão
class Session:
    def __init__(self):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvp("ssh", ["ssh", "-tt", "-o", "StrictHostKeyChecking=accept-new", "-o", "PubkeyAuthentication=no",
                              "-o", "NumberOfPasswordPrompts=1", "-o", "ConnectTimeout=10",
                              "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", TARGET])
        self.buf = b""
        self.mode = None

    def _read(self, timeout, pattern):
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.2)
            if not r:
                continue
            try:
                d = os.read(self.fd, 65536)
            except OSError:
                raise ConnectionError("sessão SSH encerrada")
            if not d:
                raise ConnectionError("sessão SSH encerrada")
            self.buf += d
            m = pattern.search(self.buf[-400:])
            if m:
                time.sleep(0.15)   # resto da linha
                r2, _, _ = select.select([self.fd], [], [], 0.1)
                if r2:
                    try:
                        self.buf += os.read(self.fd, 65536)
                    except OSError:
                        pass
                    if not pattern.search(self.buf[-400:]):
                        continue
                return
        raise TimeoutError("RU não respondeu (%s)" % self.buf[-120:].decode("utf-8", "replace").strip())

    def _send(self, s):
        os.write(self.fd, s.encode() + b"\r")

    def login(self):
        self._read(20, re.compile(rb"[Pp]assword:\s*$"))
        self.buf = b""
        self._send(PASS)
        self._read(15, re.compile(rb"[Pp]assword:\s*$|(?:^|\n)\s*[>#] ?$"))
        if re.search(rb"[Pp]assword:\s*$", self.buf):
            raise PermissionError("senha da RU recusada")
        self.mode = PROMPT.search(self.buf[-400:]).group(1)
        self.privileged()

    def privileged(self):
        if not ENABLE or self.mode == b"#":
            return
        self.buf = b""
        self._send("enable")
        self._read(8, re.compile(rb"[Pp]assword:\s*$"))
        self.buf = b""
        self._send(ENABLE)
        self._read(8, PROMPT)
        self.mode = PROMPT.search(self.buf[-400:]).group(1)
        if self.mode != b"#":
            raise PermissionError("senha do enable recusada")

    def run(self, cmd):
        """Saída de um comando (sem eco e sem prompt)."""
        assert cmd.startswith("show "), cmd   # o agente só lê
        self.buf = b""
        self._send(cmd)
        self._read(20, PROMPT)
        self.mode = PROMPT.search(self.buf[-400:]).group(1)
        text = ANSI.sub("", self.buf.decode("utf-8", "replace")).replace("\r", "")
        lines = text.split("\n")
        if lines and cmd in lines[0]:
            lines = lines[1:]
        if lines and re.match(r"^\s*[>#] ?$", lines[-1]):
            lines = lines[:-1]
        out = "\n".join(lines)
        if "Auto exit privileged" in out or (self.mode == b">" and ENABLE):
            # o modo privilegiado expira sozinho (300 s): entra de novo e repete
            self.privileged()
            return self.run(cmd) if self.mode == b"#" else out
        return out

    def close(self):
        try:
            self._send("exit")
            time.sleep(0.2)
            self._send("exit")
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.kill(self.pid, 15)
            os.waitpid(self.pid, 0)
        except OSError:
            pass


# ----------------------------------------------------------------------------- leitura das saídas
def kv(text, sep=":"):
    out = {}
    for l in text.splitlines():
        if sep in l:
            k, _, v = l.partition(sep)
            if k.strip():
                out[k.strip()] = v.strip()
    return out


def parse_status(text):
    s = kv(text)
    return {"sync": s.get("Sync State"), "rf": s.get("RF State"), "dpd": s.get("DPD"), "du": s.get("DuConnected"),
            "raw": {k: v for k, v in s.items()}}


def parse_sync(text):
    m = re.search(r"Sync status/state:\s*(\S+?)/(\S+)", text)
    return {"status": m.group(1), "state": m.group(2)} if m else {"raw": text.strip()[:200]}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_pm(text):
    """Última janela de cada contador do "show pm-data"."""
    pm = {}
    for l in text.splitlines():
        p = [x.strip() for x in l.split(",")]
        if len(p) < 5 or not p[0].isdigit():
            continue
        name, t0, t1 = p[1], p[2], p[3]
        if name in ("POWER", "TEMPERATURE") and len(p) >= 12:
            pm[name] = {"t0": t0, "t1": t1, "radio": {"min": _f(p[5]), "max": _f(p[6]), "avg": _f(p[7])},
                        "cpu": {"min": _f(p[9]), "max": _f(p[10]), "avg": _f(p[11])}}
        elif re.match(r"^(RX|TX)_", name) and len(p) >= 6:
            pm[name] = {"t0": t0, "t1": t1, "count": _f(p[5])}
        elif name == "VOLTAGE":
            continue
    return pm


RE_IF = re.compile(r"^(\S+)\s+Link encap")


def parse_eth(text):
    out = {}
    cur = None
    for l in text.splitlines():
        m = RE_IF.match(l)
        if m:
            cur = out.setdefault(m.group(1), {})
            mm = re.search(r"HWaddr\s+(\S+)", l)
            if mm:
                cur["mac"] = mm.group(1)
            continue
        if cur is None:
            continue
        for pat, key in ((r"inet addr:(\S+)", "ip"), (r"Mask:(\S+)", "mask"), (r"MTU:(\d+)", "mtu"),
                         (r"RX bytes:(\d+)", "rx_bytes"), (r"TX bytes:(\d+)", "tx_bytes"),
                         (r"RX packets:\d+ errors:(\d+) dropped:(\d+)", "rx_err"),
                         (r"TX packets:\d+ errors:(\d+) dropped:(\d+)", "tx_err")):
            mm = re.search(pat, l)
            if mm:
                if key in ("rx_err", "tx_err"):
                    cur[key] = int(mm.group(1)) + int(mm.group(2))
                elif key in ("rx_bytes", "tx_bytes", "mtu"):
                    cur[key] = int(mm.group(1))
                else:
                    cur[key] = mm.group(1)
        if "RUNNING" in l:
            cur["running"] = True
    out.pop("lo", None)
    return out


def parse_uptime(text):
    m = re.search(r"up\s+(?:(\d+)\s+days?,\s*)?(\d+):(\d+)", text)
    up = None
    if m:
        up = int(m.group(1) or 0) * 86400 + int(m.group(2)) * 3600 + int(m.group(3)) * 60
    else:
        m = re.search(r"up\s+(?:(\d+)\s+days?,\s*)?(\d+)\s+min", text)
        if m:
            up = int(m.group(1) or 0) * 86400 + int(m.group(2)) * 60
    lm = re.search(r"load average:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)", text)
    return {"uptime": up, "load": [float(x) for x in lm.groups()] if lm else None}


def parse_config(text):
    c = {}
    for l in text.splitlines():
        m = re.match(r"^\s*([^=:]+?)\s*[=:]\s*(.+?)\s*$", l)
        if m:
            c[m.group(1)] = m.group(2)
    return c


def parse_slow(outs):
    fw = kv(outs.get("show fw-info", ""))
    return {"model": fw.get("model id"), "product": fw.get("product_name"), "firmware": fw.get("firmware version"),
            "layers": outs.get("show dl-ul-layer", "").strip() or None,
            "system": " ".join(outs.get("show system", "").split("\n")[1:2]).strip() or None,
            "config": parse_config(outs.get("show running-config", ""))}


# ----------------------------------------------------------------------------- laço
def cycle(s, prev, slow_due):
    outs = {c: s.run(c) for c in FAST_CMDS + (SLOW_CMDS if slow_due else [])}
    now = time.time()
    eth = parse_eth(outs["show eth-info"])
    for name, e in eth.items():
        p = prev.get(name)
        if p and now > p[0]:
            dt = now - p[0]
            e["rx_bps"] = max(0, e.get("rx_bytes", 0) - p[1]) * 8 / dt
            e["tx_bps"] = max(0, e.get("tx_bytes", 0) - p[2]) * 8 / dt
        prev[name] = (now, e.get("rx_bytes", 0), e.get("tx_bytes", 0))
    sample = {"status": parse_status(outs["show oru-status"]), "sync": parse_sync(outs["show sync-trace"]),
              "pm": parse_pm(outs["show pm-data"]), "eth": eth, **parse_uptime(outs["show uptime"])}
    if slow_due:
        sample["info"] = parse_slow(outs)
    return sample


def main():
    once = "--once" in sys.argv   # teste: uma leitura completa, imprime e sai (não envia)
    if not TARGET or not PASS or (not once and (not URL or not TOKEN)):
        print("uso: DASHBOARD_URL=... INGEST_TOKEN=... RU_TARGET=usuario@ip RU_PASS=... [RU_ENABLE=...] ru-agent.py [--once]",
              file=sys.stderr)
        sys.exit(2)
    backoff = 5
    while True:
        s = None
        t_start = time.time()
        wait = None
        try:
            s = Session()
            s.login()
            log("conectado", TARGET)
            prev, last_slow = {}, 0.0
            if once:
                cycle(s, prev, False)
                time.sleep(2)
                print(json.dumps(cycle(s, prev, True), indent=1, ensure_ascii=False))
                return
            while True:
                t0 = time.time()
                slow = t0 - last_slow >= SLOW
                sample = cycle(s, prev, slow)
                if slow:
                    last_slow = t0
                try:
                    post({"target": TARGET, "sample": sample})
                except (urllib.error.URLError, OSError) as e:
                    log("painel indisponível:", e)
                time.sleep(max(0.5, POLL - (time.time() - t0)))
        except (ConnectionError, TimeoutError, PermissionError, OSError, AttributeError) as e:
            err = str(e) or e.__class__.__name__
            log("RU:", err)
            if once:
                sys.exit(1)
            try:
                post({"target": TARGET, "error": err})
            except (urllib.error.URLError, OSError):
                pass
            if isinstance(e, PermissionError):
                wait = 300   # senha errada: não insiste (a RU pode bloquear o usuário)
        finally:
            if s:
                s.close()
        backoff = 5 if time.time() - t_start > 120 else min(backoff * 2, 120)
        time.sleep(wait or backoff)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
