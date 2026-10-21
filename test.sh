#!/usr/bin/env bash
# =============================================================================
#  test.sh — valida o core 5G: pods, NG Setup (gNB<->AMF), registro dos UEs,
#  sessão PDU e ping pela interface do UE (uesimtunN).
#
#  Uso:  ./test.sh            (usa sudo automaticamente se o kubeconfig exigir)
#        ./test.sh -v         (mostra logs relevantes em caso de falha)
#  Código de saída: 0 = tudo OK, 1 = alguma verificação falhou.
# =============================================================================
set -Eeuo pipefail
source "$(dirname "$(readlink -f "$0")")/scripts/lib/common.sh"

VERBOSE=false
for a in "$@"; do
  case "$a" in
    -v|--verbose) VERBOSE=true ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "opção desconhecida: $a" ;;
  esac
done

load_config
[[ -r "${KUBECONFIG_PATH}" ]] || exec sudo --preserve-env=CONFIG "$0" "$@"
k3s_ready || die "k3s não está no ar (sudo systemctl status k3s)"
validate_config

PASS=0; FAIL=0
pass() { ok "$*"; PASS=$((PASS+1)); }
fail() { err "$*"; FAIL=$((FAIL+1)); }
NS="${K8S_NAMESPACE}"
GNB_DEP="deploy/${UERANSIM_RELEASE}"
UE_DEP="deploy/${UERANSIM_RELEASE}-ues"
ue_exec() { kc -n "${NS}" exec "${UE_DEP}" -c ues -- "$@"; }

dump_logs() {
  ${VERBOSE} || return 0
  echo; info "---- últimos logs: AMF ----"
  kc -n "${NS}" logs "deploy/${OPEN5GS_RELEASE}-amf" --tail=30 2>/dev/null || true
  info "---- SMF ----"; kc -n "${NS}" logs "deploy/${OPEN5GS_RELEASE}-smf" --tail=20 2>/dev/null || true
  info "---- UPF ----"; kc -n "${NS}" logs "deploy/${OPEN5GS_RELEASE}-upf" --tail=20 2>/dev/null || true
  info "---- gNB ----"; kc -n "${NS}" logs "${GNB_DEP}" --tail=20 2>/dev/null || true
  info "---- UE  ----"; kc -n "${NS}" logs "${UE_DEP}" --tail=40 2>/dev/null || true
}

finish() {
  echo
  if (( FAIL == 0 )); then
    echo "${C_GRN}${C_B}RESULTADO: ${PASS} verificações OK, 0 falhas${C_0}"
    exit 0
  fi
  dump_logs
  echo "${C_RED}${C_B}RESULTADO: ${PASS} OK, ${FAIL} falha(s)${C_0}  (use -v para ver logs)"
  echo "    Depois de reboot/restart do k3s, tente: ./scripts/heal.sh"
  exit 1
}

# 1) Pods -----------------------------------------------------------------------
step "Pods no namespace ${NS}"
not_ready=$(kc -n "${NS}" get pods --no-headers \
  -o custom-columns=N:.metadata.name,R:.status.containerStatuses[*].ready,P:.status.phase \
  | awk '$3!="Running" || $2 ~ /false/ {print $1" ("$3")"}')
if [[ -z "${not_ready}" ]]; then
  pass "todos os pods Running/Ready ($(kc -n "${NS}" get pods --no-headers | wc -l))"
else
  fail "pods não prontos: $(echo "${not_ready}" | tr '\n' ' ')"
fi
for nf in nrf scp amf smf upf ausf udm udr pcf bsf nssf; do
  if kc -n "${NS}" get "deploy/${OPEN5GS_RELEASE}-${nf}" &>/dev/null; then :; else fail "NF ${nf} ausente"; fi
done

if ! kc -n "${NS}" get "${UE_DEP}" &>/dev/null; then
  fail "UERANSIM não implantado (DEPLOY_UERANSIM=${DEPLOY_UERANSIM}); testes de UE impossíveis"
  finish
fi

# 2) Registro dos NFs no NRF ------------------------------------------------------
step "NRF"
nrf_log=$(kc -n "${NS}" logs "deploy/${OPEN5GS_RELEASE}-nrf" 2>/dev/null || true)
n_reg=$(grep -c "NF registered" <<<"${nrf_log}" || true)
if (( n_reg >= 7 )); then pass "NRF registrou ${n_reg} NF(s)"; else fail "NRF registrou só ${n_reg} NF(s) (esperado >= 7)"; fi

