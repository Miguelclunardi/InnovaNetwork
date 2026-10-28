#!/usr/bin/env bash
# =============================================================================
#  ran/ocudu/no-ran.sh — roda NA MÁQUINA DO gNB (innovaserver), com sudo.
#
#  O torre2 copia este script, o ocudu.env e (só no "preparar") o join.env para
#  ~/innovanetwork-ran/ no nó:   ./ran/ocudu/install.sh copiar | preparar
#
#  Uso (no nó):
#    sudo ~/innovanetwork-ran/no-ran.sh imagem    compila a imagem do gNB do código em OCUDU_SRC_DIR
#                                                 (commit atual, via git archive) e, se o nó já está
#                                                 no cluster, importa no containerd do k3s
#    sudo ~/innovanetwork-ran/no-ran.sh importar  só importa no k3s uma imagem já compilada
#    sudo ~/innovanetwork-ran/no-ran.sh entrar    entra no k3s do torre2 como nó do RAN (precisa do
#                                                 join.env do "preparar"; o token é apagado no fim)
#    sudo ~/innovanetwork-ran/no-ran.sh sair      sai do cluster (remove o k3s agente)
#         ~/innovanetwork-ran/no-ran.sh estado    mostra o que está instalado (sem sudo)
#
#  Não mexe em: PTP, VF/DPDK, XDP, hugepages, CPUs isoladas, netplan, serviço ocudu-gnb@.
# =============================================================================
set -Eeuo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ocudu.env
source "${DIR}/ocudu.env"
[[ -f "${DIR}/join.env" ]] && source "${DIR}/join.env"

say()  { echo "==> $*"; }
info() { echo "    $*"; }
die()  { echo "[erro] $*" >&2; exit 1; }
need_root() { [[ $EUID -eq 0 ]] || die "rode com sudo: sudo $0 $1"; }
OWNER="${SUDO_USER:-$(stat -c %U "${OCUDU_SRC_DIR}")}"
ROUTE_UNIT="innovanetwork-k3s-route.service"

image_tag() {
  if [[ -n "${OCUDU_IMAGE_TAG}" ]]; then echo "${OCUDU_IMAGE_TAG}"; return; fi
  sudo -u "${OWNER}" git -C "${OCUDU_SRC_DIR}" rev-parse --short=7 HEAD
}

do_import() {
  local ref="${OCUDU_IMAGE}:$(image_tag)"
  command -v k3s >/dev/null || { info "k3s ainda não instalado: importe depois com '$0 importar'"; return 0; }
  say "importando ${ref} no containerd do k3s"
  docker image inspect "${ref}" >/dev/null 2>&1 || die "imagem ${ref} não existe: rode '$0 imagem'"
  docker save "${ref}" | k3s ctr -n k8s.io images import -
  k3s ctr -n k8s.io images ls -q | grep -F "${ref}" | sed 's/^/    /'
}

