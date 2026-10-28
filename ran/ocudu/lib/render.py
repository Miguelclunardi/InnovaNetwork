#!/usr/bin/env python3
# =============================================================================
#  ran/ocudu/lib/render.py — manifestos do gNB OCUDU no Kubernetes.
#
#  Lê as variáveis do ocudu.env (no ambiente) e escreve no stdout: Namespace,
#  Deployment "ocudu-gnb" e o descritor do componente. Sem dependências.
#
#  O pod roda o MESMO comando do serviço nativo ocudu-gnb@:
#    taskset -c <CPUs> gnb -c <pasta>/<yml>.yml [-c <pasta>/metricas.yml]
#  com a rede e o hardware do host (hostNetwork + privileged), os .yml lidos da
#  pasta do host e o log no /tmp do host. Parar = SIGINT ao gNB (igual a Ctrl+C).
# =============================================================================
import json
import os
import sys

E = os.environ


def env(k, d=None):
    v = E.get(k, d)
    if v is None:
        sys.exit("render.py: falta %s" % k)
    return v


NS = env("OCUDU_NAMESPACE")
NODE = env("OCUDU_NODE")
CFG_DIR = env("OCUDU_CONFIG_DIR")
LOG_DIR = env("OCUDU_LOG_DIR")
IMAGE = "%s:%s" % (env("OCUDU_IMAGE"), env("OCUDU_IMAGE_TAG"))
LABELS = {"app.kubernetes.io/name": "ocudu-gnb", "app.kubernetes.io/part-of": "innovanetwork"}

# Script do contêiner: confere o .yml, recusa se já houver um gnb no host (o serviço
# nativo, por exemplo) e repassa o TERM do Kubernetes como INT ao gNB.
RUN = r'''
set -u
# Depois de um reboot do nó o gNB NÃO liga sozinho (o GPS pode levar até ~30 min e a RU precisa do relógio
# certo): só liga se o último "gnb.sh iniciar" (GNB_START_REQUEST, epoch) for posterior ao boot do nó.
# /proc/stat não é isolado por contêiner: btime é a hora de boot do host.
btime=$(awk '/^btime/{print $2}' /proc/stat)
if [ "${GNB_START_REQUEST:-0}" -lt "$btime" ]; then
  echo "ocudu-gnb: o nó reiniciou depois do último pedido de início ($(date -d @"${GNB_START_REQUEST:-0}" '+%F %T' 2>/dev/null))."
  echo "ocudu-gnb: o gNB NÃO liga sozinho. Confira o GPS (ts2phc 's2') e a RU e rode: ./ran/ocudu/gnb.sh iniciar"
  trap 'exit 0' TERM INT
  while :; do sleep 3600 & wait $!; done
fi
cfg="/configs/${GNB_CONFIG}.yml"
[ -r "$cfg" ] || { echo "ocudu-gnb: não achei $cfg"; exit 1; }
extra=""
if [ -n "${GNB_EXTRA_CONFIG}" ] && [ -r "/configs/${GNB_EXTRA_CONFIG}" ]; then
  extra="-c /configs/${GNB_EXTRA_CONFIG}"
fi
for c in /proc/[0-9]*/comm; do
  if [ "$(cat "$c" 2>/dev/null)" = gnb ]; then
    echo "ocudu-gnb: já existe um gnb rodando no host (serviço ocudu-gnb@ ou terminal): pare-o antes"
    exit 1
  fi
done
# log do .yml (log.filename) no /tmp do host: se ficou de outro dono (ex.: uid 1001 da imagem), o root
# não consegue reabrir por causa do fs.protected_regular; remove só nesse caso
logf=$(awk '/^log:/{l=1;next} l&&/^[^ #]/{l=0} l&&/filename:/{print $2; exit}' "$cfg")
if [ -n "$logf" ] && [ -e "$logf" ] && [ "$(stat -c %u "$logf")" != 0 ]; then
  echo "ocudu-gnb: removendo $logf (dono $(stat -c %u "$logf"), não root)"; rm -f "$logf"
fi
command -v taskset >/dev/null || { echo "ocudu-gnb: a imagem não tem taskset (util-linux)"; exit 1; }
echo "ocudu-gnb: taskset -c ${GNB_CPUS} gnb -c $cfg $extra"
taskset -c "${GNB_CPUS}" gnb -c "$cfg" $extra &
pid=$!
trap 'echo "ocudu-gnb: parando (SIGINT)"; kill -INT $pid' TERM INT
wait $pid; rc=$?
trap - TERM INT
wait $pid 2>/dev/null; rc2=$?
[ $rc2 -ne 127 ] && rc=$rc2
echo "ocudu-gnb: gnb terminou (código $rc)"
exit $rc
'''

