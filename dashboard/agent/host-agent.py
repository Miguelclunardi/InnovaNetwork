#!/usr/bin/env python3
# =============================================================================
#  dashboard/agent/host-agent.py — CPU/memória/temperatura/rede/discos/processos
#  das outras máquinas do sistema para o painel (aba Máquinas).
#
#  Roda na máquina do core. Para cada máquina abre UMA sessão SSH e manda o
#  coletor (hoststats.py) pela entrada padrão — nada é instalado na máquina
#  remota; lá roda só `nice -n 19 python3 -` lendo /proc e /sys a cada 2 s.
#
#  Uso:
#    DASHBOARD_URL=http://127.0.0.1:30998 INGEST_TOKEN=... \
#    HOSTS="innovaserver|innovaserver@10.10.0.1|gNB OCUDU + LiteOn" \
#      python3 host-agent.py /caminho/hoststats.py
#  HOSTS: "nome|usuario@host|papel" separados por ";".
# =============================================================================
import json
import os
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

URL = os.environ.get("DASHBOARD_URL", "").rstrip("/")
TOKEN = os.environ.get("INGEST_TOKEN", "")
INTERVAL = os.environ.get("HOST_INTERVAL", "2")
SSH_OPTS = os.environ.get("SSH_OPTS", "-o BatchMode=yes -o ServerAliveInterval=10 -o ServerAliveCountMax=3 -o ConnectTimeout=10")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def post(payload):
    req = urllib.request.Request(URL + "/api/ingest/host", data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Ingest-Token", TOKEN)
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()


def follow(name, target, role, script):
    backoff = 2
    while True:
        t0 = time.time()
        err = ""
        try:
            p = subprocess.Popen(["ssh"] + shlex.split(SSH_OPTS) + [target, "nice -n 19 python3 - --loop %s" % INTERVAL],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            p.stdin.write(script)
            p.stdin.close()
            log(name, "conectado", target)
            for line in p.stdout:
                try:
                    post({"name": name, "role": role, "sample": json.loads(line)})
                except ValueError:
                    continue
                except (urllib.error.URLError, OSError) as e:
                    log(name, "painel indisponível:", e)
            err = p.stderr.read().decode("utf-8", "replace").strip()[-300:]
            p.wait()
            log(name, "ssh terminou (código %s): %s" % (p.returncode, err))
        except OSError as e:
            err = str(e)
        try:
            post({"name": name, "role": role, "error": "sem conexão SSH com %s: %s" % (target, err or "encerrada")})
        except (urllib.error.URLError, OSError):
            pass
        backoff = 2 if time.time() - t0 > 60 else min(backoff * 2, 60)
        time.sleep(backoff)


def main():
    hosts = [h.split("|") for h in os.environ.get("HOSTS", "").split(";") if h.count("|") == 2]
    if len(sys.argv) != 2 or not URL or not TOKEN or not hosts:
        print("uso: DASHBOARD_URL=... INGEST_TOKEN=... HOSTS='nome|usuario@host|papel;...' host-agent.py hoststats.py",
              file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], "rb") as f:
        script = f.read()
    for name, target, role in hosts:
        threading.Thread(target=follow, args=(name, target, role, script), daemon=True).start()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
