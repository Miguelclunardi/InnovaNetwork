#!/usr/bin/env python3
# =============================================================================
#  dashboard/agent/gnb-ctl-agent.py — controle do gNB OCUDU pelo painel (aba Controle).
#
#  Roda na máquina do core (usuário do install). A cada poucos segundos lê, por
#  SSH, o estado do serviço ocudu-gnb@<arquivo> no host do gNB, manda ao painel e
#  recebe de volta o próximo comando (iniciar/parar/reiniciar), que executa com
#  "systemctl" SEM sudo: no host do gNB uma regra do polkit deixa este usuário
#  mexer só nas units ocudu-gnb@*.service (scripts/ocudu/setup-gnb-service.sh).
#
#  Modo k8s (GNB_CTL_MODE=k8s, InnovaNetwork v3): o gNB é o pod "ocudu-gnb" (namespace
#  ocudu) no nó do rádio. Iniciar/parar = ran/ocudu/gnb.sh (GNB_CTL_GNBSH) aqui, com o
#  kubectl do usuário; o estado vem do Kubernetes + processo gnb no nó (por SSH).
#
#  Uso:
#    DASHBOARD_URL=http://10.254.254.1:30998 INGEST_TOKEN=... \
#    GNB_CTL_SSH=innovaserver@10.10.0.1 GNB_CTL_DIR=/home/innovaserver/ocudu python3 gnb-ctl-agent.py
# =============================================================================
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request

URL = os.environ.get("DASHBOARD_URL", "").rstrip("/")
TOKEN = os.environ.get("INGEST_TOKEN", "")
TARGET = os.environ.get("GNB_CTL_SSH", "")
DIR = os.environ.get("GNB_CTL_DIR", "")
MODE = os.environ.get("GNB_CTL_MODE", "systemd")
GNBSH = os.environ.get("GNB_CTL_GNBSH", "")
NS = os.environ.get("GNB_CTL_NAMESPACE", "ocudu")
INTERVAL = float(os.environ.get("GNB_CTL_INTERVAL", "3"))
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=10",
       "-o", "ControlMaster=auto", "-o", "ControlPath=/tmp/gnbctl-%C", "-o", "ControlPersist=120"]
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")

# Lido no host do gNB (python3 -): só leitura.
STATUS = r'''
import glob, json, os, re, subprocess, sys
D = sys.argv[1]
def sh(*a):
    try:
        return subprocess.run(a, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""
def polkit_rule():
    # rules.d costuma ser root:polkitd 0750: um usuário comum não lista -> desconhecido (None), não "falta"
    try:
        return "50-ocudu-gnb.rules" in os.listdir("/etc/polkit-1/rules.d")
    except OSError:
        return None
out = {"dir": D, "unit_installed": os.path.exists("/etc/systemd/system/ocudu-gnb@.service"),
       "polkit": polkit_rule(),
       "gnb_bin": os.path.exists(os.path.join(D, "build/apps/gnb/gnb"))}
b = os.path.join(D, "build/apps/gnb/gnb")
out["gnb_bin_mtime"] = os.path.getmtime(b) if os.path.exists(b) else None
units = []
for l in sh("systemctl", "list-units", "--all", "--plain", "--no-legend", "ocudu-gnb@*").splitlines():
    p = l.split()
    if len(p) >= 4 and p[0].startswith("ocudu-gnb@"):
        units.append({"unit": p[0], "load": p[1], "state": p[2], "sub": p[3]})
pick = [u for u in units if u["state"] in ("active", "activating", "deactivating")] or \
       [u for u in units if u["state"] == "failed"]
active = None
if pick:
    u = pick[0]
    props = dict(l.split("=", 1) for l in sh("systemctl", "show", u["unit"], "-p", "MainPID", "-p",
                 "ActiveEnterTimestamp", "-p", "Result", "-p", "ExecMainStatus", "-p", "InactiveEnterTimestamp").splitlines() if "=" in l)
    active = dict(u, config=u["unit"][len("ocudu-gnb@"):-len(".service")], pid=int(props.get("MainPID") or 0),
                  since=props.get("ActiveEnterTimestamp"), result=props.get("Result"),
                  exit=props.get("ExecMainStatus"), stopped=props.get("InactiveEnterTimestamp"),
                  journal=sh("journalctl", "-u", u["unit"], "-n", "25", "--no-pager", "-o", "cat").splitlines()[-25:])
    out["active"] = active if u["state"] != "failed" else None
    out["failed"] = active if u["state"] == "failed" else None
pids = []
for l in sh("pgrep", "-a", "-x", "gnb").splitlines():
    pid, _, cmd = l.partition(" ")
    pids.append({"pid": int(pid), "cmd": cmd[:300]})
out["gnb_pids"] = pids
mine = (out.get("active") or {}).get("pid")
out["manual"] = [p for p in pids if p["pid"] != mine]
cfgs = []
for f in sorted(glob.glob(os.path.join(D, "configs", "*.yml"))):
    n = os.path.basename(f)[:-4]
    info = {"name": n, "mtime": os.path.getmtime(f)}
    try:
        t = open(f, errors="replace").read(200000)
        m = re.search(r"(?m)^\s*amf:\s*\n(?:\s*#.*\n)*\s*addr:\s*([^\s#]+)", t)
        if m:
            info["amf"] = m.group(1)
        m = re.search(r"(?m)^\s*-?\s*network_interface:\s*([^\s#]+)", t)
        if m:
            info["nic"] = m.group(1)
        m = re.search(r"(?m)^\s*dl_arfcn:\s*(\d+)", t)
        if m:
            info["arfcn"] = int(m.group(1))
        m = re.search(r"(?m)^\s*channel_bandwidth_MHz:\s*(\d+)", t)
        if m:
            info["bw"] = int(m.group(1))
        info["gnb"] = bool(re.search(r"(?m)^ru_ofh:|^ru_sdr:|^ru_dummy:", t)) and "cu_cp" in t
    except OSError:
        pass
    cfgs.append(info)
out["configs"] = cfgs
nics = {c["nic"] for c in cfgs if re.match(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9]$", c.get("nic", ""))}
out["nics"] = {n: os.path.basename(os.path.realpath("/sys/bus/pci/devices/%s/driver" % n))
               if os.path.exists("/sys/bus/pci/devices/%s/driver" % n) else None for n in nics}
out["ptp"] = {s: sh("systemctl", "is-active", s).strip() for s in ("ptp4l-gm", "ts2phc", "phc2sys")}
print(json.dumps(out))
'''

