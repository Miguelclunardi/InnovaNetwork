#!/usr/bin/env bash
# =============================================================================
#  ran/ocudu/gnb.sh — starts/stops the OCUDU gNB on Kubernetes (no sudo, on torre2).
#
#    ./ran/ocudu/gnb.sh start [yml]   starts with the .yml (no extension; default: the current one)
#    ./ran/ocudu/gnb.sh stop          stops (SIGINT to the gNB, like Ctrl+C)
#    ./ran/ocudu/gnb.sh status        pod, .yml, node, start time
#    ./ran/ocudu/gnb.sh log [-f]      gNB output (the full log is /tmp/gnb.log on the node)
#    ./ran/ocudu/gnb.sh configs       .yml files available on the node and the AMF of each
#
#  The pt-BR commands still work: iniciar = start, parar = stop, estado = status.
#  The native ocudu-gnb@ service must be stopped: both use the same RU and VF
#  (the pod refuses to start if a gnb is running on the host).
# =============================================================================
set -Eeuo pipefail
OC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ocudu.env
source "${OC_DIR}/ocudu.env"
NS="${OCUDU_NAMESPACE}"
k() { kubectl -n "${NS}" "$@"; }
die() { echo "[error] $*" >&2; exit 1; }
cur_cfg() { k get deploy ocudu-gnb -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="GNB_CONFIG")].value}'; }

state() {
  local rep pod
  rep="$(k get deploy ocudu-gnb -o jsonpath='{.spec.replicas}')"
  echo "replicas: ${rep}   .yml: $(cur_cfg)"
  pod="$(k get pods -l app.kubernetes.io/name=ocudu-gnb -o name 2>/dev/null | head -1)"
  if [[ -n "${pod}" ]]; then
    k get "${pod}" -o jsonpath='pod: {.metadata.name}  phase: {.status.phase}  node: {.spec.nodeName}  started: {.status.startTime}  restarts: {.status.containerStatuses[0].restartCount}{"\n"}'
  else
    echo "pod: none (gNB stopped)"
  fi
}

case "${1:-}" in
  start|iniciar)
    cfg="${2:-$(cur_cfg)}"
    ssh -o BatchMode=yes "${OCUDU_NODE_SSH}" "test -r '${OCUDU_CONFIG_DIR}/${cfg}.yml'" \
      || die "${cfg}.yml does not exist in ${OCUDU_CONFIG_DIR} on the node"
    if ssh -o BatchMode=yes "${OCUDU_NODE_SSH}" "systemctl list-units --no-legend --state=active 'ocudu-gnb@*' | grep -q ."; then
      die "the native ocudu-gnb@ service is running on the node: stop it first"
    fi
    # .yml + request time (the pod only starts the gNB if the request is newer than the node boot)
    k set env deploy/ocudu-gnb GNB_CONFIG="${cfg}" GNB_START_REQUEST="$(date +%s)" >/dev/null
    k scale deploy/ocudu-gnb --replicas=1 >/dev/null
    echo "starting with ${cfg}.yml; waiting for the pod…"
    k rollout status deploy/ocudu-gnb --timeout=120s >/dev/null || true
    state
    echo "follow it: $0 log -f"
    ;;
  stop|parar)
    k scale deploy/ocudu-gnb --replicas=0 >/dev/null
    echo "stopping…"
    k wait --for=delete pod -l app.kubernetes.io/name=ocudu-gnb --timeout=60s >/dev/null 2>&1 || true
    state
    ;;
  status|estado)  state ;;
  log)     shift; k logs deploy/ocudu-gnb --tail=200 "$@" ;;
  configs)
    ssh -o BatchMode=yes "${OCUDU_NODE_SSH}" "cd '${OCUDU_CONFIG_DIR}' && for f in *.yml; do
      a=\$(awk '/^cu_cp:/{c=1} c&&/^ *addr:/{print \$2; exit}' \"\$f\"); [ -n \"\$a\" ] && printf '%-40s AMF %s\n' \"\${f%.yml}\" \"\$a\"; done; true"
    ;;
  *) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