# 3) NG Setup gNB <-> AMF (N2/SCTP) ---------------------------------------------
step "N2: NG Setup"
deadline=$(( SECONDS + TEST_TIMEOUT ))
until kc -n "${NS}" logs "${GNB_DEP}" 2>/dev/null | grep -q "NG Setup procedure is successful"; do
  (( SECONDS < deadline )) || break; sleep 3
done
if kc -n "${NS}" logs "${GNB_DEP}" 2>/dev/null | grep -q "NG Setup procedure is successful"; then
  if is_true "${RAN_LINK_ENABLED}"; then
    pass "gNB fez NG Setup com o AMF (${AMF_N2_IP}:38412/SCTP pelo link ${RAN_LINK_IFACE})"
  else
    pass "gNB fez NG Setup com o AMF (${OPEN5GS_RELEASE}-amf-ngap:38412/SCTP)"
  fi
else
  fail "gNB não completou NG Setup (verifique PLMN/TAC e SCTP)"
  finish
fi

# 4) Registro e sessão PDU de cada UE --------------------------------------------
parse_slice "${SLICES[0]}"
step "UEs: registro (5GMM) e sessão PDU (DNN ${S_DNN}, S-NSSAI ${S_SST}/${S_SD})"
for (( i = 0; i < UE_COUNT; i++ )); do
  imsi=$(ue_imsi "$i"); tun="uesimtun${i}"
  deadline=$(( SECONDS + TEST_TIMEOUT )); status=""
  while (( SECONDS < deadline )); do
    status=$(ue_exec nr-cli "imsi-${imsi}" --exec status 2>/dev/null || true)
    grep -q "RM-REGISTERED" <<<"${status}" && ue_exec ip -4 -o addr show "${tun}" &>/dev/null && break
    sleep 3
  done
  if grep -q "RM-REGISTERED" <<<"${status}"; then
    pass "imsi-${imsi}: registrado ($(grep -o 'MM-REGISTERED[^ ]*' <<<"${status}" | head -1))"
  else
    fail "imsi-${imsi}: não registrou (assinante cadastrado? K/OPC/PLMN/slice batem?)"
    continue
  fi
  ue_ip=$(ue_exec ip -4 -o addr show "${tun}" 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || true)
  if [[ -n "${ue_ip}" ]] && ip_in_cidr "${ue_ip}" "${S_SUBNET}"; then
    pass "imsi-${imsi}: sessão PDU ativa, ${tun} = ${ue_ip} (pool ${S_SUBNET})"
  else
    fail "imsi-${imsi}: sem sessão PDU/IP válido em ${tun} (obtido: '${ue_ip:-nenhum}')"
    continue
  fi

  # 5) Plano de usuário: ping via GTP-U (N3) até o UPF e, opcionalmente, N6
  if ue_exec ping -I "${tun}" -c "${TEST_PING_COUNT}" -W 2 -q "${S_GW}" >/dev/null 2>&1; then
    pass "imsi-${imsi}: ping ${S_GW} (gateway no UPF) via ${tun}"
  else
    fail "imsi-${imsi}: ping ${S_GW} via ${tun} falhou (N3/GTP-U ou UPF)"
  fi
  if is_true "${TEST_INTERNET}"; then
    out=$(ue_exec ping -I "${tun}" -c "${TEST_PING_COUNT}" -W 3 -q "${TEST_PING_TARGET}" 2>&1 || true)
    if grep -q '% packet loss' <<<"${out}" && ! grep -q '100% packet loss' <<<"${out}"; then
      pass "imsi-${imsi}: ping ${TEST_PING_TARGET} via ${tun} ($(grep -o '[0-9.]*% packet loss' <<<"${out}"); rtt $(grep -o '= [0-9./]* ms' <<<"${out}" | cut -d/ -f2) ms)"
    else
      fail "imsi-${imsi}: ping ${TEST_PING_TARGET} via ${tun} falhou (NAT/N6 do UPF ou saída do host)"
    fi
  fi
done

finish