namespace = {
    "apiVersion": "v1", "kind": "Namespace",
    "metadata": {"name": NS, "labels": {"innovanetwork/component": "ocudu"}},
}

deployment = {
    "apiVersion": "apps/v1", "kind": "Deployment",
    "metadata": {"name": "ocudu-gnb", "namespace": NS, "labels": LABELS},
    "spec": {
        "replicas": int(env("OCUDU_REPLICAS", "0")),  # 0 = parado; ligar = 1 (gnb.sh ou painel)
        "strategy": {"type": "Recreate"},    # nunca dois gNBs ao mesmo tempo
        "selector": {"matchLabels": {"app.kubernetes.io/name": "ocudu-gnb"}},
        "template": {
            "metadata": {"labels": LABELS},
            "spec": {
                "nodeSelector": {"kubernetes.io/hostname": NODE},
                "tolerations": [{"key": "innovanetwork/ran", "operator": "Exists", "effect": "NoSchedule"}],
                "hostNetwork": True,         # N2/N3 em 10.10.0.1, métricas :8001, como no host
                "hostPID": True,             # para enxergar um gnb nativo e recusar
                "dnsPolicy": "ClusterFirstWithHostNet",
                "terminationGracePeriodSeconds": 30,
                "containers": [{
                    "name": "gnb",
                    "image": IMAGE,
                    "imagePullPolicy": "Never",   # imagem local, importada no containerd do k3s
                    # privileged + root: DPDK/vfio, hugepages, /proc/self/pagemap, RT. A imagem oficial
                    # roda como USER 1001; o serviço nativo ocudu-gnb@ roda como root (igual aqui).
                    "securityContext": {"privileged": True, "runAsUser": 0, "runAsGroup": 0},
                    "command": ["/bin/bash", "-c", RUN],
                    # O Kubernetes limita as hugepages do pod ao que ele pede (sem pedido = 0 e o DPDK
                    # falha com "Cannot init memory"). Memória: só pedido, sem limite.
                    "resources": {
                        "requests": {"hugepages-1Gi": env("OCUDU_HUGEPAGES_1G"), "memory": env("OCUDU_MEMORY_REQUEST")},
                        "limits": {"hugepages-1Gi": env("OCUDU_HUGEPAGES_1G")},
                    },
                    "env": [
                        {"name": "GNB_CONFIG", "value": env("OCUDU_GNB_CONFIG", env("OCUDU_DEFAULT_CONFIG"))},
                        {"name": "GNB_EXTRA_CONFIG", "value": env("OCUDU_EXTRA_CONFIG", "")},
                        {"name": "GNB_CPUS", "value": env("OCUDU_CPUS")},
                        {"name": "GNB_START_REQUEST", "value": env("OCUDU_START_REQUEST", "0")},
                    ],
                    "volumeMounts": [
                        {"name": "configs", "mountPath": "/configs", "readOnly": True},
                        {"name": "hugepages", "mountPath": "/dev/hugepages"},
                        {"name": "logs", "mountPath": LOG_DIR},
                    ],
                }],
                "volumes": [
                    {"name": "configs", "hostPath": {"path": CFG_DIR, "type": "Directory"}},
                    {"name": "hugepages", "hostPath": {"path": "/dev/hugepages", "type": "Directory"}},
                    {"name": "logs", "hostPath": {"path": LOG_DIR, "type": "Directory"}},
                ],
            },
        },
    },
}

# Descritor do componente (contrato da v3): ferramentas como o painel descobrem o que está instalado.
descriptor = {
    "apiVersion": "v1", "kind": "ConfigMap",
    "metadata": {"name": "innovanetwork-component", "namespace": NS,
                 "labels": {"innovanetwork/component": "ocudu"}},
    "data": {
        "kind": "ran",
        "type": "ocudu",
        "name": "gNB OCUDU",
        "deployment": "ocudu-gnb",
        "node": NODE,
        "config_dir": CFG_DIR,
        "config_env": "GNB_CONFIG",
        "default_config": env("OCUDU_DEFAULT_CONFIG"),
        "image": IMAGE,
    },
}

print(json.dumps({"apiVersion": "v1", "kind": "List", "items": [namespace, descriptor, deployment]},
                 indent=1, ensure_ascii=False))
