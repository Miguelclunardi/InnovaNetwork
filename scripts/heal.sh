#!/usr/bin/env bash
# =============================================================================
#  scripts/heal.sh — checks and recovers the core after a reboot/restart of k3s.
#
#  Waits for k3s and the pods to be ready, checks whether the UEs are registered
#  and pinging the UPF and, if they are not, restarts in order the UEs and then
#  UPF -> SMF -> gNB -> UEs (redoes the PFCP/N4 association and the NG Setup).
#
#  Usage: ./scripts/heal.sh            (uses sudo automatically if needed)
#         ./scripts/heal.sh --boot     (mode of the open5gs-k3s-heal unit: waits up to 15 min)
#         ./scripts/heal.sh --boot-off (CORE_AUTOSTART=false: at boot STOPS the cores and
#                                       UERANSIM — scale 0; the dashboard stays; start them
#                                       from the Control tab, which brings everything up in
#                                       order). Also applies to free5GC (namespaces with
#                                       the innovanetwork/core label).
#  Exit code: 0 = user plane OK, 1 = not recovered.
# =============================================================================
set -Eeuo pipefail
source "$(dirname "$(readlink -f "$0")")/lib/common.sh"

BOOT=false
OFF=false
for a in "$@"; do
  case "$a" in
    --boot) BOOT=true ;;
    --boot-off) BOOT=true; OFF=true ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $a" ;;
  esac
done

load_config
${BOOT} || [[ -r "${KUBECONFIG_PATH}" ]] || exec sudo --preserve-env=CONFIG "$0" "$@"
validate_config

wait_s=120; ${BOOT} && wait_s=900
step "Waiting for k3s"
t=0
until k3s_ready; do (( t += 5 )); (( t < wait_s )) || die "k3s did not answer within ${wait_s}s"; sleep 5; done
ok "k3s API ready"

kc get ns "${K8S_NAMESPACE}" &>/dev/null || { info "namespace ${K8S_NAMESPACE} does not exist; nothing to do"; exit 0; }
if ${OFF}; then
  step "Stopping the core and UERANSIM (CORE_AUTOSTART=false)"
  deps=$(kc -n "${K8S_NAMESPACE}" get deploy -o name | grep -v '^deployment.apps/dashboard$' || true)
  if [[ -n "${deps}" ]]; then
    # shellcheck disable=SC2086
    kc -n "${K8S_NAMESPACE}" scale --replicas=0 ${deps} >/dev/null
    ok "$(wc -w <<<"${deps}") deployment(s) at 0; start them from the dashboard Control tab"
  fi
  # other cores (free5GC): every namespace with the innovanetwork/core label
  for ns in $(kc get ns -l innovanetwork/core -o jsonpath='{.items[*].metadata.name}' 2>/dev/null); do
    deps=$(kc -n "${ns}" get deploy -o name || true)
    [[ -n "${deps}" ]] || continue
    # shellcheck disable=SC2086
    kc -n "${ns}" scale --replicas=0 ${deps} >/dev/null
    ok "${ns}: $(wc -w <<<"${deps}") deployment(s) at 0"
  done
  exit 0
fi

step "Waiting for the pods of ${K8S_NAMESPACE}"
# At boot the old pods still show for a few seconds before being recreated
${BOOT} && sleep 30
if kc -n "${K8S_NAMESPACE}" wait --for=condition=Ready pod --all --timeout="${wait_s}s" >/dev/null 2>&1; then
  ok "all pods ready"
else
  warn "not all pods became ready within ${wait_s}s; going on anyway"
fi

step "User plane (registration + ping to the UPF)"
if ensure_user_plane; then
  exit 0
fi
err "did not recover by itself — run ./test.sh -v and see docs/troubleshooting.md"
exit 1
