#!/usr/bin/env bash
# =============================================================================
#  free5gc/uninstall.sh — remove SÓ o free5GC (namespace dele, inclusive os
#  assinantes do MongoDB dele). Não toca no Open5GS, no k3s nem no gtp5g
#  (para tirar o módulo: sudo ./free5gc/setup-gtp5g.sh --remove).
#  Uso: ./free5gc/uninstall.sh [--sim]
# =============================================================================
set -Eeuo pipefail
F5_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=free5gc.env
source "${F5_DIR}/free5gc.env"
if [[ "${1:-}" != "--sim" ]]; then
  read -r -p "Apagar o namespace ${F5_NAMESPACE} (free5GC e os assinantes dele)? [s/N] " r
  [[ "${r,,}" == s* ]] || { echo "nada feito"; exit 0; }
fi
helm -n "${F5_NAMESPACE}" uninstall "${F5_UERANSIM_RELEASE}" >/dev/null 2>&1 || true
kubectl delete namespace "${F5_NAMESPACE}" --ignore-not-found --wait=true
echo "free5GC removido (certificados de teste continuam em ~/.config/innovanetwork/free5gc)"
