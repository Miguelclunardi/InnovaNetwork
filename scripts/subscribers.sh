#!/usr/bin/env bash
# =============================================================================
#  scripts/subscribers.sh — gerencia assinantes no MongoDB do Open5GS
#  (executa open5gs-dbctl dentro do pod "populate").
#
#    sudo ./scripts/subscribers.sh sync                     # aplica UEs + SUBSCRIBERS do config.env
#    sudo ./scripts/subscribers.sh list                     # IMSI, K, OPC, DNN, IP
#    sudo ./scripts/subscribers.sh add IMSI K OPC [SST SD DNN]
#    sudo ./scripts/subscribers.sh remove IMSI
#    sudo ./scripts/subscribers.sh reset                    # APAGA todos os assinantes
#
#  Alterações via add/remove não ficam no config.env: para persistir,
#  edite SUBSCRIBERS no config.env e rode 'sync' (ou ./install.sh).
# =============================================================================
set -Eeuo pipefail
source "$(dirname "$(readlink -f "$0")")/lib/common.sh"

load_config
[[ -r "${KUBECONFIG_PATH}" ]] || exec sudo --preserve-env=CONFIG "$0" "$@"
k3s_ready || die "k3s não está no ar"
validate_config

cmd="${1:-}"; shift || true
case "${cmd}" in
  sync)
    sync_subscribers ;;
  list)
    populate_exec "open5gs-dbctl showfiltered" ;;
  add)
    (( $# == 3 || $# == 6 )) || die "uso: add IMSI K OPC [SST SD DNN]"
    [[ "$1" =~ ^[0-9]{15}$ ]] || die "IMSI deve ter 15 dígitos"
    [[ "$2" =~ ^[0-9A-Fa-f]{32}$ && "$3" =~ ^[0-9A-Fa-f]{32}$ ]] || die "K/OPC devem ter 32 hex"
    parse_slice "${SLICES[0]}"
    sst=${4:-$S_SST}; sd=${5:-$S_SD}; dnn=${6:-$S_DNN}
    [[ "${sst}" =~ ^[0-9]{1,3}$ && "${sd}" =~ ^[0-9A-Fa-f]{6}$ && "${dnn}" =~ ^[A-Za-z0-9.-]+$ ]] || die "SST/SD/DNN inválidos"
    populate_exec "open5gs-dbctl remove $1 >/dev/null 2>&1 || true
open5gs-dbctl add_ue_with_slice $1 ${2^^} ${3^^} ${dnn} ${sst} ${sd,,} >/dev/null"
    ok "assinante $1 (DNN=${dnn}, S-NSSAI=${sst}/${sd,,}) adicionado" ;;
  remove)
    [[ "${1:-}" =~ ^[0-9]{15}$ ]] || die "uso: remove IMSI(15 dígitos)"
    populate_exec "open5gs-dbctl remove $1 >/dev/null"
    ok "assinante $1 removido" ;;
  reset)
    read -r -p "    Apagar TODOS os assinantes? [s/N] " r
    [[ "${r,,}" =~ ^(s|sim|y|yes)$ ]] || exit 0
    populate_exec "open5gs-dbctl reset >/dev/null"
    ok "base de assinantes zerada" ;;
  *)
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
