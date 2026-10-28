#!/usr/bin/env bash
# =============================================================================
#  ran/ocudu/gnb.sh — liga/para o gNB OCUDU no Kubernetes (sem sudo, no torre2).
#
#    ./ran/ocudu/gnb.sh iniciar [yml]   liga com o .yml (sem extensão; padrão: o atual)
#    ./ran/ocudu/gnb.sh parar           para (SIGINT ao gNB, como Ctrl+C)
#    ./ran/ocudu/gnb.sh estado          pod, .yml, nó, início
#    ./ran/ocudu/gnb.sh log [-f]        saída do gNB (o log completo fica em /tmp/gnb.log no nó)
#    ./ran/ocudu/gnb.sh configs         .yml disponíveis no nó e o AMF de cada um
#
#  O serviço nativo ocudu-gnb@ precisa estar parado: os dois usam a mesma RU e VF
#  (o pod recusa iniciar se houver um gnb rodando no host).
# =============================================================================
set -Eeuo pipefail
OC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ocudu.env
source "${OC_DIR}/ocudu.env"
NS="${OCUDU_NAMESPACE}"
k() { kubectl -n "${NS}" "$@"; }
die() { echo "[erro] $*" >&2; exit 1; }
cur_cfg() { k get deploy ocudu-gnb -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="GNB_CONFIG")].value}'; }

state() {
  local rep pod
  rep="$(k get deploy ocudu-gnb -o jsonpath='{.spec.replicas}')"
  echo "réplicas: ${rep}   .yml: $(cur_cfg)"
  pod="$(k get pods -l app.kubernetes.io/name=ocudu-gnb -o name 2>/dev/null | head -1)"
  if [[ -n "${pod}" ]]; then
    k get "${pod}" -o jsonpath='pod: {.metadata.name}  fase: {.status.phase}  nó: {.spec.nodeName}  início: {.status.startTime}  reinícios: {.status.containerStatuses[0].restartCount}{"\n"}'
  else
    echo "pod: nenhum (gNB parado)"
  fi
}

case "${1:-}" in
  iniciar)
    cfg="${2:-$(cur_cfg)}"
    ssh -o BatchMode=yes "${OCUDU_NODE_SSH}" "test -r '${OCUDU_CONFIG_DIR}/${cfg}.yml'" \
      || die "${cfg}.yml não existe em ${OCUDU_CONFIG_DIR} no nó"
    if ssh -o BatchMode=yes "${OCUDU_NODE_SSH}" "systemctl list-units --no-legend --state=active 'ocudu-gnb@*' | grep -q ."; then
      die "o serviço nativo ocudu-gnb@ está ligado no nó: pare-o antes"
    fi
    # .yml + hora do pedido (o pod só liga o gNB se o pedido for posterior ao boot do nó)
    k set env deploy/ocudu-gnb GNB_CONFIG="${cfg}" GNB_START_REQUEST="$(date +%s)" >/dev/null
    k scale deploy/ocudu-gnb --replicas=1 >/dev/null
    echo "ligando com ${cfg}.yml; esperando o pod…"
    k rollout status deploy/ocudu-gnb --timeout=120s >/dev/null || true
    state
    echo "acompanhe: $0 log -f"
    ;;
  parar)
    k scale deploy/ocudu-gnb --replicas=0 >/dev/null
    echo "parando…"
    k wait --for=delete pod -l app.kubernetes.io/name=ocudu-gnb --timeout=60s >/dev/null 2>&1 || true
    state
    ;;
  estado)  state ;;
  log)     shift; k logs deploy/ocudu-gnb --tail=200 "$@" ;;
  configs)
    ssh -o BatchMode=yes "${OCUDU_NODE_SSH}" "cd '${OCUDU_CONFIG_DIR}' && for f in *.yml; do
      a=\$(awk '/^cu_cp:/{c=1} c&&/^ *addr:/{print \$2; exit}' \"\$f\"); [ -n \"\$a\" ] && printf '%-40s AMF %s\n' \"\${f%.yml}\" \"\$a\"; done; true"
    ;;
  *) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
