#!/usr/bin/env bash
# =============================================================================
#  uninstall.sh — removes what install.sh created, in levels:
#
#    sudo ./uninstall.sh            # removes the Helm releases, PVCs and the namespace
#    sudo ./uninstall.sh --k3s      # + uninstalls k3s (k3s-uninstall.sh)
#    sudo ./uninstall.sh --purge    # + k3s + sysctl, modules, NetworkManager,
#                                   #   UFW rules, the helm we installed,
#                                   #   cloned charts, helm/generated/ and the ~/.bashrc block
#    -y   does not ask for confirmation
# =============================================================================
set -Eeuo pipefail
source "$(dirname "$(readlink -f "$0")")/scripts/lib/common.sh"

REMOVE_K3S=false; PURGE=false; YES=false
for a in "$@"; do
  case "$a" in
    --k3s) REMOVE_K3S=true ;;
    --purge) PURGE=true; REMOVE_K3S=true ;;
    -y|--yes) YES=true ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $a" ;;
  esac
done
require_root "$@"
load_config
resolve_target_user

confirm() {
  ${YES} && return 0
  local r; read -r -p "    $1 [y/N] " r
  [[ "${r,,}" =~ ^(s|sim|y|yes)$ ]]
}

step "Plan"
info "remove releases '${UERANSIM_RELEASE}' and '${OPEN5GS_RELEASE}' and namespace '${K8S_NAMESPACE}' (includes the MongoDB data)"
if ${REMOVE_K3S}; then info "uninstall k3s (ALL cluster workloads will be deleted) and the ${STABLE_IFACE} interface"; fi
if ${PURGE}; then info "remove ${SYSCTL_FILE}, ${MODULES_FILE}, ${NM_CONF_FILE}, UFW rules, ${INSTALL_DIR}, ${GENERATED_DIR}"; fi
confirm "Continue?" || { info "cancelled"; exit 0; }

# 1) Workloads -------------------------------------------------------------------
step "Releases and namespace"
if k3s_ready; then
  find_helm
  for rel in "${UERANSIM_RELEASE}" "${OPEN5GS_RELEASE}"; do
    if [[ -n "${HELM_BIN}" ]] && hm -n "${K8S_NAMESPACE}" status "${rel}" &>/dev/null; then
      hm -n "${K8S_NAMESPACE}" uninstall "${rel}" --wait --timeout 5m >/dev/null && ok "release ${rel} removed"
    else
      info "release ${rel} does not exist"
    fi
  done
  if kc get ns "${K8S_NAMESPACE}" &>/dev/null; then
    kc -n "${K8S_NAMESPACE}" delete pvc --all --wait=true >/dev/null 2>&1 || true
    kc delete ns "${K8S_NAMESPACE}" --wait=true --timeout=180s >/dev/null && ok "namespace ${K8S_NAMESPACE} removed"
  fi
  if [[ -n "${HELM_BIN}" ]] && hm -n kube-system status multus &>/dev/null; then
    hm -n kube-system uninstall multus --wait --timeout 5m >/dev/null && ok "release multus removed"
    kc delete crd network-attachment-definitions.k8s.cni.cncf.io --ignore-not-found >/dev/null
  fi
else
  info "k3s is not running; skipping the release removal"
fi
# Dashboard: the objects go with the namespace; the gNB log agent is a host unit
if [[ -f "${GNBLOG_UNIT_FILE}" ]]; then
  systemctl disable --now open5gs-k3s-gnb-log.service >/dev/null 2>&1 || true
  rm -f "${GNBLOG_UNIT_FILE}"; rm -rf "${INSTALL_DIR}/dashboard-agent"; systemctl daemon-reload
  ok "unit open5gs-k3s-gnb-log removed"
fi
if [[ -f "${GNBCTL_UNIT_FILE}" ]]; then
  systemctl disable --now open5gs-k3s-gnb-ctl.service >/dev/null 2>&1 || true
  rm -f "${GNBCTL_UNIT_FILE}"; systemctl daemon-reload
  ok "unit open5gs-k3s-gnb-ctl removed (the ocudu-gnb@ service stays on the gNB host; to remove it: setup-gnb-service.sh --remove)"
fi
if [[ -f "${RU_UNIT_FILE}" ]]; then
  systemctl disable --now open5gs-k3s-ru.service >/dev/null 2>&1 || true
  rm -f "${RU_UNIT_FILE}"; systemctl daemon-reload
  ok "unit open5gs-k3s-ru removed (RU passwords kept in ${INSTALL_DIR}/state/ru-credentials)"
