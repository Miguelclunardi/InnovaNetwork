#!/usr/bin/env bash
# =============================================================================
#  free5gc/test.sh — confere o free5GC: pods prontos, NG Setup do gNB simulado,
#  registro do UE, sessão PDU e ping pela interface do UE (uesimtunN).
#  Uso: ./free5gc/test.sh
# =============================================================================
set -Eeuo pipefail
F5_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${F5_DIR}")"
# shellcheck source=../scripts/lib/common.sh
source "${PROJECT_DIR}/scripts/lib/common.sh"
load_config
# shellcheck source=free5gc.env
source "${F5_DIR}/free5gc.env"
NS="${F5_NAMESPACE}"; REL="${F5_UERANSIM_RELEASE}"
P=0; F=0
pass() { echo "    ${C_GRN}[ok]${C_0} $*"; P=$((P+1)); }
fail() { echo "    ${C_RED}[falhou]${C_0} $*"; F=$((F+1)); }

step "free5GC (${NS})"
notready=$(kubectl -n "${NS}" get pods --no-headers 2>/dev/null | awk '$2 !~ /^([0-9]+)\/\1$/ || $3 != "Running" {print $1}')
total=$(kubectl -n "${NS}" get pods --no-headers 2>/dev/null | wc -l)
[[ ${total} -gt 0 && -z "${notready}" ]] && pass "${total} pods prontos" || fail "pods não prontos: ${notready:-nenhum pod}"
kubectl -n "${NS}" logs deploy/amf --tail=-1 2>/dev/null | grep -q "ngap_server\|NGAP server\|Listen on ${F5_AMF_N2_IP}" \
  && pass "AMF escutando N2 em ${F5_AMF_N2_IP}" || true
kubectl -n "${NS}" logs deploy/smf --tail=-1 2>/dev/null | grep -qi "association.*\(setup\|success\)" \
  && pass "SMF associado ao UPF (PFCP)" || fail "SMF sem associação PFCP com o UPF"
kubectl -n "${NS}" logs "deploy/${REL}" --tail=-1 2>/dev/null | grep -q "NG Setup procedure is successful" \
  && pass "gNB simulado: NG Setup ok" || fail "gNB simulado sem NG Setup"

ue() { kubectl -n "${NS}" exec "deploy/${REL}-ues" -- "$@"; }
for (( i = 0; i < UE_COUNT; i++ )); do
  tun="uesimtun${i}"
  if ue ip -4 -o addr show "${tun}" 2>/dev/null | grep -q inet; then
    pass "UE ${i}: sessão PDU ($(ue ip -4 -o addr show "${tun}" | awk '{print $4}'))"
    out=$(ue ping -I "${tun}" -c "${TEST_PING_COUNT}" -W 3 -q "${TEST_PING_TARGET}" 2>&1 || true)
    grep -q ' 0% packet loss' <<<"${out}" && pass "UE ${i}: ping ${TEST_PING_TARGET} via ${tun}" \
      || fail "UE ${i}: ping ${TEST_PING_TARGET} falhou ($(grep -o '[0-9.]*% packet loss' <<<"${out}" || echo sem resposta))"
  else
    fail "UE ${i}: sem ${tun} (registro ou sessão PDU)"
  fi
done
echo; echo "    resultado: ${P} ok, ${F} falha(s)"
(( F == 0 ))
