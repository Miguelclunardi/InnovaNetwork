#!/usr/bin/env bash
# =============================================================================
#  install.sh — instala k3s + Helm + Open5GS (5G SA) + UERANSIM num único nó
#  Ubuntu 24.04 (desktop ou server). Idempotente: pode ser executado várias
#  vezes; aplica apenas o que mudou no config.env.
#
#  Uso:
#    sudo ./install.sh                 # instalação completa
#    sudo ./install.sh --deploy-only   # só (re)gera values e faz helm upgrade
#    CONFIG=outro.env sudo -E ./install.sh
#
#  O log vai automaticamente para logs/install.log (não precisa de "| tee").
# =============================================================================
set -Eeuo pipefail
source "$(dirname "$(readlink -f "$0")")/scripts/lib/common.sh"
trap 'err "falhou na linha ${LINENO}: ${BASH_COMMAND}"' ERR

DEPLOY_ONLY=false
usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
for a in "$@"; do
  case "$a" in
    --deploy-only) DEPLOY_ONLY=true ;;
    -h|--help) usage ;;
    *) die "opção desconhecida: $a" ;;
  esac
done

# ----------------------------------------------------------------------------
#  1. Pacotes
# ----------------------------------------------------------------------------
step_packages() {
  step "Pacotes do sistema"
  local pkgs=(curl ca-certificates git iproute2 iptables kmod lksctp-tools tar gzip coreutils bash-completion) missing=()
  local p
  for p in "${pkgs[@]}"; do dpkg -s "$p" &>/dev/null || missing+=("$p"); done
  if (( ${#missing[@]} )); then
    info "instalando: ${missing[*]}"
    DEBIAN_FRONTEND=noninteractive apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${missing[@]}" >/dev/null
  fi
  ok "dependências presentes"
}

# ----------------------------------------------------------------------------
#  2. Módulos do kernel (SCTP para N2/NGAP, TUN para UPF/UE, bridge p/ CNI)
# ----------------------------------------------------------------------------
step_modules() {
  step "Módulos do kernel"
  if ! modinfo sctp &>/dev/null; then
    if is_true "${AUTO_INSTALL_MODULES_EXTRA}"; then
      info "módulo sctp ausente no kernel $(uname -r); instalando linux-modules-extra"
      DEBIAN_FRONTEND=noninteractive apt-get update -qq
      DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "linux-modules-extra-$(uname -r)" >/dev/null \
        || die "não foi possível instalar linux-modules-extra-$(uname -r). Use um kernel 'generic'."
    else
      die "módulo sctp indisponível e AUTO_INSTALL_MODULES_EXTRA=false"
    fi
  fi
  local mods=(sctp tun br_netfilter overlay) m
  printf '%s\n' "# Gerado por open5GK3S/install.sh" "${mods[@]}" >"${MODULES_FILE}"
  for m in "${mods[@]}"; do modprobe "$m" || die "falha ao carregar módulo $m"; done
  ok "carregados e persistidos em ${MODULES_FILE}: ${mods[*]}"
  if command -v checksctp &>/dev/null; then
    checksctp &>/dev/null && ok "SCTP funcional (checksctp)" || warn "checksctp falhou"
  fi
}

# ----------------------------------------------------------------------------
#  3. sysctl
# ----------------------------------------------------------------------------
step_sysctl() {
  step "Parâmetros sysctl"
  cat >"${SYSCTL_FILE}" <<'EOF'
# Gerado por open5GK3S/install.sh
# Encaminhamento IPv4 (pods, NAT do UPF/N6)
net.ipv4.ip_forward = 1
# Tráfego de bridge passando pelo iptables (kube-proxy / flannel)
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
# Muitos pods (um por NF) => mais inotify
fs.inotify.max_user_instances = 1024
fs.inotify.max_user_watches = 524288
# Buffers maiores para GTP-U/SCTP
net.core.rmem_max = 8388608
net.core.wmem_max = 8388608
EOF
  sysctl -q -p "${SYSCTL_FILE}" >/dev/null
  ok "aplicado ${SYSCTL_FILE}"
}

# ----------------------------------------------------------------------------
#  4. Ajustes específicos de ambiente (desktop x server)
# ----------------------------------------------------------------------------
step_host_profile() {
  step "Ajustes do perfil '${DETECTED_PROFILE}'"
  if ${HAS_NM}; then
    # Sem isso o NetworkManager tenta gerenciar cni0/flannel/veth e derruba a rede dos pods
    local content
    local devs="interface-name:cni0;interface-name:flannel*;interface-name:veth*"
    if [[ "${NODE_IP_MODE}" == stable ]]; then devs+=";interface-name:${STABLE_IFACE}"; fi
    content=$'# Gerado por open5GK3S/install.sh\n[keyfile]\nunmanaged-devices='"${devs}"$'\n'
    if [[ ! -f "${NM_CONF_FILE}" ]] || [[ "$(cat "${NM_CONF_FILE}")"$'\n' != "${content}" ]]; then
      mkdir -p "$(dirname "${NM_CONF_FILE}")"
      printf '%s' "${content}" >"${NM_CONF_FILE}"
      systemctl reload NetworkManager || true
    fi
    ok "NetworkManager ignora cni0/flannel*/veth*$([[ "${NODE_IP_MODE}" == stable ]] && echo "/${STABLE_IFACE}" || true)"
  else
    info "NetworkManager inativo (típico de server/netplan+networkd) — nada a fazer"
  fi

  if ${UFW_ACTIVE}; then
    if is_true "${CONFIGURE_UFW}"; then
      ufw allow from "${K3S_CLUSTER_CIDR}" comment 'open5gs-k3s pods' >/dev/null
      ufw allow from "${K3S_SERVICE_CIDR}" comment 'open5gs-k3s services' >/dev/null
      ufw route allow from "${K3S_CLUSTER_CIDR}" comment 'open5gs-k3s pods' >/dev/null
      ufw route allow to "${K3S_CLUSTER_CIDR}" comment 'open5gs-k3s pods' >/dev/null
      if is_true "${WEBUI_ENABLED}"; then ufw allow "${WEBUI_NODEPORT}/tcp" comment 'open5gs-k3s webui' >/dev/null; fi
      if is_true "${EXPOSE_RAN}"; then ufw allow 2152/udp comment 'open5gs-k3s N3' >/dev/null; fi
      ok "regras UFW aplicadas (CIDRs do cluster, WebUI$(is_true "${EXPOSE_RAN}" && echo ', N3' || true))"
      if is_true "${EXPOSE_RAN}"; then warn "UFW não filtra SCTP por porta: garanta que SCTP/38412 não esteja bloqueado"; fi
    else
      warn "UFW ativo e CONFIGURE_UFW=false: pode bloquear tráfego dos pods"
    fi
  fi

  if ${HAS_FIREWALLD}; then
    if is_true "${CONFIGURE_FIREWALLD}"; then
      # Recomendação do k3s: redes de pods e services na zona trusted
      local fw=(--zone=trusted --add-source="${K3S_CLUSTER_CIDR}" --add-source="${K3S_SERVICE_CIDR}")
      firewall-cmd -q --permanent "${fw[@]}" 2>/dev/null || true
      if is_true "${WEBUI_ENABLED}"; then firewall-cmd -q --permanent --add-port="${WEBUI_NODEPORT}/tcp" 2>/dev/null || true; fi
      if is_true "${EXPOSE_RAN}"; then
        firewall-cmd -q --permanent --add-port=38412/sctp --add-port=2152/udp 2>/dev/null || true
      fi
      firewall-cmd -q --reload
      firewall-cmd -q --zone=trusted --query-source="${K3S_CLUSTER_CIDR}" \
        || die "firewalld: não foi possível adicionar ${K3S_CLUSTER_CIDR} à zona trusted"
      ok "firewalld: ${K3S_CLUSTER_CIDR} e ${K3S_SERVICE_CIDR} na zona trusted$(is_true "${WEBUI_ENABLED}" && echo ", porta ${WEBUI_NODEPORT}/tcp" || true)"
    else
      warn "firewalld ativo e CONFIGURE_FIREWALLD=false: o tráfego direto entre pods (UE<->gNB, N3) será rejeitado"
    fi
  fi

  if ${HAS_DOCKER}; then
    warn "Docker ativo: ele define a política FORWARD=DROP do iptables. O k3s/flannel cria regras"
    warn "próprias para ${K3S_CLUSTER_CIDR}, mas se pods ficarem sem rede veja a seção 'Docker' do README."
  fi
  if ! ${HAS_AVX} && [[ -z "${MONGODB_IMAGE_REPOSITORY}" ]]; then
    warn "CPU sem AVX: a imagem padrão do MongoDB (8.x) NÃO roda. Defina MONGODB_IMAGE_* com uma versão 4.4."
  fi
  if (( MEM_MB < 3500 )); then warn "pouca RAM (${MEM_MB} MiB). Recomendado >= 4 GiB."; fi
  if (( CPUS < 2 )); then warn "apenas ${CPUS} vCPU. Recomendado >= 2."; fi
  if (( $(swapon --show --noheadings 2>/dev/null | wc -l) > 0 )); then info "swap ativo (k3s tolera; nada a fazer)"; fi
}

# ----------------------------------------------------------------------------
#  4b. Interface estável do nó (NODE_IP_MODE=stable)
#  O k3s guarda o node-ip no config; se o IP do host mudar (DHCP, Wi-Fi x cabo,
#  outra rede) o k3s não sobe. Uma interface dummy com IP fixo e privado, criada
#  a cada boot antes do k3s, torna o cluster independente da rede física.
#  A saída para a internet (N6) continua pela rota default, qualquer que seja.
# ----------------------------------------------------------------------------
step_stable_netif() {
  step "Interface estável do nó (NODE_IP_MODE=${NODE_IP_MODE})"
  if [[ "${NODE_IP_MODE}" != stable ]]; then
    if [[ -f "${NETIF_UNIT_FILE}" ]]; then
      systemctl disable --now open5gs-k3s-netif.service >/dev/null 2>&1 || true
      rm -f "${NETIF_UNIT_FILE}" "${K3S_DROPIN_FILE}"
      systemctl daemon-reload
      ok "interface estável removida; k3s usa ${K3S_NODE_IFACE} (${K3S_NODE_IP})"
    else
      info "k3s usa a interface física ${K3S_NODE_IFACE} (${K3S_NODE_IP}) — sensível a troca de IP"
    fi
    return 0
  fi
  local unit dropin changed=false
  unit=$(cat <<EOU
# Gerado por open5GK3S/install.sh
[Unit]
Description=open5GK3S: interface estavel do no k3s (${STABLE_IFACE} ${STABLE_IP}), independente de DHCP
Before=k3s.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'ip link show ${STABLE_IFACE} >/dev/null 2>&1 || ip link add ${STABLE_IFACE} type dummy; ip addr replace ${STABLE_IP}/32 dev ${STABLE_IFACE}; ip link set ${STABLE_IFACE} up'

[Install]
WantedBy=multi-user.target
EOU
)
  dropin=$'# Gerado por open5GK3S/install.sh
[Unit]
Requires=open5gs-k3s-netif.service
After=open5gs-k3s-netif.service'
  if [[ "$(cat "${NETIF_UNIT_FILE}" 2>/dev/null)" != "${unit}" ]]; then
    printf '%s
' "${unit}" >"${NETIF_UNIT_FILE}"; changed=true
  fi
  if [[ "$(cat "${K3S_DROPIN_FILE}" 2>/dev/null)" != "${dropin}" ]]; then
    mkdir -p "$(dirname "${K3S_DROPIN_FILE}")"
    printf '%s
' "${dropin}" >"${K3S_DROPIN_FILE}"; changed=true
  fi
  if ${changed}; then systemctl daemon-reload; fi
  systemctl enable open5gs-k3s-netif.service >/dev/null 2>&1
  # 'restart' reaplica IP/nome se mudaram no config
  if ${changed}; then systemctl restart open5gs-k3s-netif.service; else systemctl start open5gs-k3s-netif.service; fi
  ip -4 -o addr show dev "${STABLE_IFACE}" 2>/dev/null | grep -q " ${STABLE_IP}/" \
    || die "não foi possível criar ${STABLE_IFACE} com ${STABLE_IP}"
  ok "${STABLE_IFACE} = ${STABLE_IP} (recriada a cada boot antes do k3s)"
  if is_true "${EXPOSE_RAN}"; then
    warn "EXPOSE_RAN=true: o gNB externo usa o IP físico ${NODE_IP}; se ele mudar, rode 'sudo ./install.sh --deploy-only'"
  fi
}

# ----------------------------------------------------------------------------
#  5. k3s
# ----------------------------------------------------------------------------
step_k3s() {
  step "k3s ${K3S_VERSION}"
  local cfg restart=false
  cfg=$(
    echo "# Gerado por open5GK3S/install.sh a partir de config.env"
    echo "write-kubeconfig-mode: \"0600\"   # só root; o usuário recebe ~/.kube/open5gs-k3s.yaml"
    echo "node-ip: \"${K3S_NODE_IP}\"   # NODE_IP_MODE=${NODE_IP_MODE}"
    echo "flannel-iface: \"${K3S_NODE_IFACE}\""
    echo "cluster-cidr: \"${K3S_CLUSTER_CIDR}\""
    echo "service-cidr: \"${K3S_SERVICE_CIDR}\""
    echo "disable:"
    echo "  - traefik"
    echo "# ~15 imagens baixadas ao mesmo tempo: o limite padrão do kubelet (5 QPS) gera 'pull QPS exceeded'"
    echo "kubelet-arg:"
    echo "  - \"registry-qps=20\""
    echo "  - \"registry-burst=40\""
  )
  mkdir -p "$(dirname "${K3S_CONFIG_FILE}")"
  if [[ ! -f "${K3S_CONFIG_FILE}" ]] || [[ "$(cat "${K3S_CONFIG_FILE}")" != "${cfg}" ]]; then
    if [[ -f "${K3S_CONFIG_FILE}" ]] && grep -q "cluster-cidr" "${K3S_CONFIG_FILE}" \
       && ! grep -q "\"${K3S_CLUSTER_CIDR}\"" "${K3S_CONFIG_FILE}"; then
      warn "K3S_CLUSTER_CIDR mudou num cluster existente: isso exige './uninstall.sh --k3s' antes."
    fi
    printf '%s\n' "${cfg}" >"${K3S_CONFIG_FILE}"
    restart=true
  fi

  local installed="" sig_file="${INSTALL_DIR}/state/k3s.sig" sig
  sig="${K3S_VERSION} ${K3S_EXTRA_ARGS[*]}"
  if command -v k3s &>/dev/null; then installed=$(k3s --version 2>/dev/null | awk 'NR==1{print $3}'); fi
  if [[ "${installed}" != "${K3S_VERSION}" ]] || [[ "$(cat "${sig_file}" 2>/dev/null)" != "${sig}" ]]; then
    info "instalando k3s ${K3S_VERSION} (atual: ${installed:-nenhum})"
    curl -sfL https://get.k3s.io -o "${INSTALL_DIR}/state/get-k3s.sh"
    INSTALL_K3S_VERSION="${K3S_VERSION}" INSTALL_K3S_EXEC="server ${K3S_EXTRA_ARGS[*]}" \
      sh "${INSTALL_DIR}/state/get-k3s.sh" >/dev/null
    echo "${sig}" >"${sig_file}"
    restart=false
  elif ${restart}; then
    info "config do k3s mudou; reiniciando"
    systemctl restart k3s
  fi
  systemctl enable --now k3s >/dev/null 2>&1 || true

  info "aguardando API do Kubernetes..."
  local t=0
  until k3s_ready; do
    (( t += 3 )); (( t < 300 )) || die "API do k3s não respondeu em 300s (journalctl -u k3s)"
    sleep 3
  done
  # O k3s aplica os manifests do sistema de forma assíncrona: esperar existirem antes do rollout
  local d
  for d in coredns local-path-provisioner; do
    t=0
    until kc -n kube-system get "deploy/${d}" &>/dev/null; do
      (( t += 3 )); (( t < 300 )) || die "deploy/${d} não foi criado pelo k3s em 300s"
      sleep 3
    done
  done
  kc wait --for=condition=Ready node --all --timeout=300s >/dev/null
  kc -n kube-system rollout status deploy/coredns --timeout=300s >/dev/null
  kc -n kube-system rollout status deploy/local-path-provisioner --timeout=300s >/dev/null
  ok "k3s $(k3s --version | awk 'NR==1{print $3}') pronto; nó $(kc get nodes -o jsonpath='{.items[0].metadata.name}') Ready"
  if [[ -x /usr/local/bin/kubectl && ! -L /usr/local/bin/kubectl ]]; then
    info "kubectl próprio já existe em /usr/local/bin (não foi substituído); use 'sudo k3s kubectl' ou KUBECONFIG=${KUBECONFIG_PATH}"
  fi
}

# ----------------------------------------------------------------------------
#  6. Helm
# ----------------------------------------------------------------------------
step_helm() {
  step "Helm"
  find_helm
  local cur=""
  [[ -n "${HELM_BIN}" ]] && cur=$("${HELM_BIN}" version --template '{{.Version}}' 2>/dev/null || true)
  # Instala o helm fixado se: não há helm; o nosso está em outra versão; ou o do
  # sistema não é v3 (Helm 4 não aceita post-renderer como executável)
  if [[ -z "${HELM_BIN}" ]] || \
     [[ "${HELM_BIN}" == "${INSTALL_DIR}/bin/helm" && "${cur}" != "${HELM_VERSION}" ]] || \
     [[ "${cur}" != v3.* ]]; then
    info "instalando helm ${HELM_VERSION} em ${INSTALL_DIR}/bin (link em /usr/local/bin/helm)"
    local tmp arch; tmp=$(mktemp -d)
    case "$(uname -m)" in
      x86_64) arch=amd64 ;; aarch64|arm64) arch=arm64 ;;
      *) die "arquitetura $(uname -m) não suportada pelo download do helm" ;;
    esac
    curl -sfL "https://get.helm.sh/helm-${HELM_VERSION}-linux-${arch}.tar.gz" -o "${tmp}/helm.tgz"
    curl -sfL "https://get.helm.sh/helm-${HELM_VERSION}-linux-${arch}.tar.gz.sha256sum" -o "${tmp}/helm.sha"
    (cd "${tmp}" && echo "$(awk '{print $1}' helm.sha)  helm.tgz" | sha256sum -c --quiet) || die "checksum do helm inválido"
    tar xzf "${tmp}/helm.tgz" -C "${tmp}"
    install -D -m 0755 "${tmp}/linux-${arch}/helm" "${INSTALL_DIR}/bin/helm"
    rm -rf "${tmp}"
    [[ -e /usr/local/bin/helm ]] || ln -s "${INSTALL_DIR}/bin/helm" /usr/local/bin/helm
    HELM_BIN="${INSTALL_DIR}/bin/helm"
  fi
  ok "helm $("${HELM_BIN}" version --template '{{.Version}}') (${HELM_BIN})"
}

