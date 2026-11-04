#!/usr/bin/env bash
# =============================================================================
#  scripts/ue-traffic.sh — generates traffic on ALL UERANSIM UEs at the same time
#  (for demos: watch the dashboard while it runs).
#
#  One iperf3 server per UE runs on this machine (ports 5301, 5302, ...); each UE
#  runs an iperf3 client bound to its own interface (uesimtunN), so the traffic
#  crosses the whole user plane: UE -> gNB (sim) -> UPF -> N6 -> this machine.
#  No internet needed. Throughput is printed every 2 s per UE, and a summary at the end.
#
#  Usage: ./scripts/ue-traffic.sh [seconds] [down|up|both]   (default: 60 down; Ctrl+C stops)
#    TRAFFIC_RATE=50M ./scripts/ue-traffic.sh 120            (bit/s per UE; default 20M)
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${CONFIG:-${ROOT}/config.env}"
# shellcheck source=lib/common.sh
source "${ROOT}/scripts/lib/common.sh"
load_config
[[ -r "${KUBECONFIG_PATH}" ]] || exec sudo --preserve-env=CONFIG,TRAFFIC_RATE "$0" "$@"

SECS="${1:-60}"
DIR="${2:-down}"
RATE="${TRAFFIC_RATE:-20M}"
SERVER="${STABLE_IP:-${NODE_IP}}"
BASE_PORT=5301
UE_DEP="deploy/${UERANSIM_RELEASE}-ues"
[[ "${SECS}" =~ ^[0-9]+$ ]] || die "usage: $0 [seconds] [down|up|both]"
[[ "${RATE}" =~ ^[0-9]+[KkMmGg]?$ ]] || die "TRAFFIC_RATE: use e.g. 5M, 20M or 100M"
case "${DIR}" in down) MODE="-R" ;; up) MODE="" ;; both) MODE="--bidir" ;;
  *) die "direction: down, up or both" ;; esac
command -v iperf3 >/dev/null || die "iperf3 not installed on this machine (sudo apt install iperf3)"

ue_exec() { kc -n "${K8S_NAMESPACE}" exec "${UE_DEP}" -c ues -- "$@"; }
TUNS=$(ue_exec sh -c 'ip -o -4 addr | awk "/uesimtun/ {print \$2\"=\"\$4}"') || die "UE pod not found (${UE_DEP})"
[[ -n "${TUNS}" ]] || die "no uesimtun interface: are the UEs registered? (./test.sh)"

# iperf3 servers on this machine, one per UE; removed at the end (also on Ctrl+C)
PIDS=()
cleanup() { kill "${PIDS[@]}" 2>/dev/null || true; }
trap cleanup EXIT
trap 'echo; info "stopped"; exit 0' INT
n=0
for t in ${TUNS}; do
  iperf3 -s -1 -p $((BASE_PORT + n)) >/dev/null 2>&1 & PIDS+=($!)
  n=$((n + 1))
done
sleep 1

info "Traffic on ${n} UE(s) for ${SECS}s · direction: ${DIR} · ${RATE}bit/s per UE · server ${SERVER}"
# One shell inside the UE pod; one iperf3 client per uesimtunN, in parallel.
ue_exec sh -c '
  SECS=$1; SERVER=$2; PORT=$3; RATE=$4; MODE=$5; shift 5
  for t in "$@"; do
    dev=${t%%=*}; ip=${t#*=}; ip=${ip%/*}
    echo "  $dev  $ip  -> port $PORT"
    iperf3 -c "$SERVER" -p "$PORT" -B "$ip" -t "$SECS" -b "$RATE" -i 2 $MODE --forceflush 2>&1 |
      awk -v d="$dev" "
        /error/ { print \"  \" d \"  \" \$0; next }
        match(\$0, /[0-9.]+ [KMG]bits\\/sec/) {
          v = substr(\$0, RSTART, RLENGTH)
          if (\$0 ~ /receiver/) printf \"  %-10s TOTAL  %s\n\", d, v
          else if (\$0 !~ /sender/) printf \"  %-10s %s\n\", d, v
        }"  &
    PORT=$((PORT + 1))
  done
  wait
' sh "${SECS}" "${SERVER}" "${BASE_PORT}" "${RATE}" "${MODE}" ${TUNS}
ok "done"
