#!/usr/bin/env bash
# =============================================================================
#  free5gc/test.sh — checks free5GC: pods ready, NG Setup of the simulated gNB,
#  UE registration, PDU session and ping through the UE interface (uesimtunN).
#  Usage: ./free5gc/test.sh
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
fail() { echo "    ${C_RED}[failed]${C_0} $*"; F=$((F+1)); }

step "free5GC (${NS})"
notready=$(kubectl -n "${NS}" get pods --no-headers 2>/dev/null | awk '{split($2, r, "/"); if (r[1] != r[2] || $3 != "Running") print $1}' | paste -sd' ')
total=$(kubectl -n "${NS}" get pods --no-headers 2>/dev/null | wc -l)
[[ ${total} -gt 0 && -z "${notready}" ]] && pass "${total} pods ready" || fail "pods not ready: ${notready:-no pods}"
grep -q "ngap_server\|NGAP server\|Listen on ${F5_AMF_N2_IP}"  <<<"$(kubectl -n "${NS}" logs deploy/amf --tail=-1 2>/dev/null)" \
  && pass "AMF listening for N2 on ${F5_AMF_N2_IP}" || true
grep -qi "association.*\(setup\|success\)"  <<<"$(kubectl -n "${NS}" logs deploy/smf --tail=-1 2>/dev/null)" \
  && pass "SMF associated with the UPF (PFCP)" || fail "SMF without a PFCP association with the UPF"
kubectl -n "${NS}" logs "deploy/${REL}" --tail=-1 2>/dev/null | grep -q "NG Setup procedure is successful" \
  && pass "simulated gNB: NG Setup ok" || fail "simulated gNB without NG Setup"

ue() { kubectl -n "${NS}" exec "deploy/${REL}-ues" -- "$@"; }
for (( i = 0; i < UE_COUNT; i++ )); do
  tun="uesimtun${i}"
  if ue ip -4 -o addr show "${tun}" 2>/dev/null | grep -q inet; then
    pass "UE ${i}: PDU session ($(ue ip -4 -o addr show "${tun}" | awk '{print $4}'))"
    out=$(ue ping -I "${tun}" -c "${TEST_PING_COUNT}" -W 3 -q "${TEST_PING_TARGET}" 2>&1 || true)
    grep -q ' 0% packet loss' <<<"${out}" && pass "UE ${i}: ping ${TEST_PING_TARGET} via ${tun}" \
      || fail "UE ${i}: ping ${TEST_PING_TARGET} failed ($(grep -o '[0-9.]*% packet loss' <<<"${out}" || echo no reply))"
  else
    fail "UE ${i}: no ${tun} (registration or PDU session)"
  fi
done
echo; echo "    result: ${P} ok, ${F} failure(s)"
(( F == 0 ))
