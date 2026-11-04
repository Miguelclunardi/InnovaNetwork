#!/usr/bin/env bash
# =============================================================================
#  free5gc/uninstall.sh — removes ONLY free5GC (its namespace, including the
#  subscribers in its MongoDB). Does not touch Open5GS, k3s or gtp5g
#  (to remove the module: sudo ./free5gc/setup-gtp5g.sh --remove).
#  Usage: ./free5gc/uninstall.sh [--sim]
# =============================================================================
set -Eeuo pipefail
F5_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=free5gc.env
source "${F5_DIR}/free5gc.env"
if [[ "${1:-}" != "--sim" ]]; then
  read -r -p "Delete the namespace ${F5_NAMESPACE} (free5GC and its subscribers)? [y/N] " r
  [[ "${r,,}" == y* ]] || { echo "nothing done"; exit 0; }
fi
helm -n "${F5_NAMESPACE}" uninstall "${F5_UERANSIM_RELEASE}" >/dev/null 2>&1 || true
kubectl delete namespace "${F5_NAMESPACE}" --ignore-not-found --wait=true
echo "free5GC removed (the test certificates stay in ~/.config/innovanetwork/free5gc)"