# Executado no host do gNB (bash -s acao nome dir): só systemctl nas units ocudu-gnb@*.
COMMAND = r'''
set -u
A="$1"; N="$2"; D="$3"
running() { systemctl list-units --plain --no-legend --state=active,activating 'ocudu-gnb@*' | awk '{print $1}'; }
case "$A" in
  start)
    [[ "$N" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "nome de arquivo inválido: $N"; exit 2; }
    [[ -r "$D/configs/$N.yml" ]] || { echo "não existe: $D/configs/$N.yml"; exit 2; }
    for u in $(running); do echo "parando $u"; systemctl stop "$u" || exit 1; done
    systemctl reset-failed 'ocudu-gnb@*' 2>/dev/null || true
    echo "iniciando ocudu-gnb@$N.service"
    systemctl start "ocudu-gnb@$N.service" || { journalctl -u "ocudu-gnb@$N.service" -n 15 --no-pager -o cat 2>/dev/null; exit 1; }
    ;;
  stop)
    u=$(running); [[ -n "$u" ]] || { echo "nenhum gNB rodando pelo serviço"; exit 0; }
    for x in $u; do echo "parando $x"; systemctl stop "$x" || exit 1; done
    ;;
  restart)
    u=$(running); [[ -n "$u" ]] || { echo "nenhum gNB rodando pelo serviço"; exit 1; }
    for x in $u; do echo "reiniciando $x"; systemctl restart "$x" || exit 1; done
    ;;
  *) echo "ação inválida"; exit 2 ;;
esac
'''


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def post(payload):
    req = urllib.request.Request(URL + "/api/ingest/gnb-ctl", data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Ingest-Token", TOKEN)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def remote(cmd, stdin, timeout):
    p = subprocess.run(SSH + [TARGET, cmd], input=stdin, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def status():
    rc, out, err = remote("python3 - %s" % shlex.quote(DIR), STATUS, 20)
    if rc != 0:
        raise OSError((err or out or "ssh código %d" % rc).strip()[-300:])
    st = json.loads(out)
    return k8s_status(st) if MODE == "k8s" else st


def kubectl(*a, timeout=15):
    p = subprocess.run(["kubectl", "-n", NS] + list(a), capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise OSError("kubectl: " + (p.stderr or p.stdout).strip()[-200:])
    return p.stdout


def _since(iso):
    try:
        t = time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        return time.strftime("%a %Y-%m-%d %H:%M:%S %Z", time.localtime(t))
    except (TypeError, ValueError):
        return None


def k8s_status(st):
    """Troca a parte "serviço systemd" do estado pela do Deployment/pod ocudu-gnb (mesmo formato p/ o painel)."""
    st["mode"] = "k8s"
    st["unit_installed"] = None   # sem unit/polkit no modo k8s: o aviso de instalação não se aplica
    st["polkit"] = None
    dep = json.loads(kubectl("get", "deploy", "ocudu-gnb", "-o", "json"))
    env = {e["name"]: e.get("value") for e in dep["spec"]["template"]["spec"]["containers"][0].get("env", [])}
    cfg, reps = env.get("GNB_CONFIG") or "", dep["spec"].get("replicas") or 0
    pods = json.loads(kubectl("get", "pods", "-l", "app.kubernetes.io/name=ocudu-gnb", "-o", "json"))["items"]
    pods = [p for p in pods if not p["metadata"].get("deletionTimestamp")]
    # gnb do pod: "-c /configs/…" (o nativo usa o caminho completo da pasta do OCUDU)
    mine = [x for x in st.get("gnb_pids", []) if " -c /configs/" in " " + x["cmd"]]
    st["manual"] = [x for x in st.get("gnb_pids", []) if x not in mine]
    st["active"] = st["failed"] = None
    st["k8s"] = {"replicas": reps, "config": cfg, "pod": None, "waiting_boot": False}
    if not pods:
        return st
    pod = pods[0]
    name = pod["metadata"]["name"]
    cs = (pod["status"].get("containerStatuses") or [{}])[0]
    state = cs.get("state") or {}
    try:
        journal = kubectl("logs", name, "--tail=25", timeout=10).splitlines()[-25:]
    except (OSError, subprocess.TimeoutExpired):
        journal = []
    waiting = any("NÃO liga sozinho" in l for l in journal) and not mine
    st["k8s"].update(pod=name, phase=pod["status"].get("phase"), restarts=cs.get("restartCount", 0),
                     waiting_boot=waiting, node=pod["spec"].get("nodeName"))
    info = {"unit": "pod/" + name, "config": cfg, "pid": mine[0]["pid"] if mine else 0,
            "since": _since((state.get("running") or {}).get("startedAt")), "journal": journal}
    bad = (state.get("waiting") or {}).get("reason") in ("CrashLoopBackOff", "Error", "ErrImageNeverPull",
                                                         "CreateContainerError", "CreateContainerConfigError")
    if reps and (bad or pod["status"].get("phase") in ("Failed", "Succeeded") or state.get("terminated")):
        reason = (state.get("waiting") or state.get("terminated") or {}).get("reason") or pod["status"].get("phase")
        st["failed"] = dict(info, state="failed", sub=reason, result=reason)
    elif state.get("running") and not waiting:
        st["active"] = dict(info, state="active", sub="running" if mine else "activating")
    return st


def execute_k8s(cmd):
    action, name = cmd.get("action"), cmd.get("config") or ""
    args = {"start": ["iniciar", name], "stop": ["parar"], "restart": ["iniciar"]}[action]
    if action == "start" and not name:
        return {"id": cmd.get("id"), "ok": False, "output": "falta o arquivo .yml"}
    try:
        p = subprocess.run([GNBSH] + args, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return {"id": cmd.get("id"), "ok": False, "output": "tempo esgotado (180 s)"}
    return {"id": cmd.get("id"), "ok": p.returncode == 0, "output": (p.stdout + p.stderr).strip()[-3000:]}


def execute(cmd):
    action, name = cmd.get("action"), cmd.get("config") or ""
    if action not in ("start", "stop", "restart") or (name and not NAME.match(name)):
        return {"id": cmd.get("id"), "ok": False, "output": "comando recusado pelo agente"}
    if MODE == "k8s":
        return execute_k8s(cmd)
    try:
        rc, out, err = remote("bash -s -- %s %s %s" % (action, shlex.quote(name or "-"), shlex.quote(DIR)),
                              COMMAND, 120)
    except subprocess.TimeoutExpired:
        return {"id": cmd.get("id"), "ok": False, "output": "tempo esgotado (120 s)"}
    text = (out + err).strip()
    if "Interactive authentication required" in text or "Access denied" in text:
        text += "\n(falta a regra do polkit no host do gNB: rode scripts/ocudu/setup-gnb-service.sh lá, com sudo)"
    return {"id": cmd.get("id"), "ok": rc == 0, "output": text[-3000:]}


def main():
    if MODE == "k8s" and not os.access(GNBSH, os.X_OK):
        print("modo k8s: GNB_CTL_GNBSH deve apontar para ran/ocudu/gnb.sh", file=sys.stderr)
        sys.exit(2)
    if not URL or not TOKEN or not TARGET or not DIR:
        print("uso: DASHBOARD_URL=... INGEST_TOKEN=... GNB_CTL_SSH=usuario@host GNB_CTL_DIR=/caminho/ocudu gnb-ctl-agent.py",
              file=sys.stderr)
        sys.exit(2)
    result = None
    last_err = None
    while True:
        t0 = time.time()
        try:
            st = status()
            if last_err:
                log("conectado de novo a", TARGET)
                last_err = None
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as e:
            st = {"error": str(e)[-300:]}
            if str(e) != last_err:
                log("estado do gNB:", e)
                last_err = str(e)
        try:
            r = post({"status": st, "result": result})
            result = None
            cmd = r.get("command")
            if cmd:
                log("comando:", cmd.get("action"), cmd.get("config") or "")
                result = execute(cmd)
                log("resultado:", "ok" if result["ok"] else "falhou", result["output"][-200:].replace("\n", " | "))
                continue   # manda o resultado e o estado novo já
        except (urllib.error.URLError, OSError, ValueError) as e:
            log("painel indisponível:", e)
        time.sleep(max(0.5, INTERVAL - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
