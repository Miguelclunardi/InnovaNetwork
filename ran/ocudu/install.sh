#!/usr/bin/env bash
# =============================================================================
#  ran/ocudu/install.sh — gNB OCUDU no Kubernetes (componente RAN do InnovaNetwork).
#
#  Roda no torre2 (servidor do k3s). Separado do install.sh dos cores e do painel.
#  DEPENDE DO SEU SETUP: veja ran/ocudu/ocudu.env e docs/ocudu-k8s.md.
#
#  Ordem, na primeira vez:
#    1. ./ran/ocudu/install.sh copiar          copia no-ran.sh + ocudu.env para o nó (~/innovanetwork-ran)
#    2. no nó: sudo ~/innovanetwork-ran/no-ran.sh imagem      (compila a imagem do gNB)
#    3. sudo ./ran/ocudu/install.sh preparar   libera o UFW do torre2 para o nó e manda ao nó um token
#                                              de entrada (válido 2 h; nunca aparece na tela)
#    4. no nó: sudo ~/innovanetwork-ran/no-ran.sh entrar      (k3s agente; importa a imagem)
#    5. ./ran/ocudu/install.sh                 cria o namespace e o Deployment (0 réplicas = parado)
#    6. ./ran/ocudu/gnb.sh iniciar [yml]       liga o gNB (o serviço nativo precisa estar parado)
#
#  Outras opções:  --dry-run (gera e valida no servidor; não aplica) · --remover (apaga o namespace)
# =============================================================================
set -Eeuo pipefail
OC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${OC_DIR}/../.." && pwd)"
# shellcheck source=../../scripts/lib/common.sh
source "${PROJECT_DIR}/scripts/lib/common.sh"
load_config
# shellcheck source=ocudu.env
source "${OC_DIR}/ocudu.env"
unset HELM_CACHE_HOME HELM_CONFIG_HOME HELM_DATA_HOME
KUBECTL="kubectl"
[[ $EUID -ne 0 ]] || KUBECTL="kubectl --kubeconfig ${KUBECONFIG_PATH:-/etc/rancher/k3s/k3s.yaml}"
k() { ${KUBECTL} "$@"; }
OWNER="${SUDO_USER:-$(id -un)}"
as_owner() { if [[ $EUID -eq 0 && -n "${SUDO_USER:-}" ]]; then sudo -u "${SUDO_USER}" "$@"; else "$@"; fi; }
NODE_DIR="innovanetwork-ran"           # no home do usuário do nó