fi
if [[ -f "${HOSTS_UNIT_FILE}" ]]; then
  systemctl disable --now open5gs-k3s-hosts.service >/dev/null 2>&1 || true
  rm -f "${HOSTS_UNIT_FILE}"; rm -rf "${INSTALL_DIR}/dashboard-agent"; systemctl daemon-reload
  ok "unit open5gs-k3s-hosts removed"
fi
rm -f "${INSTALL_DIR}/state/dashboard-ingest-token" "${INSTALL_DIR}/state/dashboard-admin-password"
rm -rf "${INSTALL_DIR}/state/config-backups"
# The dashboard metric history is NOT deleted (future comparisons). To delete it: sudo rm -rf /var/lib/open5gs-k3s/dashboard
if [[ -d /var/lib/open5gs-k3s/dashboard ]]; then echo "    dashboard history kept in /var/lib/open5gs-k3s/dashboard"; fi

# 2) k3s --------------------------------------------------------------------------
if ${REMOVE_K3S}; then
  step "kubeconfig of user ${TARGET_USER}"
  remove_user_kubeconfig   # before k3s goes away (uses 'k3s kubectl')
  ok "context ${KCTX} removed from ${TARGET_HOME}/.kube/config (other contexts kept)"
  step "k3s"
  if [[ -x /usr/local/bin/k3s-uninstall.sh ]]; then
    /usr/local/bin/k3s-uninstall.sh >/dev/null 2>&1 || warn "k3s-uninstall.sh returned an error"
    ok "k3s uninstalled"
  else
    info "k3s not installed"
  fi
  rm -f "${INSTALL_DIR}/state/k3s.sig"
  if [[ -f "${HEAL_UNIT_FILE}" ]]; then
    systemctl disable open5gs-k3s-heal.service >/dev/null 2>&1 || true
    rm -f "${HEAL_UNIT_FILE}"; rm -rf "${INSTALL_DIR}/heal"; systemctl daemon-reload
    ok "unit open5gs-k3s-heal removed"
  fi
  if [[ -f "${NETIF_UNIT_FILE}" ]]; then
    systemctl disable --now open5gs-k3s-netif.service >/dev/null 2>&1 || true
    rm -f "${NETIF_UNIT_FILE}" "${K3S_DROPIN_FILE}"
    rmdir "$(dirname "${K3S_DROPIN_FILE}")" 2>/dev/null || true
    systemctl daemon-reload
    ip link del "${STABLE_IFACE}" 2>/dev/null || true
    ok "stable interface ${STABLE_IFACE} and unit open5gs-k3s-netif removed"
  fi
fi

# 3) System settings ------------------------------------------------------------------
if ${PURGE}; then
  step "System settings"
  if [[ -f "${SYSCTL_FILE}" ]]; then rm -f "${SYSCTL_FILE}"; sysctl -q --system >/dev/null || true; ok "sysctl removed (values return to default on the next boot)"; fi
  if [[ -f "${MODULES_FILE}" ]]; then rm -f "${MODULES_FILE}"; ok "${MODULES_FILE} removed (modules stay loaded until the reboot)"; fi
  if [[ -f "${NM_CONF_FILE}" ]]; then rm -f "${NM_CONF_FILE}"; systemctl reload NetworkManager 2>/dev/null || true; ok "NetworkManager config removed"; fi
  if command -v ufw &>/dev/null; then
    # deletes, from the end to the start, the rules with the open5gs-k3s comment
    mapfile -t nums < <(ufw status numbered 2>/dev/null | grep 'open5gs-k3s' | sed -E 's/^\[ *([0-9]+)\].*/\1/' | sort -rn)
    for n in "${nums[@]}"; do ufw --force delete "$n" >/dev/null; done
    if (( ${#nums[@]} )); then ok "${#nums[@]} UFW rule(s) removed"; fi
  fi
  if systemctl is-active --quiet firewalld 2>/dev/null; then
    firewall-cmd -q --permanent --zone=trusted --remove-source="${K3S_CLUSTER_CIDR}" --remove-source="${K3S_SERVICE_CIDR}" 2>/dev/null || true
    firewall-cmd -q --permanent --remove-port="${WEBUI_NODEPORT}/tcp" --remove-port=38412/sctp --remove-port=2152/udp 2>/dev/null || true
    firewall-cmd -q --reload && ok "firewalld rules removed"
  fi
  if [[ -L /usr/local/bin/helm && "$(readlink /usr/local/bin/helm)" == "${INSTALL_DIR}/bin/helm" ]]; then
    rm -f /usr/local/bin/helm; ok "link /usr/local/bin/helm removed"
  fi
  remove_user_bashrc && ok "open5gs-k3s block removed from ${TARGET_HOME}/.bashrc"
  rm -rf "${INSTALL_DIR}" "${GENERATED_DIR}"
  ok "${INSTALL_DIR} and ${GENERATED_DIR} removed"
fi

step "Done"