do_image() {
  need_root imagem
  command -v docker >/dev/null || die "docker não instalado"
  local tag ref ctx
  tag="$(image_tag)"; ref="${OCUDU_IMAGE}:${tag}"
  ctx="/var/tmp/innovanetwork-ocudu-src"
  say "imagem ${ref} (OCUDU em ${OCUDU_SRC_DIR}, commit $(sudo -u "${OWNER}" git -C "${OCUDU_SRC_DIR}" rev-parse --short=10 HEAD))"
  if sudo -u "${OWNER}" git -C "${OCUDU_SRC_DIR}" status --porcelain --untracked-files=no | grep -qv '^.. configs/\|^.. docker/'; then
    info "[aviso] há alterações locais no código fora de configs/ e docker/: a imagem usa o commit, sem elas"
  fi
  # Contexto limpo = só o commit (sem build/ nativo de ~2 GB, que quebraria o cmake da imagem)
  rm -rf "${ctx}"; mkdir -p "${ctx}"
  sudo -u "${OWNER}" git -C "${OCUDU_SRC_DIR}" archive HEAD | tar x -C "${ctx}"
  if [[ "${OCUDU_IMAGE_ROHC:-false}" != "true" ]]; then
    # Sem ROHC (igual ao gnb nativo): o Dockerfile copia /opt/rohc, então criamos a pasta vazia
    # em vez de baixar e compilar a biblioteca. Só a cópia temporária muda; o OCUDU_SRC_DIR não.
    info "sem ROHC (OCUDU_IMAGE_ROHC=false): build_rohc.sh substituído na cópia temporária"
    printf '#!/bin/sh\nmkdir -p /opt/rohc/lib /opt/rohc/include\necho "ROHC desligado (InnovaNetwork)"\n' \
      > "${ctx}/docker/scripts/build_rohc.sh"
    chmod 755 "${ctx}/docker/scripts/build_rohc.sh"
  fi
  say "compilando (demora ~20-40 min; usa ${OCUDU_BUILD_JOBS} jobs nas CPUs não isoladas)"
  docker build -f "${ctx}/docker/Dockerfile" --target runtime-dpdk \
    --build-arg COMPONENT=gnb \
    --build-arg OS="${OCUDU_IMAGE_OS}" --build-arg OS_VERSION="${OCUDU_IMAGE_OS_VERSION}" \
    --build-arg MARCH="${OCUDU_IMAGE_MARCH}" --build-arg NUM_JOBS="${OCUDU_BUILD_JOBS}" \
    --label "innovanetwork.ocudu.commit=$(sudo -u "${OWNER}" git -C "${OCUDU_SRC_DIR}" rev-parse HEAD)" \
    -t "${ref}" "${ctx}"
  rm -rf "${ctx}"
  docker run --rm --entrypoint /bin/bash "${ref}" -c 'command -v gnb taskset bash' | sed 's/^/    tem: /'
  do_import
}