copy_to_node() {  # $@ = arquivos locais
  step "Copiando para ${OCUDU_NODE_SSH}:~/${NODE_DIR}/"
  as_owner ssh -o BatchMode=yes "${OCUDU_NODE_SSH}" "mkdir -p ~/${NODE_DIR} && chmod 700 ~/${NODE_DIR}"
  as_owner scp -q -o BatchMode=yes "$@" "${OCUDU_NODE_SSH}:${NODE_DIR}/"
  as_owner ssh -o BatchMode=yes "${OCUDU_NODE_SSH}" "chmod 700 ~/${NODE_DIR}/no-ran.sh; chmod 600 ~/${NODE_DIR}/*.env"
  ok "$(printf '%s ' "${@##*/}")"
}

do_copy() {
  copy_to_node "${OC_DIR}/no-ran.sh" "${OC_DIR}/ocudu.env"
  info "no nó: sudo ~/${NODE_DIR}/no-ran.sh imagem   (depois: preparar + entrar)"
}

do_prepare() {
  [[ $EUID -eq 0 ]] || die "rode com sudo: sudo $0 preparar"
  [[ "${NODE_IP_MODE}" == "stable" ]] || die "este modo de entrada usa NODE_IP_MODE=stable (servidor em ${STABLE_IP})"
  if ufw status 2>/dev/null | grep -q "Status: active"; then
    step "UFW do torre2: liberando o nó ${OCUDU_NODE_IP}"
    ufw allow from "${OCUDU_NODE_IP}" comment 'InnovaNetwork k3s no RAN' >/dev/null
    ufw allow from 10.42.0.0/16 comment 'InnovaNetwork k3s pods' >/dev/null
    ufw allow from 10.43.0.0/16 comment 'InnovaNetwork k3s services' >/dev/null
    ok "regras 'InnovaNetwork k3s'"
  fi
  step "Token de entrada (2 h) para o nó"
  local tmp; tmp="$(mktemp -d)"; chmod 700 "${tmp}"
  local tok; tok="$(k3s token create --ttl 2h --description "InnovaNetwork no RAN ${OCUDU_NODE}")"
  [[ -n "${tok}" ]] || die "k3s token create não devolveu token"
  umask 077
  cat > "${tmp}/join.env" <<EOF
# Gerado por ran/ocudu/install.sh preparar ($(date -Is)). Apagado pelo no-ran.sh entrar.
K3S_URL="https://${STABLE_IP}:6443"
K3S_TOKEN="${tok}"
K3S_VERSION="${K3S_VERSION}"
STABLE_IP="${STABLE_IP}"
EOF
  chown -R "${OWNER}" "${tmp}"
  copy_to_node "${OC_DIR}/no-ran.sh" "${OC_DIR}/ocudu.env" "${tmp}/join.env"
  rm -rf "${tmp}"
  info "no nó: sudo ~/${NODE_DIR}/no-ran.sh entrar"
}

image_tag() {
  if [[ -n "${OCUDU_IMAGE_TAG}" ]]; then echo "${OCUDU_IMAGE_TAG}"; return; fi
  as_owner ssh -o BatchMode=yes "${OCUDU_NODE_SSH}" "git -C '${OCUDU_SRC_DIR}' rev-parse --short=7 HEAD"
}

render() {  # $1 = tag da imagem; $2 = .yml em uso; $3 = réplicas
  OCUDU_IMAGE_TAG="$1" OCUDU_GNB_CONFIG="$2" OCUDU_REPLICAS="$3" OCUDU_NAMESPACE="${OCUDU_NAMESPACE}" OCUDU_NODE="${OCUDU_NODE}" \
  OCUDU_CONFIG_DIR="${OCUDU_CONFIG_DIR}" OCUDU_LOG_DIR="${OCUDU_LOG_DIR}" OCUDU_IMAGE="${OCUDU_IMAGE}" \
  OCUDU_DEFAULT_CONFIG="${OCUDU_DEFAULT_CONFIG}" OCUDU_EXTRA_CONFIG="${OCUDU_EXTRA_CONFIG}" \
  OCUDU_CPUS="${OCUDU_CPUS}" python3 "${OC_DIR}/lib/render.py"
}

do_deploy() {
  local dry="$1" tag out
  tag="$(image_tag)"; [[ -n "${tag}" ]] || die "não consegui ler o commit do OCUDU no nó"
  out="${GENERATED_DIR}/ocudu"; mkdir -p "${out}"
  step "Manifestos (imagem ${OCUDU_IMAGE}:${tag})"
  # Se já existe, mantém réplicas e o .yml escolhido (não derruba um gNB ligado)
  local cur_rep cur_cfg
  cur_rep="$(k -n "${OCUDU_NAMESPACE}" get deploy ocudu-gnb -o jsonpath='{.spec.replicas}' 2>/dev/null || true)"
  cur_cfg="$(k -n "${OCUDU_NAMESPACE}" get deploy ocudu-gnb -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="GNB_CONFIG")].value}' 2>/dev/null || true)"
  render "${tag}" "${cur_cfg:-${OCUDU_DEFAULT_CONFIG}}" "${cur_rep:-0}" > "${out}/ocudu.yaml"
  ok "${out}/ocudu.yaml"
  if ${dry}; then
    # cliente: o namespace ainda pode não existir (o servidor recusaria o Deployment)
    k apply --dry-run=client -f "${out}/ocudu.yaml" | sed 's/^/    /'
    if k get namespace "${OCUDU_NAMESPACE}" >/dev/null 2>&1; then
      k apply --dry-run=server -f "${out}/ocudu.yaml" | sed 's/^/    /'
    fi
    return
  fi
  step "Nó ${OCUDU_NODE}"
  k get node "${OCUDU_NODE}" >/dev/null 2>&1 || die "o nó ${OCUDU_NODE} não está no cluster (passos 3 e 4)"
  k get node "${OCUDU_NODE}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' | grep -q True \
    || die "o nó ${OCUDU_NODE} não está Ready"
  k get node "${OCUDU_NODE}" -o jsonpath='{range .status.images[*]}{.names}{"\n"}{end}' \
    | grep -qF "${OCUDU_IMAGE}:${tag}" || warn "a imagem ${OCUDU_IMAGE}:${tag} não aparece no nó (no nó: no-ran.sh importar)"
  ok "Ready"
  step "Aplicando (réplicas atuais: ${cur_rep:-0}; 0 = gNB parado)"
  k apply -f "${out}/ocudu.yaml" | sed 's/^/    /'
  ok "gNB: ./ran/ocudu/gnb.sh iniciar [yml] | parar | estado | log"
}

case "${1:-}" in
  copiar)    do_copy ;;
  preparar)  do_prepare ;;
  --dry-run) do_deploy true ;;
  --remover) k delete namespace "${OCUDU_NAMESPACE}" --ignore-not-found ;;
  "")        do_deploy false ;;
  -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)         die "opção desconhecida: $1 (veja --help)" ;;
esac