# ----------------------------------------------------------------------------
#  7. Charts da Gradiant (git, ref fixa) + dependências
# ----------------------------------------------------------------------------
step_charts() {
  step "Charts Gradiant @ ${GRADIANT_CHARTS_REF:0:12}"
  if [[ ! -d "${CHARTS_DIR}/.git" ]]; then
    git clone -q --filter=blob:none "${GRADIANT_CHARTS_REPO}" "${CHARTS_DIR}"
  fi
  if ! git -C "${CHARTS_DIR}" cat-file -e "${GRADIANT_CHARTS_REF}^{commit}" 2>/dev/null; then
    git -C "${CHARTS_DIR}" fetch -q origin "${GRADIANT_CHARTS_REF}" || git -C "${CHARTS_DIR}" fetch -q --tags origin
  fi
  local head; head=$(git -C "${CHARTS_DIR}" rev-parse HEAD)
  if [[ "${head}" != "$(git -C "${CHARTS_DIR}" rev-parse "${GRADIANT_CHARTS_REF}^{commit}")" ]]; then
    git -C "${CHARTS_DIR}" checkout -q --force "${GRADIANT_CHARTS_REF}"
    rm -f "${CHARTS_DIR}"/charts/*/.deps-ok
  fi
  "${HELM_BIN}" repo add bitnami https://charts.bitnami.com/bitnami --force-update >/dev/null
  local c
  for c in open5gs ueransim-gnb; do
    if [[ ! -f "${CHARTS_DIR}/charts/${c}/.deps-ok" ]]; then
      info "helm dependency build ${c}"
      "${HELM_BIN}" dependency build "${CHARTS_DIR}/charts/${c}" >/dev/null
      touch "${CHARTS_DIR}/charts/${c}/.deps-ok"
    fi
  done
  ok "open5gs $(awk '/^version:/{print $2}' "${CHARTS_DIR}/charts/open5gs/Chart.yaml") (app $(awk -F'"' '/^appVersion:/{print $2}' "${CHARTS_DIR}/charts/open5gs/Chart.yaml")), ueransim-gnb $(awk '/^version:/{print $2}' "${CHARTS_DIR}/charts/ueransim-gnb/Chart.yaml")"
}

# ----------------------------------------------------------------------------
#  8. Deploy
# ----------------------------------------------------------------------------
step_deploy_core() {
  step "Open5GS (release ${OPEN5GS_RELEASE}, namespace ${K8S_NAMESPACE})"
  render_open5gs_values
  info "values gerados: ${OPEN5GS_VALUES} (hash ${OPEN5GS_HASH})"
  info "helm upgrade --install (pode levar vários minutos na 1ª vez: download de imagens)"
  hm upgrade --install "${OPEN5GS_RELEASE}" "${CHARTS_DIR}/charts/open5gs" \
    --namespace "${K8S_NAMESPACE}" --create-namespace \
    -f "${CHARTS_DIR}/charts/open5gs/values-5g.yaml" \
    -f "${OPEN5GS_VALUES}" \
    --wait --timeout "${HELM_TIMEOUT}" >/dev/null \
    || { kc -n "${K8S_NAMESPACE}" get pods; die "deploy do Open5GS falhou (veja os pods acima)"; }
  ok "Open5GS implantado"
}

step_subscribers() {
  step "Assinantes (MongoDB)"
  local dep; dep=$(populate_deploy)
  kc -n "${K8S_NAMESPACE}" rollout status "${dep}" --timeout=300s >/dev/null
  sync_subscribers
}

step_deploy_ueransim() {
  if ! is_true "${DEPLOY_UERANSIM}"; then
    step "UERANSIM desabilitado (DEPLOY_UERANSIM=false)"
    if hm -n "${K8S_NAMESPACE}" status "${UERANSIM_RELEASE}" &>/dev/null; then
      hm -n "${K8S_NAMESPACE}" uninstall "${UERANSIM_RELEASE}" >/dev/null
      ok "release ${UERANSIM_RELEASE} removido"
    fi
    return 0
  fi
  step "UERANSIM gNB + ${UE_COUNT} UE(s) (release ${UERANSIM_RELEASE})"
  render_ueransim_values
  info "values gerados: ${UERANSIM_VALUES} (hash ${UERANSIM_HASH})"
  hm upgrade --install "${UERANSIM_RELEASE}" "${CHARTS_DIR}/charts/ueransim-gnb" \
    --namespace "${K8S_NAMESPACE}" \
    -f "${UERANSIM_VALUES}" \
    --post-renderer "${PROJECT_DIR}/helm/postrender/drop-gnb-hpa.sh" \
    --wait --timeout "${HELM_TIMEOUT}" >/dev/null \
    || { kc -n "${K8S_NAMESPACE}" get pods; die "deploy do UERANSIM falhou"; }
  ok "UERANSIM implantado"
  ensure_user_plane || warn "plano de usuário não ficou OK — rode ./test.sh -v"
}

# ----------------------------------------------------------------------------
#  8b. Recuperação automática no boot (AUTO_HEAL)
#  Depois de um reboot os pods voltam em ordem qualquer e o plano de usuário
#  pode ficar sem sincronia (UPF/SMF/UE). A unit roda scripts/heal.sh a cada boot.
#  Ela roda como root, então executa uma CÓPIA em ${INSTALL_DIR} (dono root),
#  nunca os arquivos editáveis do projeto do usuário.
# ----------------------------------------------------------------------------
step_boot_heal() {
  step "Recuperação automática no boot (AUTO_HEAL=${AUTO_HEAL})"
  if ! is_true "${AUTO_HEAL}"; then
    if [[ -f "${HEAL_UNIT_FILE}" ]]; then
      systemctl disable open5gs-k3s-heal.service >/dev/null 2>&1 || true
      rm -f "${HEAL_UNIT_FILE}"; systemctl daemon-reload
      ok "unit open5gs-k3s-heal removida"
    else
      info "desligada; depois de um reboot rode ./scripts/heal.sh se o ./test.sh falhar"
    fi
    return 0
  fi
  local dst="${INSTALL_DIR}/heal" unit
  install -d -m 0755 -o root -g root "${dst}" "${dst}/scripts" "${dst}/scripts/lib"
  install -m 0755 -o root -g root "${PROJECT_DIR}/scripts/heal.sh" "${dst}/scripts/heal.sh"
  install -m 0644 -o root -g root "${PROJECT_DIR}/scripts/lib/common.sh" "${dst}/scripts/lib/common.sh"
  install -m 0600 -o root -g root "${CONFIG}" "${dst}/config.env"
  unit=$(cat <<EOU
# Gerado por open5GK3S/install.sh
[Unit]
Description=open5GK3S: verifica e recupera o plano de usuario apos o boot
After=k3s.service
Wants=k3s.service

[Service]
# exec (não oneshot): não atrasa o boot enquanto espera os pods
Type=exec
Environment=CONFIG=${dst}/config.env HOME=/root
ExecStart=${dst}/scripts/heal.sh --boot

[Install]
WantedBy=multi-user.target
EOU
)
  if [[ "$(cat "${HEAL_UNIT_FILE}" 2>/dev/null)" != "${unit}" ]]; then
    printf '%s\n' "${unit}" >"${HEAL_UNIT_FILE}"; systemctl daemon-reload
  fi
  systemctl enable open5gs-k3s-heal.service >/dev/null 2>&1
  ok "unit open5gs-k3s-heal ativa no boot (cópia em ${dst}; log: journalctl -u open5gs-k3s-heal)"
}

# ----------------------------------------------------------------------------
#  9. kubeconfig para o usuário que chamou o sudo (sem sobrescrever o dele)
# ----------------------------------------------------------------------------
step_user_kubeconfig() {
  step "kubeconfig e atalhos do usuário '${TARGET_USER}'"
  KUBECONFIG_CHANGED=false; BASHRC_CHANGED=false; KCTX_NOT_CURRENT=false
  setup_user_kubeconfig "${K3S_KUBECONFIG}"
  if ${KUBECONFIG_CHANGED}; then
    ok "${TARGET_HOME}/.kube/config atualizado (contexto '${KCTX}', dono ${TARGET_USER}, 0600)"
  else
    ok "${TARGET_HOME}/.kube/config já estava atualizado"
  fi
  if ${KCTX_NOT_CURRENT}; then
    warn "seu contexto atual foi mantido; para usar este cluster: kubectl config use-context ${KCTX}"
  fi
  if is_true "${SHELL_EXTRAS}"; then
    setup_user_bashrc
    if ${BASHRC_CHANGED}; then ok "alias 'k' e autocomplete do kubectl em ${TARGET_HOME}/.bashrc (abra um novo terminal)"; fi
  fi
  # teste real como o usuário (sem sudo, sem KUBECONFIG)
  if su - "${TARGET_USER}" -s /bin/bash -c 'env -u KUBECONFIG kubectl get nodes' &>/dev/null; then
    ok "'kubectl get nodes' funciona como ${TARGET_USER} sem sudo"
  else
    warn "'kubectl get nodes' falhou como ${TARGET_USER} — veja docs/troubleshooting.md"
  fi
}

final_summary() {
  step "Pronto"
  kc -n "${K8S_NAMESPACE}" get pods -o wide
  echo
  info "Teste:            ./test.sh"
  if is_true "${WEBUI_ENABLED}"; then
    info "WebUI:            http://${NODE_IP:-localhost}:${WEBUI_NODEPORT}  (admin / 1423; vale qualquer IP do host)"
  fi
  info "kubectl:          kubectl -n ${K8S_NAMESPACE} get pods   (como ${TARGET_USER}, sem sudo)"
  if is_true "${EXPOSE_RAN}"; then
    info "gNB externo:      AMF N2 = ${NODE_IP}:38412/SCTP   UPF N3 = ${NODE_IP}:2152/UDP"
  fi
  info "Assinantes:       sudo ./scripts/subscribers.sh list"
}

# Arquivos criados como root (logs, values) voltam para o usuário real
fix_ownership() {
  [[ -n "${TARGET_USER:-}" && "${TARGET_USER}" != "root" ]] || return 0
  chown -R "${TARGET_USER}:${TARGET_GROUP}" "${LOG_DIR}" "${GENERATED_DIR}" 2>/dev/null || true
}

main() {
  require_root "$@"
  # Log automático (não use "| tee": palavras extras viram arquivos)
  mkdir -p "${LOG_DIR}"
  exec > >(tee -a "${LOG_DIR}/install.log") 2>&1
  echo "===== $(date '+%F %T') install.sh $* ====="
  trap fix_ownership EXIT
  load_config
  step "Validação de config e detecção de ambiente (${CONFIG})"
  validate_config
  detect_env
  resolve_target_user
  print_env_summary
  mkdir -p "${INSTALL_DIR}/state"

  if ${DEPLOY_ONLY}; then
    k3s_ready || die "--deploy-only requer k3s já instalado e no ar"
    find_helm; [[ -n "${HELM_BIN}" ]] || die "helm não encontrado"
  else
    step_packages
    step_modules
    step_sysctl
    step_host_profile
    step_stable_netif
    step_k3s
    step_helm
  fi
  step_charts
  step_deploy_core
  step_subscribers
  step_deploy_ueransim
  step_boot_heal
  step_user_kubeconfig
  final_summary
}

main "$@"
