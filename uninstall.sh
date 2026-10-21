#!/usr/bin/env bash
# =============================================================================
#  uninstall.sh — remove o que o install.sh criou, em níveis:
#
#    sudo ./uninstall.sh            # remove releases Helm, PVCs e o namespace
#    sudo ./uninstall.sh --k3s      # + desinstala o k3s (k3s-uninstall.sh)
#    sudo ./uninstall.sh --purge    # + k3s + sysctl, módulos, NetworkManager,
#                                   #   regras UFW, helm instalado por nós,
#                                   #   charts clonados, helm/generated/ e o bloco do ~/.bashrc
#    -y   não pede confirmação
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
    *) die "opção desconhecida: $a" ;;
  esac
done
require_root "$@"
load_config
resolve_target_user

confirm() {
  ${YES} && return 0
  local r; read -r -p "    $1 [s/N] " r
  [[ "${r,,}" =~ ^(s|sim|y|yes)$ ]]
}

step "Plano"
info "remover releases '${UERANSIM_RELEASE}' e '${OPEN5GS_RELEASE}' e namespace '${K8S_NAMESPACE}' (inclui dados do MongoDB)"
if ${REMOVE_K3S}; then info "desinstalar o k3s (TODOS os workloads do cluster serão apagados) e a interface ${STABLE_IFACE}"; fi
if ${PURGE}; then info "remover ${SYSCTL_FILE}, ${MODULES_FILE}, ${NM_CONF_FILE}, regras UFW, ${INSTALL_DIR}, ${GENERATED_DIR}"; fi
confirm "Continuar?" || { info "cancelado"; exit 0; }

# 1) Workloads -------------------------------------------------------------------
step "Releases e namespace"
if k3s_ready; then
  find_helm
  for rel in "${UERANSIM_RELEASE}" "${OPEN5GS_RELEASE}"; do
    if [[ -n "${HELM_BIN}" ]] && hm -n "${K8S_NAMESPACE}" status "${rel}" &>/dev/null; then
      hm -n "${K8S_NAMESPACE}" uninstall "${rel}" --wait --timeout 5m >/dev/null && ok "release ${rel} removido"
    else
      info "release ${rel} não existe"
    fi
  done
  if kc get ns "${K8S_NAMESPACE}" &>/dev/null; then
    kc -n "${K8S_NAMESPACE}" delete pvc --all --wait=true >/dev/null 2>&1 || true
    kc delete ns "${K8S_NAMESPACE}" --wait=true --timeout=180s >/dev/null && ok "namespace ${K8S_NAMESPACE} removido"
  fi
  if [[ -n "${HELM_BIN}" ]] && hm -n kube-system status multus &>/dev/null; then
    hm -n kube-system uninstall multus --wait --timeout 5m >/dev/null && ok "release multus removido"
    kc delete crd network-attachment-definitions.k8s.cni.cncf.io --ignore-not-found >/dev/null
  fi
else
  info "k3s não está no ar; pulando remoção de releases"
fi

# 2) k3s --------------------------------------------------------------------------
if ${REMOVE_K3S}; then
  step "kubeconfig do usuário ${TARGET_USER}"
  remove_user_kubeconfig   # antes do k3s sumir (usa 'k3s kubectl')
  ok "contexto ${KCTX} removido de ${TARGET_HOME}/.kube/config (demais contextos preservados)"
  step "k3s"
  if [[ -x /usr/local/bin/k3s-uninstall.sh ]]; then
    /usr/local/bin/k3s-uninstall.sh >/dev/null 2>&1 || warn "k3s-uninstall.sh retornou erro"
    ok "k3s desinstalado"
  else
    info "k3s não instalado"
  fi
  rm -f "${INSTALL_DIR}/state/k3s.sig"
  if [[ -f "${HEAL_UNIT_FILE}" ]]; then
    systemctl disable open5gs-k3s-heal.service >/dev/null 2>&1 || true
    rm -f "${HEAL_UNIT_FILE}"; rm -rf "${INSTALL_DIR}/heal"; systemctl daemon-reload
    ok "unit open5gs-k3s-heal removida"
  fi
  if [[ -f "${NETIF_UNIT_FILE}" ]]; then
    systemctl disable --now open5gs-k3s-netif.service >/dev/null 2>&1 || true
    rm -f "${NETIF_UNIT_FILE}" "${K3S_DROPIN_FILE}"
    rmdir "$(dirname "${K3S_DROPIN_FILE}")" 2>/dev/null || true
    systemctl daemon-reload
    ip link del "${STABLE_IFACE}" 2>/dev/null || true
    ok "interface estável ${STABLE_IFACE} e unit open5gs-k3s-netif removidas"
  fi
fi

# 3) Ajustes de sistema ---------------------------------------------------------------
if ${PURGE}; then
  step "Ajustes do sistema"
  if [[ -f "${SYSCTL_FILE}" ]]; then rm -f "${SYSCTL_FILE}"; sysctl -q --system >/dev/null || true; ok "sysctl removido (valores voltam no próximo boot)"; fi
  if [[ -f "${MODULES_FILE}" ]]; then rm -f "${MODULES_FILE}"; ok "${MODULES_FILE} removido (módulos continuam carregados até o reboot)"; fi
  if [[ -f "${NM_CONF_FILE}" ]]; then rm -f "${NM_CONF_FILE}"; systemctl reload NetworkManager 2>/dev/null || true; ok "config do NetworkManager removida"; fi
  if command -v ufw &>/dev/null; then
    # apaga, do fim para o início, as regras com comentário open5gs-k3s
    mapfile -t nums < <(ufw status numbered 2>/dev/null | grep 'open5gs-k3s' | sed -E 's/^\[ *([0-9]+)\].*/\1/' | sort -rn)
    for n in "${nums[@]}"; do ufw --force delete "$n" >/dev/null; done
    if (( ${#nums[@]} )); then ok "${#nums[@]} regra(s) UFW removida(s)"; fi
  fi
  if systemctl is-active --quiet firewalld 2>/dev/null; then
    firewall-cmd -q --permanent --zone=trusted --remove-source="${K3S_CLUSTER_CIDR}" --remove-source="${K3S_SERVICE_CIDR}" 2>/dev/null || true
    firewall-cmd -q --permanent --remove-port="${WEBUI_NODEPORT}/tcp" --remove-port=38412/sctp --remove-port=2152/udp 2>/dev/null || true
    firewall-cmd -q --reload && ok "regras do firewalld removidas"
  fi
  if [[ -L /usr/local/bin/helm && "$(readlink /usr/local/bin/helm)" == "${INSTALL_DIR}/bin/helm" ]]; then
    rm -f /usr/local/bin/helm; ok "link /usr/local/bin/helm removido"
  fi
  remove_user_bashrc && ok "bloco open5gs-k3s removido de ${TARGET_HOME}/.bashrc"
  rm -rf "${INSTALL_DIR}" "${GENERATED_DIR}"
  ok "${INSTALL_DIR} e ${GENERATED_DIR} removidos"
fi

step "Concluído"