do_join() {
  need_root entrar
  [[ -n "${K3S_URL:-}" && -n "${K3S_TOKEN:-}" && -n "${K3S_VERSION:-}" && -n "${STABLE_IP:-}" ]] \
    || die "falta o join.env: no torre2, rode 'sudo ./ran/ocudu/install.sh preparar'"
  ip -br addr show "${OCUDU_NODE_IFACE}" | grep -q "${OCUDU_NODE_IP}/" \
    || die "${OCUDU_NODE_IFACE} não tem ${OCUDU_NODE_IP}"

  # Lições de 2026-10-28 (docs/ocudu-k8s.md, "Problemas encontrados"):
  # 1) outro Kubernetes na máquina (ex.: MicroK8s) ocupa as portas do kubelet e o k3s não sobe
  local busy
  busy="$(ss -ltnpH '( sport = :10250 or sport = :10248 or sport = :6443 )' 2>/dev/null | grep -v '"k3s' || true)"
  if [[ -n "${busy}" ]]; then
    echo "${busy}" | sed 's/^/    /'
    die "há outro Kubernetes usando as portas do kubelet (10250/10248). MicroK8s? 'sudo microk8s stop' (não apaga nada; volta com 'sudo microk8s start')"
  fi
  # 2) restos de uma tentativa que falhou: certificados antigos fazem o servidor recusar o nó
  if [[ -d /var/lib/rancher/k3s/agent ]] && ! systemctl is-active -q k3s-agent; then
    say "limpando restos de uma tentativa anterior (/var/lib/rancher/k3s/agent)"
    systemctl stop k3s-agent 2>/dev/null || true
    rm -rf /var/lib/rancher/k3s/agent
  fi

  say "rota até o servidor do k3s (${STABLE_IP} via ${OCUDU_SERVER_VIA}) — unit ${ROUTE_UNIT}"
  cat > "/etc/systemd/system/${ROUTE_UNIT}" <<EOF
# InnovaNetwork: rota até o servidor do k3s (torre2) pela fibra. Gerado por ran/ocudu/no-ran.sh
[Unit]
Description=InnovaNetwork: rota ${STABLE_IP} via ${OCUDU_SERVER_VIA} (k3s)
After=network-online.target
Wants=network-online.target
Before=k3s-agent.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/ip route replace ${STABLE_IP}/32 via ${OCUDU_SERVER_VIA} dev ${OCUDU_NODE_IFACE}
ExecStop=-/usr/sbin/ip route del ${STABLE_IP}/32

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now "${ROUTE_UNIT}"
  ping -c1 -W2 "${STABLE_IP}" >/dev/null || die "sem resposta de ${STABLE_IP} pela fibra"
  info "ok: ${STABLE_IP} responde"

  if ufw status 2>/dev/null | grep -q "Status: active"; then
    say "UFW: liberando o cluster (só a partir do torre2 e das redes do k3s)"
    ufw allow from "${OCUDU_SERVER_VIA}" comment 'InnovaNetwork k3s' >/dev/null
    ufw allow from "${STABLE_IP}" comment 'InnovaNetwork k3s' >/dev/null
    ufw allow from 10.42.0.0/16 comment 'InnovaNetwork k3s pods' >/dev/null
    ufw allow from 10.43.0.0/16 comment 'InnovaNetwork k3s services' >/dev/null
  fi

  say "configuração do k3s agente"
  mkdir -p /etc/rancher/k3s
  cat > /etc/rancher/k3s/config.yaml <<EOF
# Gerado por InnovaNetwork ran/ocudu/no-ran.sh — nó do RAN
node-name: "${OCUDU_NODE}"
node-ip: "${OCUDU_NODE_IP}"
flannel-iface: "${OCUDU_NODE_IFACE}"
node-label:
  - "innovanetwork/role=ran"
node-taint:
  - "innovanetwork/ran=true:NoSchedule"
EOF
  say "instalando k3s ${K3S_VERSION} (agente) e entrando em ${K3S_URL}"
  curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="${K3S_VERSION}" K3S_URL="${K3S_URL}" \
    K3S_TOKEN="${K3S_TOKEN}" sh -s - agent
  rm -f "${DIR}/join.env"
  info "token apagado (${DIR}/join.env)"
  systemctl is-active k3s-agent | sed 's/^/    k3s-agent: /'
  if docker image inspect "${OCUDU_IMAGE}:$(image_tag)" >/dev/null 2>&1; then do_import; fi
  say "pronto. No torre2: kubectl get nodes"
}

do_leave() {
  need_root sair
  [[ -x /usr/local/bin/k3s-agent-uninstall.sh ]] && /usr/local/bin/k3s-agent-uninstall.sh
  systemctl disable --now "${ROUTE_UNIT}" 2>/dev/null || true
  rm -f "/etc/systemd/system/${ROUTE_UNIT}"; systemctl daemon-reload
  info "k3s agente removido. No torre2: kubectl delete node ${OCUDU_NODE}"
  info "(regras do UFW 'InnovaNetwork k3s' ficam; remova com 'sudo ufw status numbered' se quiser)"
}

do_state() {
  echo "k3s-agent:  $(systemctl is-active k3s-agent 2>/dev/null || true)"
  echo "rota:       $(ip route show "${STABLE_IP:-10.254.254.1}" 2>/dev/null || true)"
  echo "join.env:   $([[ -f "${DIR}/join.env" ]] && echo presente || echo ausente)"
  echo "OCUDU:      $(git -C "${OCUDU_SRC_DIR}" rev-parse --short=7 HEAD 2>/dev/null)"
  echo "gnb nativo: $(systemctl list-units --no-legend --state=active 'ocudu-gnb@*' | awk '{print $1}' | tr '\n' ' ')"
}

case "${1:-}" in
  imagem)   do_image ;;
  importar) need_root importar; do_import ;;
  entrar)   do_join ;;
  sair)     do_leave ;;
  estado)   do_state ;;
  *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
