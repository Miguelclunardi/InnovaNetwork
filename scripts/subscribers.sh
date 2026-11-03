#!/usr/bin/env bash
# =============================================================================
#  scripts/subscribers.sh — manages subscribers in the Open5GS MongoDB
#  (runs open5gs-dbctl inside the "populate" pod).
#
#    sudo ./scripts/subscribers.sh sync                     # applies the UEs + SUBSCRIBERS of config.env
#    sudo ./scripts/subscribers.sh list                     # IMSI, K, OPC, DNN, IP
#    sudo ./scripts/subscribers.sh add IMSI K OPC [SST SD DNN]
#    sudo ./scripts/subscribers.sh remove IMSI
#    sudo ./scripts/subscribers.sh reset                    # DELETES every subscriber
#
#  Changes made with add/remove are not stored in config.env: to persist them,
#  edit SUBSCRIBERS in config.env and run 'sync' (or ./install.sh).
# =============================================================================
set -Eeuo pipefail
source "$(dirname "$(readlink -f "$0")")/lib/common.sh"

load_config
[[ -r "${KUBECONFIG_PATH}" ]] || exec sudo --preserve-env=CONFIG "$0" "$@"
k3s_ready || die "k3s is not running"
validate_config

cmd="${1:-}"; shift || true
case "${cmd}" in
  sync)
    sync_subscribers ;;
  list)
    populate_exec "open5gs-dbctl showfiltered" ;;
  add)
    (( $# == 3 || $# == 6 )) || die "usage: add IMSI K OPC [SST SD DNN]"
    [[ "$1" =~ ^[0-9]{15}$ ]] || die "the IMSI must have 15 digits"
    [[ "$2" =~ ^[0-9A-Fa-f]{32}$ && "$3" =~ ^[0-9A-Fa-f]{32}$ ]] || die "K/OPC devem ter 32 hex"
    parse_slice "${SLICES[0]}"
    sst=${4:-$S_SST}; sd=${5:-$S_SD}; dnn=${6:-$S_DNN}
    [[ "${sst}" =~ ^[0-9]{1,3}$ && "${sd}" =~ ^[0-9A-Fa-f]{6}$ && "${dnn}" =~ ^[A-Za-z0-9.-]+$ ]] || die "invalid SST/SD/DNN"
    populate_exec "open5gs-dbctl remove $1 >/dev/null 2>&1 || true
open5gs-dbctl add_ue_with_slice $1 ${2^^} ${3^^} ${dnn} ${sst} ${sd,,} >/dev/null"
    ok "subscriber $1 (DNN=${dnn}, S-NSSAI=${sst}/${sd,,}) added" ;;
  remove)
    [[ "${1:-}" =~ ^[0-9]{15}$ ]] || die "usage: remove IMSI (15 digits)"
    populate_exec "open5gs-dbctl remove $1 >/dev/null"
    ok "subscriber $1 removed" ;;
  reset)
    read -r -p "    Delete ALL subscribers? [y/N] " r
    [[ "${r,,}" =~ ^(s|sim|y|yes)$ ]] || exit 0
    populate_exec "open5gs-dbctl reset >/dev/null"
    ok "subscriber database cleared" ;;
  *)
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
