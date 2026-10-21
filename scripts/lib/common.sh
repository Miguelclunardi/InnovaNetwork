#!/usr/bin/env bash
# =============================================================================
#  scripts/lib/common.sh — funções compartilhadas por install.sh, test.sh,
#  uninstall.sh e scripts/subscribers.sh. Não executar diretamente.
# =============================================================================

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GENERATED_DIR="${PROJECT_DIR}/helm/generated"   # values Helm gerados do config.env
LOG_DIR="${PROJECT_DIR}/logs"
K3S_KUBECONFIG="/etc/rancher/k3s/k3s.yaml"     # 0600, só root
# HOME pode faltar (units do systemd): cai para o home do usuário atual
USER_KUBECONFIG="${HOME:-$(getent passwd "$(id -u)" | cut -d: -f6)}/.kube/open5gs-k3s.yaml" # cópia do install.sh para o usuário do sudo
# Usa o kubeconfig do k3s se legível (root); senão a cópia do usuário
# Root usa sempre a credencial do k3s, mesmo que ela ainda não exista (instalação do zero:
# o k3s cria o arquivo depois que a biblioteca já foi carregada).
if [[ ${EUID} -eq 0 || -r "${K3S_KUBECONFIG}" ]]; then KUBECONFIG_PATH="${K3S_KUBECONFIG}"; else KUBECONFIG_PATH="${USER_KUBECONFIG}"; fi
K3S_CONFIG_FILE="/etc/rancher/k3s/config.yaml"
SYSCTL_FILE="/etc/sysctl.d/90-open5gs-k3s.conf"
MODULES_FILE="/etc/modules-load.d/open5gs-k3s.conf"
NM_CONF_FILE="/etc/NetworkManager/conf.d/90-open5gs-k3s-unmanaged.conf"
NETIF_UNIT_FILE="/etc/systemd/system/open5gs-k3s-netif.service"   # interface estável do nó
K3S_DROPIN_FILE="/etc/systemd/system/k3s.service.d/10-open5gs-k3s-netif.conf"
HEAL_UNIT_FILE="/etc/systemd/system/open5gs-k3s-heal.service"
GNBLOG_UNIT_FILE="/etc/systemd/system/open5gs-k3s-gnb-log.service"     # log do gNB -> painel      # recuperação no boot
HASH_ANNOTATION="open5gs-k3s/config-hash"

# ----------------------------------------------------------------------------
#  Log
# ----------------------------------------------------------------------------
if [[ -t 1 ]]; then
  C_RED=$'\e[31m'; C_GRN=$'\e[32m'; C_YEL=$'\e[33m'; C_BLU=$'\e[34m'; C_B=$'\e[1m'; C_0=$'\e[0m'
else
  C_RED=""; C_GRN=""; C_YEL=""; C_BLU=""; C_B=""; C_0=""
fi
step() { echo; echo "${C_B}${C_BLU}==> $*${C_0}"; }
info() { echo "    $*"; }
ok()   { echo "    ${C_GRN}[ok]${C_0} $*"; }
warn() { echo "    ${C_YEL}[aviso]${C_0} $*" >&2; }
err()  { echo "    ${C_RED}[erro]${C_0} $*" >&2; }
die()  { err "$*"; exit 1; }

# Repete um comando que depende da internet (DNS/rede podem falhar por alguns segundos).
# Uso: retry <comando> [args...]   — até 5 tentativas, espera 5, 10, 15, 20 s entre elas.
retry() {
  local n=1 max=5
  until "$@"; do
    if (( n >= max )); then err "falhou ${max} vezes: $*"; return 1; fi
    warn "falhou (tentativa ${n}/${max}): $* — nova tentativa em $((n * 5))s"
    sleep $((n * 5)); n=$((n + 1))
  done
}

require_root() {
  if [[ ${EUID} -ne 0 ]]; then
    # Reexecuta com sudo preservando CONFIG, se definido
    exec sudo --preserve-env=CONFIG "$0" "$@"
  fi
}

# ----------------------------------------------------------------------------
#  Configuração
# ----------------------------------------------------------------------------
load_config() {
  CONFIG="${CONFIG:-${PROJECT_DIR}/config.env}"
  [[ -f "${CONFIG}" ]] || die "Arquivo de configuração não encontrado: ${CONFIG}"
  # shellcheck source=../config.env
  source "${CONFIG}"

  # Padrões para variáveis ausentes (config antigo/mínimo)
  : "${ENV_PROFILE:=auto}" "${NODE_IFACE:=}" "${NODE_IP:=}"
  : "${AUTO_HEAL:=true}" "${NODE_IP_MODE:=stable}" "${STABLE_IFACE:=k3s0}" "${STABLE_IP:=10.254.254.1}"
  : "${INSTALL_DIR:=/opt/open5gs-k3s}" "${KUBECONFIG_USER:=}" "${SHELL_EXTRAS:=true}"
  : "${AUTO_INSTALL_MODULES_EXTRA:=true}" "${CONFIGURE_UFW:=true}" "${CONFIGURE_FIREWALLD:=true}"
  : "${K3S_VERSION:?defina K3S_VERSION}" "${HELM_VERSION:?defina HELM_VERSION}"
  : "${GRADIANT_CHARTS_REPO:=https://github.com/Gradiant/5g-charts.git}"
  : "${GRADIANT_CHARTS_REF:?defina GRADIANT_CHARTS_REF}"
  : "${OPEN5GS_IMAGE_TAG:=}" "${UERANSIM_IMAGE_TAG:=}"
  : "${K8S_NAMESPACE:=open5gs}" "${OPEN5GS_RELEASE:=open5gs}" "${UERANSIM_RELEASE:=ueransim}"
  : "${K3S_CLUSTER_CIDR:=10.42.0.0/16}" "${K3S_SERVICE_CIDR:=10.43.0.0/16}"
  : "${HELM_TIMEOUT:=20m}"
  : "${MCC:?defina MCC}" "${MNC:?defina MNC}" "${TAC:?defina TAC}"
  : "${AMF_REGION_ID:=2}" "${AMF_SET_ID:=1}" "${NETWORK_NAME:=Open5GS}"
  : "${DNS_SERVERS:=8.8.8.8 8.8.4.4}" "${UE_MTU:=1400}"
  : "${WEBUI_ENABLED:=true}" "${WEBUI_NODEPORT:=30999}"
  : "${DASHBOARD_ENABLED:=false}" "${DASHBOARD_NODEPORT:=30998}" "${DASHBOARD_IMAGE:=python:3.12-slim}"
  : "${DASHBOARD_PASSWORD:=}" "${DASHBOARD_HISTORY_SECONDS:=900}" "${OPEN5GS_METRICS:=false}"
  : "${GNB_METRICS_URL:=}" "${GNB_NAME:=gNB}" "${GNB_LOG_SSH:=}" "${GNB_LOG_FILE:=/tmp/gnb.log}"
  GNB_LOG_DROP="${GNB_LOG_DROP-}"
  : "${MONGODB_PERSISTENCE:=true}" "${MONGODB_PERSISTENCE_SIZE:=2Gi}"
  : "${MONGODB_IMAGE_REGISTRY:=}" "${MONGODB_IMAGE_REPOSITORY:=}" "${MONGODB_IMAGE_TAG:=}"
  : "${DEPLOY_UERANSIM:=true}" "${EXPOSE_RAN:=false}"
  : "${RAN_LINK_ENABLED:=false}" "${RAN_LINK_IFACE:=}" "${RAN_LINK_CIDR:=}" "${RAN_LINK_MTU:=1500}"
  : "${AMF_N2_IP:=}" "${UPF_N3_IP:=}" "${GNB_SIM_IP:=}" "${MULTUS_CHART_VERSION:=v4.3.110}"
  : "${UE_COUNT:=1}" "${UE_MSIN_START:=0000000001}"
  : "${UE_KEY:?defina UE_KEY}" "${UE_OPC:?defina UE_OPC}"
  : "${TEST_PING_COUNT:=4}" "${TEST_INTERNET:=true}" "${TEST_PING_TARGET:=8.8.8.8}" "${TEST_TIMEOUT:=180}"
  declare -p SLICES      &>/dev/null || die "SLICES não definido no config"
  declare -p SUBSCRIBERS &>/dev/null || SUBSCRIBERS=()
  declare -p K3S_EXTRA_ARGS &>/dev/null || K3S_EXTRA_ARGS=()

  CHARTS_DIR="${INSTALL_DIR}/5g-charts"
  export HELM_CACHE_HOME="${INSTALL_DIR}/helm/cache"
  export HELM_CONFIG_HOME="${INSTALL_DIR}/helm/config"
  export HELM_DATA_HOME="${INSTALL_DIR}/helm/data"
}

is_true() { [[ "${1,,}" =~ ^(1|true|yes|sim|on)$ ]]; }

# ----------------------------------------------------------------------------
#  Rede: utilitários IPv4
# ----------------------------------------------------------------------------
ip2int() { local IFS=.; local -a o=($1); echo $(( (o[0]<<24) + (o[1]<<16) + (o[2]<<8) + o[3] )); }
int2ip() { local n=$1; echo "$(( (n>>24)&255 )).$(( (n>>16)&255 )).$(( (n>>8)&255 )).$(( n&255 ))"; }
valid_ipv4() {
  [[ "$1" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
  local i; for i in 1 2 3 4; do (( BASH_REMATCH[i] <= 255 )) || return 1; done
}
valid_cidr() {
  [[ "$1" == */* ]] || return 1
  valid_ipv4 "${1%/*}" && [[ "${1#*/}" =~ ^[0-9]+$ ]] && (( ${1#*/} >= 8 && ${1#*/} <= 30 ))
}
# cidr_info CIDR -> define CIDR_NET (int), CIDR_MASK (bits), CIDR_BCAST (int)
cidr_info() {
  local ip=${1%/*} bits=${1#*/}
  local mask=$(( bits == 0 ? 0 : (0xFFFFFFFF << (32 - bits)) & 0xFFFFFFFF ))
  CIDR_MASK=$bits
  CIDR_NET=$(( $(ip2int "$ip") & mask ))
  CIDR_BCAST=$(( CIDR_NET | (~mask & 0xFFFFFFFF) ))
}
cidr_overlap() {
  local a_net a_bc
  cidr_info "$1"; a_net=$CIDR_NET; a_bc=$CIDR_BCAST
  cidr_info "$2"
  (( a_net <= CIDR_BCAST && CIDR_NET <= a_bc ))
}
ip_in_cidr() { cidr_info "$2"; local n; n=$(ip2int "$1"); (( n >= CIDR_NET && n <= CIDR_BCAST )); }

# ----------------------------------------------------------------------------
#  Slices: "SST:SD:DNN:CIDR" -> S_SST S_SD S_DNN S_CIDR S_SUBNET S_GW S_MASK
# ----------------------------------------------------------------------------
parse_slice() {
  local IFS=:
  read -r S_SST S_SD S_DNN S_CIDR <<<"$1"
  cidr_info "${S_CIDR}"
  S_MASK=${CIDR_MASK}
  S_SUBNET="$(int2ip "${CIDR_NET}")/${CIDR_MASK}"
  S_GW="$(int2ip $(( CIDR_NET + 1 )))"
}

# Nome da TUN no UPF para a slice de índice i (ogstun, ogstun2, ogstun3, ...)
tun_name() { (( $1 == 0 )) && echo ogstun || echo "ogstun$(( $1 + 1 ))"; }

msin_len() { echo $(( 15 - ${#MCC} - ${#MNC} )); }
# IMSI do i-ésimo UE do UERANSIM (0-based)
ue_imsi() {
  local len; len=$(msin_len)
  printf "%s%s%0${len}d" "${MCC}" "${MNC}" $(( 10#${UE_MSIN_START} + $1 ))
}

# ----------------------------------------------------------------------------
#  Validação do config.env
# ----------------------------------------------------------------------------
validate_config() {
  local errors=0 e
  bad() { err "config: $*"; errors=$((errors+1)); }

  [[ "${MCC}" =~ ^[0-9]{3}$ ]]    || bad "MCC deve ter 3 dígitos (atual: '${MCC}')"
  [[ "${MNC}" =~ ^[0-9]{2,3}$ ]]  || bad "MNC deve ter 2 ou 3 dígitos (atual: '${MNC}')"
  [[ "${TAC}" =~ ^[0-9]+$ ]] && (( 10#${TAC} >= 1 && 10#${TAC} <= 16777215 )) \
    || bad "TAC deve ser decimal entre 1 e 16777215 (atual: '${TAC}')"
  [[ "${AMF_REGION_ID}" =~ ^[0-9]+$ ]] && (( AMF_REGION_ID <= 255 )) || bad "AMF_REGION_ID 0..255"
  [[ "${AMF_SET_ID}" =~ ^[0-9]+$ ]] && (( AMF_SET_ID <= 1023 ))       || bad "AMF_SET_ID 0..1023"
  [[ "${NETWORK_NAME}" =~ ^[A-Za-z0-9._\ -]+$ ]] || bad "NETWORK_NAME com caracteres inválidos"

  (( ${#SLICES[@]} >= 1 )) || bad "SLICES precisa de pelo menos um item"
  local i s dnns="" cidrs=()
  for i in "${!SLICES[@]}"; do
    s=${SLICES[$i]}
    [[ "$s" =~ ^[0-9]{1,3}:[0-9A-Fa-f]{6}:[A-Za-z0-9][A-Za-z0-9.-]*:[0-9./]+$ ]] \
      || { bad "SLICES[$i]='$s' fora do formato SST:SD:DNN:CIDR (SD = 6 hex)"; continue; }
    valid_cidr "${s##*:}" || { bad "SLICES[$i]: CIDR inválido '${s##*:}' (use /8../30)"; continue; }
    parse_slice "$s"
    (( S_SST >= 1 && S_SST <= 255 )) || bad "SLICES[$i]: SST deve estar entre 1 e 255"
    if [[ " ${dnns} " == *" ${S_DNN} "* ]]; then bad "SLICES[$i]: DNN '${S_DNN}' repetido (use um DNN por slice)"; fi
    dnns+=" ${S_DNN}"
    if cidr_overlap "${S_CIDR}" "${K3S_CLUSTER_CIDR}"; then bad "SLICES[$i]: ${S_CIDR} sobrepõe K3S_CLUSTER_CIDR"; fi
    if cidr_overlap "${S_CIDR}" "${K3S_SERVICE_CIDR}"; then bad "SLICES[$i]: ${S_CIDR} sobrepõe K3S_SERVICE_CIDR"; fi
    for e in "${cidrs[@]}"; do
      if cidr_overlap "${S_CIDR}" "$e"; then bad "SLICES[$i]: ${S_CIDR} sobrepõe ${e}"; fi
    done
    cidrs+=("${S_CIDR}")
  done
  valid_cidr "${K3S_CLUSTER_CIDR}" || bad "K3S_CLUSTER_CIDR inválido"
  valid_cidr "${K3S_SERVICE_CIDR}" || bad "K3S_SERVICE_CIDR inválido"
  if cidr_overlap "${K3S_CLUSTER_CIDR}" "${K3S_SERVICE_CIDR}"; then bad "K3S_CLUSTER_CIDR e K3S_SERVICE_CIDR se sobrepõem"; fi
  for e in ${DNS_SERVERS}; do valid_ipv4 "$e" || bad "DNS_SERVERS: '$e' não é IPv4"; done
  [[ "${UE_MTU}" =~ ^[0-9]+$ ]] && (( UE_MTU >= 1200 && UE_MTU <= 9000 )) || bad "UE_MTU 1200..9000"

  [[ "${UE_KEY}" =~ ^[0-9A-Fa-f]{32}$ ]] || bad "UE_KEY deve ter 32 hex"
  [[ "${UE_OPC}" =~ ^[0-9A-Fa-f]{32}$ ]] || bad "UE_OPC deve ter 32 hex"
  [[ "${UE_COUNT}" =~ ^[0-9]+$ ]] && (( UE_COUNT >= 1 && UE_COUNT <= 100 )) || bad "UE_COUNT 1..100"
  local len; len=$(msin_len)
  [[ "${UE_MSIN_START}" =~ ^[0-9]+$ && ${#UE_MSIN_START} -eq ${len} ]] \
    || bad "UE_MSIN_START deve ter ${len} dígitos (15 - MCC - MNC); atual: '${UE_MSIN_START}'"

  local f
  for i in "${!SUBSCRIBERS[@]}"; do
    IFS=: read -r -a f <<<"${SUBSCRIBERS[$i]}"
    if (( ${#f[@]} != 3 && ${#f[@]} != 6 )); then bad "SUBSCRIBERS[$i]: use IMSI:K:OPC ou IMSI:K:OPC:SST:SD:DNN"; continue; fi
    [[ "${f[0]}" =~ ^[0-9]{15}$ ]] || bad "SUBSCRIBERS[$i]: IMSI deve ter 15 dígitos"
    [[ "${f[1]}" =~ ^[0-9A-Fa-f]{32}$ && "${f[2]}" =~ ^[0-9A-Fa-f]{32}$ ]] || bad "SUBSCRIBERS[$i]: K/OPC devem ter 32 hex"
    if (( ${#f[@]} == 6 )); then
      [[ "${f[3]}" =~ ^[0-9]{1,3}$ && "${f[4]}" =~ ^[0-9A-Fa-f]{6}$ ]] || bad "SUBSCRIBERS[$i]: SST/SD inválidos"
      [[ " ${dnns} " == *" ${f[5]} "* ]] || warn "SUBSCRIBERS[$i]: DNN '${f[5]}' não existe em SLICES"
    fi
  done

  [[ "${ENV_PROFILE}" =~ ^(auto|desktop|server)$ ]] || bad "ENV_PROFILE deve ser auto|desktop|server"
  [[ "${K8S_NAMESPACE}" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || bad "K8S_NAMESPACE inválido"
  [[ "${OPEN5GS_RELEASE}" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || bad "OPEN5GS_RELEASE inválido"
  [[ "${UERANSIM_RELEASE}" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || bad "UERANSIM_RELEASE inválido"
  [[ "${WEBUI_NODEPORT}" =~ ^[0-9]+$ ]] && (( WEBUI_NODEPORT >= 30000 && WEBUI_NODEPORT <= 32767 )) \
    || bad "WEBUI_NODEPORT deve estar em 30000..32767"
  if is_true "${DASHBOARD_ENABLED}"; then
    [[ "${DASHBOARD_NODEPORT}" =~ ^[0-9]+$ ]] && (( DASHBOARD_NODEPORT >= 30000 && DASHBOARD_NODEPORT <= 32767 )) \
      || bad "DASHBOARD_NODEPORT deve estar em 30000..32767"
    [[ "${DASHBOARD_NODEPORT}" != "${WEBUI_NODEPORT}" ]] || bad "DASHBOARD_NODEPORT igual a WEBUI_NODEPORT"
    [[ "${DASHBOARD_HISTORY_SECONDS}" =~ ^[0-9]+$ ]] && (( DASHBOARD_HISTORY_SECONDS >= 60 && DASHBOARD_HISTORY_SECONDS <= 21600 )) \
      || bad "DASHBOARD_HISTORY_SECONDS deve estar em 60..21600"
    [[ -z "${GNB_METRICS_URL}" || "${GNB_METRICS_URL}" =~ ^wss?://[^[:space:]]+$ ]] || bad "GNB_METRICS_URL deve ser ws://host:porta"
    [[ -z "${GNB_LOG_SSH}" || "${GNB_LOG_SSH}" =~ ^[A-Za-z0-9._-]+@[A-Za-z0-9.:_-]+$ ]] || bad "GNB_LOG_SSH deve ser usuario@host"
    [[ "${GNB_LOG_FILE}" =~ ^/[^[:space:]\'\"]+$ ]] || bad "GNB_LOG_FILE deve ser um caminho absoluto sem espaços"
    if [[ -n "${GNB_LOG_DROP}" ]] && ! python3 -c 'import re,sys; re.compile(sys.argv[1])' "${GNB_LOG_DROP}" 2>/dev/null; then
      bad "GNB_LOG_DROP não é uma regex válida"
    fi
  fi
  if [[ -n "${MONGODB_IMAGE_REPOSITORY}${MONGODB_IMAGE_TAG}" ]] && \
     [[ -z "${MONGODB_IMAGE_REPOSITORY}" || -z "${MONGODB_IMAGE_TAG}" ]]; then
    bad "MONGODB_IMAGE_REPOSITORY e MONGODB_IMAGE_TAG devem ser definidos juntos"
  fi
  if [[ -n "${NODE_IP}" ]] && ! valid_ipv4 "${NODE_IP}"; then bad "NODE_IP inválido"; fi
  [[ "${NODE_IP_MODE}" =~ ^(stable|iface)$ ]] || bad "NODE_IP_MODE deve ser stable|iface"
  if [[ "${NODE_IP_MODE}" == stable ]]; then
    valid_ipv4 "${STABLE_IP}" || bad "STABLE_IP inválido"
    [[ "${STABLE_IFACE}" =~ ^[a-zA-Z0-9_-]{1,15}$ ]] || bad "STABLE_IFACE inválido (até 15 caracteres)"
  fi

  if is_true "${RAN_LINK_ENABLED}"; then
    is_true "${EXPOSE_RAN}" && bad "RAN_LINK_ENABLED e EXPOSE_RAN são alternativas: ligue só um"
    [[ "${RAN_LINK_IFACE}" =~ ^[a-zA-Z0-9_.-]{1,15}$ ]] || bad "RAN_LINK_IFACE inválido"
    [[ "${RAN_LINK_MTU}" =~ ^[0-9]+$ ]] && (( RAN_LINK_MTU >= 1280 && RAN_LINK_MTU <= 9216 )) || bad "RAN_LINK_MTU 1280..9216"
    if valid_cidr "${RAN_LINK_CIDR}"; then
      for e in "${K3S_CLUSTER_CIDR}" "${K3S_SERVICE_CIDR}"; do
        if cidr_overlap "${RAN_LINK_CIDR}" "$e"; then bad "RAN_LINK_CIDR sobrepõe $e"; fi
      done
      for e in AMF_N2_IP UPF_N3_IP GNB_SIM_IP; do
        if ! valid_ipv4 "${!e}"; then bad "$e inválido ('${!e}')"
        elif ! cidr_overlap "${!e}/32" "${RAN_LINK_CIDR}"; then bad "$e (${!e}) fora de RAN_LINK_CIDR"; fi
      done
      [[ "${AMF_N2_IP}" != "${UPF_N3_IP}" && "${AMF_N2_IP}" != "${GNB_SIM_IP}" && "${UPF_N3_IP}" != "${GNB_SIM_IP}" ]] \
        || bad "AMF_N2_IP, UPF_N3_IP e GNB_SIM_IP devem ser diferentes"
    else
      bad "RAN_LINK_CIDR inválido ('${RAN_LINK_CIDR}')"
    fi
  fi

  (( errors == 0 )) || die "${errors} erro(s) no ${CONFIG}"
  unset -f bad
}

# ----------------------------------------------------------------------------
#  Detecção de ambiente (desktop x server, interface, IP, recursos)
# ----------------------------------------------------------------------------
detect_env() {
  HAS_NM=false; UFW_ACTIVE=false; HAS_DOCKER=false; HAS_AVX=false; HAS_FIREWALLD=false
  if systemctl is-active --quiet firewalld 2>/dev/null; then HAS_FIREWALLD=true; fi

  if systemctl is-active --quiet NetworkManager 2>/dev/null; then HAS_NM=true; fi
  if command -v ufw &>/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then UFW_ACTIVE=true; fi
  if systemctl is-active --quiet docker 2>/dev/null; then HAS_DOCKER=true; fi
  if grep -qw avx /proc/cpuinfo; then HAS_AVX=true; fi

  if [[ "${ENV_PROFILE}" == "auto" ]]; then
    # graphical.target sozinho não basta: servidores costumam vir com ele como padrão sem
    # nenhuma interface gráfica. Desktop = NetworkManager ativo ou gerenciador de login instalado.
    if ${HAS_NM} || [[ -e /etc/systemd/system/display-manager.service ]]; then
      DETECTED_PROFILE=desktop
    else
      DETECTED_PROFILE=server
    fi
  else
    DETECTED_PROFILE=${ENV_PROFILE}
  fi

  # Interface/IP físicos do host (rota default). Podem mudar (DHCP, Wi-Fi x cabo).
  local need_phys=true
  if [[ "${NODE_IP_MODE}" == stable ]] && ! is_true "${EXPOSE_RAN}"; then need_phys=false; fi
  if [[ -z "${NODE_IFACE}" ]]; then
    NODE_IFACE=$(ip -4 route show default 2>/dev/null | awk '{for(i=1;i<NF;i++) if($i=="dev"){print $(i+1); exit}}')
  fi
  if [[ -n "${NODE_IFACE}" ]] && ip link show "${NODE_IFACE}" &>/dev/null; then
    if [[ -z "${NODE_IP}" ]]; then
      NODE_IP=$(ip -4 -o addr show dev "${NODE_IFACE}" scope global | awk '{print $4}' | cut -d/ -f1 | head -1)
    elif ! ip -4 -o addr show dev "${NODE_IFACE}" | grep -q " ${NODE_IP}/"; then
      warn "NODE_IP ${NODE_IP} não está configurado em ${NODE_IFACE}"
    fi
  else
    NODE_IFACE=""
  fi
  if [[ -z "${NODE_IP}" ]]; then
    ${need_phys} && die "Sem interface/IP de rede detectável; defina NODE_IFACE/NODE_IP no config"
    warn "host sem rede agora (sem rota default) — o cluster funciona mesmo assim (NODE_IP_MODE=stable)"
  fi

  # Endereço que o k3s usa como nó. Em 'stable' é uma interface dummy própria,
  # independente de DHCP/troca de rede; em 'iface' é a interface física.
  if [[ "${NODE_IP_MODE}" == stable ]]; then
    K3S_NODE_IFACE="${STABLE_IFACE}"; K3S_NODE_IP="${STABLE_IP}"
  else
    K3S_NODE_IFACE="${NODE_IFACE}"; K3S_NODE_IP="${NODE_IP}"
  fi

  MEM_MB=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
  CPUS=$(nproc)
}

print_env_summary() {
  info "Perfil do host     : ${C_B}${DETECTED_PROFILE}${C_0} (ENV_PROFILE=${ENV_PROFILE})"
  info "Host (físico)      : ${NODE_IFACE:-sem rede} / ${NODE_IP:-sem IP}"
  info "Nó do k3s          : ${K3S_NODE_IFACE} / ${K3S_NODE_IP} (NODE_IP_MODE=${NODE_IP_MODE})"
  info "CPU / RAM          : ${CPUS} vCPU / ${MEM_MB} MiB (AVX: ${HAS_AVX})"
  info "NetworkManager     : ${HAS_NM}   UFW ativo: ${UFW_ACTIVE}   firewalld: ${HAS_FIREWALLD}   Docker: ${HAS_DOCKER}"
  info "PLMN / TAC         : ${MCC}-${MNC} / ${TAC}"
  local s; for s in "${SLICES[@]}"; do parse_slice "$s"
    info "Slice              : SST=${S_SST} SD=${S_SD} DNN=${S_DNN} pool=${S_SUBNET} gw=${S_GW}"
  done
  info "UEs UERANSIM       : ${UE_COUNT} a partir de IMSI $(ue_imsi 0)"
}

# ----------------------------------------------------------------------------
#  kubectl / helm sempre apontando para o k3s (não usa ~/.kube/config)
# ----------------------------------------------------------------------------
kc() {
  if command -v k3s &>/dev/null; then
    k3s kubectl --kubeconfig "${KUBECONFIG_PATH}" "$@"
  else
    kubectl --kubeconfig "${KUBECONFIG_PATH}" "$@"
  fi
}
find_helm() {
  if [[ -x "${INSTALL_DIR}/bin/helm" ]]; then HELM_BIN="${INSTALL_DIR}/bin/helm"
  elif command -v helm &>/dev/null; then HELM_BIN="$(command -v helm)"
  else HELM_BIN=""; fi
}
hm() { "${HELM_BIN}" --kubeconfig "${KUBECONFIG_PATH}" "$@"; }

k3s_ready() { [[ -r "${KUBECONFIG_PATH}" ]] && kc get --raw /readyz &>/dev/null; }

# Nome do deployment por componente (independe do nome do release)
populate_deploy() {
  kc -n "${K8S_NAMESPACE}" get deploy \
    -l "app.kubernetes.io/instance=${OPEN5GS_RELEASE},app.kubernetes.io/component=populate" \
    -o name 2>/dev/null | head -1
}

# ----------------------------------------------------------------------------
#  Geração dos values Helm a partir do config.env
# ----------------------------------------------------------------------------
_q() { printf '"%s"' "$1"; }   # string YAML entre aspas

# Anotação do Multus: 2ª interface (net1) na rede ran-link com IP fixo
ran_link_annotation() {  # $1 = IP
  printf "k8s.v1.cni.cncf.io/networks: '[{\"name\":\"ran-link\",\"ips\":[\"%s/%s\"]}]'" "$1" "${RAN_LINK_CIDR#*/}"
}

_nf_common() {  # $1 = chave do NF no chart umbrella; $2 (opcional) = IP no ran-link
  echo "$1:"
  # Recreate: em RollingUpdate pods novos descobrem NFs antigos (via NRF antigo) e
  # guardam esse cache por 24h => falhas como "No route to host" no SCP.
  echo "  updateStrategy:"
  echo "    type: Recreate"
  echo "  podAnnotations:"
  echo "    ${HASH_ANNOTATION}: __CONFIG_HASH__"
  if [[ -n "${2:-}" ]]; then echo "    $(ran_link_annotation "$2")"; fi
  if [[ -n "${OPEN5GS_IMAGE_TAG}" ]]; then
    echo "  image:"
    echo "    tag: $(_q "${OPEN5GS_IMAGE_TAG}")"
  fi
  # Prometheus (:9090/metrics) para a aba Core do painel
  if is_true "${OPEN5GS_METRICS}" && [[ " amf smf upf pcf " == *" $1 "* ]]; then
    echo "  metrics:"
    echo "    enabled: true"
  fi
}

render_open5gs_values() {
  local out="${GENERATED_DIR}/open5gs-values.yaml" i s dns body
  mkdir -p "${GENERATED_DIR}"
  body=$(
    echo "# GERADO automaticamente a partir de config.env — não edite à mão."
    if [[ -n "${MONGODB_IMAGE_REPOSITORY}" ]]; then
      echo "global:"
      echo "  security:"
      echo "    allowInsecureImages: true   # imagem MongoDB customizada"
    fi
    echo "populate:"
    echo "  enabled: true"
    echo "  initCommands: []              # assinantes via scripts/subscribers.sh (idempotente)"
    echo "mongodb:"
    echo "  persistence:"
    echo "    enabled: $(is_true "${MONGODB_PERSISTENCE}" && echo true || echo false)"
    echo "    size: $(_q "${MONGODB_PERSISTENCE_SIZE}")"
    if [[ -n "${MONGODB_IMAGE_REPOSITORY}" ]]; then
      echo "  image:"
      if [[ -n "${MONGODB_IMAGE_REGISTRY}" ]]; then echo "    registry: $(_q "${MONGODB_IMAGE_REGISTRY}")"; fi
      echo "    repository: $(_q "${MONGODB_IMAGE_REPOSITORY}")"
      echo "    tag: $(_q "${MONGODB_IMAGE_TAG}")"
    fi

    # --- NRF: PLMN servido. Sem isso o chart usa 999/70 e o SCP trata o UE como
    #     roaming ("No SEPP"), rejeitando o registro com HTTP 400.
    _nf_common nrf
    echo "  config:"
    echo "    servingList:"
    echo "      - plmn_id: {mcc: $(_q "${MCC}"), mnc: $(_q "${MNC}")}"

    for nf in scp ausf udm udr pcf bsf; do _nf_common "$nf"; done

    # --- AMF: GUAMI, TAI, PLMN + S-NSSAI suportados
    #     Com RAN_LINK: net1 no link; o N2 passa a ouvir em net1 (post-renderer amf-ngap-net1.sh)
    if is_true "${RAN_LINK_ENABLED}"; then _nf_common amf "${AMF_N2_IP}"; else _nf_common amf; fi
    echo "  config:"
    echo "    networkName: $(_q "${NETWORK_NAME}")"
    echo "    guamiList:"
    echo "      - plmn_id: {mcc: $(_q "${MCC}"), mnc: $(_q "${MNC}")}"
    echo "        amf_id: {region: ${AMF_REGION_ID}, set: ${AMF_SET_ID}}"
    echo "    taiList:"
    echo "      - plmn_id: {mcc: $(_q "${MCC}"), mnc: $(_q "${MNC}")}"
    echo "        tac: [$((10#${TAC}))]"
    echo "    plmnList:"
    echo "      - plmn_id: {mcc: $(_q "${MCC}"), mnc: $(_q "${MNC}")}"
    echo "        s_nssai:"
    for s in "${SLICES[@]}"; do parse_slice "$s"
      echo "          - {sst: ${S_SST}, sd: $(_q "${S_SD,,}")}"
    done
    if is_true "${EXPOSE_RAN}"; then
      echo "  services:"
      echo "    ngap:"
      echo "      type: LoadBalancer      # ServiceLB do k3s => SCTP ${NODE_IP}:38412"
    fi

    # --- NSSF: uma NSI por slice (todas apontando para o NRF)
    _nf_common nssf
    echo "  config:"
    echo "    nsiList:"
    for s in "${SLICES[@]}"; do parse_slice "$s"
      echo "      - {uri: \"\", sst: ${S_SST}, sd: $(_q "${S_SD,,}")}"
    done

    # --- SMF: pools/DNN, DNS, MTU
    _nf_common smf
    echo "  config:"
    echo "    pcrf:"
    echo "      enabled: false"
    echo "    mtu: ${UE_MTU}"
    echo "    dnsList:"
    for dns in ${DNS_SERVERS}; do echo "      - $(_q "$dns")"; done
    echo "    subnetList:"
    for s in "${SLICES[@]}"; do parse_slice "$s"
      echo "      - {subnet: $(_q "${S_SUBNET}"), gateway: $(_q "${S_GW}"), dnn: $(_q "${S_DNN}")}"
    done

    # --- UPF: uma TUN + NAT por DNN
    if is_true "${RAN_LINK_ENABLED}"; then _nf_common upf "${UPF_N3_IP}"; else _nf_common upf; fi
    echo "  config:"
    if is_true "${RAN_LINK_ENABLED}"; then
      echo "    upf:"
      echo "      gtpu:"
      echo "        dev: net1            # N3 no link com o gNB (${UPF_N3_IP})"
    fi
    if is_true "${EXPOSE_RAN}"; then
      echo "    upf:"
      echo "      gtpu:"
      echo "        advertise: $(_q "${NODE_IP}")   # endereço N3 anunciado ao gNB"
    fi
    echo "    subnetList:"
    for i in "${!SLICES[@]}"; do parse_slice "${SLICES[$i]}"
      echo "      - subnet: $(_q "${S_SUBNET}")"
      echo "        gateway: $(_q "${S_GW}")"
      echo "        dnn: $(_q "${S_DNN}")"
      echo "        dev: $(tun_name "$i")"
      echo "        mask: ${S_MASK}"
      echo "        createDev: true"
      echo "        enableNAT: true"
    done
    echo "  services:"
    # PFCP (N4) sem DNAT: Service headless => o SMF fala direto com o IP do pod do UPF.
    # Com ClusterIP, o tráfego SMF->Service e UPF->SMF (ambos UDP 8805<->8805) colidia no
    # conntrack, a porta de origem do SMF era reescrita e o UPF respondia "Cannot find PFCP-Node".
    echo "    pfcp:"
    echo "      clusterIP: None"
    if is_true "${EXPOSE_RAN}"; then
      echo "    gtpu:"
      echo "      type: LoadBalancer      # ServiceLB do k3s => UDP ${NODE_IP}:2152"
    fi

    # --- WebUI
    if is_true "${WEBUI_ENABLED}"; then
      _nf_common webui
      echo "  enabled: true"
      echo "  ingress:"
      echo "    enabled: false"
      echo "  services:"
      echo "    http:"
      echo "      type: NodePort"
      echo "      nodePorts:"
      echo "        http: $(_q "${WEBUI_NODEPORT}")"
    else
      echo "webui:"
      echo "  enabled: false"
    fi
  )
  OPEN5GS_HASH=$(printf '%s' "${body}" | sha256sum | cut -c1-16)
  printf '%s\n' "${body//__CONFIG_HASH__/$(_q "${OPEN5GS_HASH}")}" >"${out}"
  OPEN5GS_VALUES="${out}"
}

# Rede ran-link (NetworkAttachmentDefinition do Multus): macvlan sobre RAN_LINK_IFACE.
# O IP de cada pod vem da anotação dele (IPAM static). No macvlan o próprio host
# não enxerga os pods pela RAN_LINK_IFACE; o gNB do outro lado do cabo, sim.
render_ran_link_nad() {
  local out="${GENERATED_DIR}/ran-link-nad.yaml"
  mkdir -p "${GENERATED_DIR}"
  cat >"${out}" <<EOF
# GERADO automaticamente a partir de config.env — não edite à mão.
apiVersion: k8s.cni.cncf.io/v1
kind: NetworkAttachmentDefinition
metadata:
  name: ran-link
  namespace: ${K8S_NAMESPACE}
spec:
  config: |-
    {
      "cniVersion": "0.3.1",
      "type": "macvlan",
      "master": "${RAN_LINK_IFACE}",
      "mode": "bridge",
      "mtu": ${RAN_LINK_MTU},
      "ipam": { "type": "static" },
      "capabilities": { "ips": true }
    }
EOF
  RAN_LINK_NAD="${out}"
}

# Painel (dashboard/): ServiceAccount só leitura, ConfigMap com os arquivos da
# página, Secret (senha/token), Deployment e Service NodePort.
render_dashboard() {
  local out="${GENERATED_DIR}/dashboard.yaml" app="${PROJECT_DIR}/dashboard/app" files=() f hash cm
  mkdir -p "${GENERATED_DIR}"
  for f in server.py index.html app.js style.css favicon.svg uPlot.iife.min.js uPlot.min.css; do
    [[ -f "${app}/${f}" ]] || die "arquivo do painel ausente: ${app}/${f}"
    files+=(--from-file="${f}=${app}/${f}")
  done
  cm=$(kc -n "${K8S_NAMESPACE}" create configmap dashboard-app "${files[@]}" --dry-run=client -o yaml)
  # O hash muda quando a página ou a config mudam => o pod reinicia sozinho
  hash=$(printf '%s\n' "${cm}" "${GNB_METRICS_URL}" "${GNB_NAME}" "${NETWORK_NAME}" "${DASHBOARD_HISTORY_SECONDS}" \
         "${OPEN5GS_METRICS}" "${DASHBOARD_IMAGE}" "${DASHBOARD_PASSWORD}" "${DASHBOARD_INGEST_TOKEN}" | sha256sum | cut -c1-16)
  {
    echo "# GERADO automaticamente a partir de config.env — não edite à mão."
    printf '%s\n' "${cm}" | sed '/creationTimestamp/d'
    cat <<EOF
---
apiVersion: v1
kind: Secret
metadata:
  name: dashboard
  namespace: ${K8S_NAMESPACE}
type: Opaque
stringData:
  password: $(_q "${DASHBOARD_PASSWORD}")
  ingest-token: $(_q "${DASHBOARD_INGEST_TOKEN}")
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: dashboard
  namespace: ${K8S_NAMESPACE}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: dashboard-read
  namespace: ${K8S_NAMESPACE}
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: dashboard-read
  namespace: ${K8S_NAMESPACE}
subjects:
  - kind: ServiceAccount
    name: dashboard
    namespace: ${K8S_NAMESPACE}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: dashboard-read
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dashboard
  namespace: ${K8S_NAMESPACE}
  labels: {app.kubernetes.io/name: dashboard, app.kubernetes.io/part-of: open5gk3s}
spec:
  replicas: 1
  strategy: {type: Recreate}
  selector:
    matchLabels: {app.kubernetes.io/name: dashboard}
  template:
    metadata:
      labels: {app.kubernetes.io/name: dashboard, app.kubernetes.io/part-of: open5gk3s}
      annotations:
        ${HASH_ANNOTATION}: $(_q "${hash}")
    spec:
      serviceAccountName: dashboard
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534
        runAsGroup: 65534
        seccompProfile: {type: RuntimeDefault}
      containers:
        - name: dashboard
          image: $(_q "${DASHBOARD_IMAGE}")
          command: ["python3", "-u", "/app/server.py"]
          ports:
            - {name: http, containerPort: 8080}
          env:
            - {name: NAMESPACE, valueFrom: {fieldRef: {fieldPath: metadata.namespace}}}
            - {name: PORT, value: "8080"}
            - {name: PYTHONDONTWRITEBYTECODE, value: "1"}
            - {name: OPEN5GS_RELEASE, value: $(_q "${OPEN5GS_RELEASE}")}
            - {name: GNB_METRICS_URL, value: $(_q "${GNB_METRICS_URL}")}
            - {name: GNB_NAME, value: $(_q "${GNB_NAME}")}
            - {name: NETWORK_NAME, value: $(_q "${NETWORK_NAME}")}
            - {name: HISTORY_SECONDS, value: $(_q "${DASHBOARD_HISTORY_SECONDS}")}
            - {name: CORE_METRICS, value: $(_q "$(is_true "${OPEN5GS_METRICS}" && echo true || echo false)")}
            - {name: DASHBOARD_PASSWORD, valueFrom: {secretKeyRef: {name: dashboard, key: password}}}
            - {name: INGEST_TOKEN, valueFrom: {secretKeyRef: {name: dashboard, key: ingest-token}}}
          readinessProbe:
            httpGet: {path: /api/health, port: http}
            periodSeconds: 10
          livenessProbe:
            httpGet: {path: /api/health, port: http}
            initialDelaySeconds: 20
            periodSeconds: 20
          resources:
            requests: {cpu: 50m, memory: 64Mi}
            limits: {memory: 512Mi}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
          volumeMounts:
            - {name: app, mountPath: /app, readOnly: true}
      volumes:
        - name: app
          configMap: {name: dashboard-app}
---
apiVersion: v1
kind: Service
metadata:
  name: dashboard
  namespace: ${K8S_NAMESPACE}
spec:
  type: NodePort
  selector: {app.kubernetes.io/name: dashboard}
  ports:
    - {name: http, port: 80, targetPort: http, nodePort: ${DASHBOARD_NODEPORT}}
EOF
  } >"${out}"
  DASHBOARD_MANIFEST="${out}"
}

render_ueransim_values() {
  local out="${GENERATED_DIR}/ueransim-values.yaml" body
  mkdir -p "${GENERATED_DIR}"
  parse_slice "${SLICES[0]}"
  body=$(
    echo "# GERADO automaticamente a partir de config.env — não edite à mão."
    echo "fullnameOverride: $(_q "${UERANSIM_RELEASE}")"
    if [[ -n "${UERANSIM_IMAGE_TAG}" ]]; then
      echo "image:"
      echo "  tag: $(_q "${UERANSIM_IMAGE_TAG}")"
      echo "  pullPolicy: IfNotPresent"
    else
      echo "image:"
      echo "  pullPolicy: IfNotPresent"
    fi
    echo "podAnnotations:"
    echo "  ${HASH_ANNOTATION}: __CONFIG_HASH__"
    if is_true "${RAN_LINK_ENABLED}"; then
      # gNB simulado no mesmo link do gNB real: N2 e N3 por net1; rádio (UEs) segue no eth0
      echo "  $(ran_link_annotation "${GNB_SIM_IP}")"
      echo "amf:"
      echo "  ip: $(_q "${AMF_N2_IP}")"
      echo "interfaces:"
      echo "  n2: {dev: net1}"
      echo "  n3: {dev: net1}"
      echo "  radio: {dev: eth0}"
    else
      echo "amf:"
      echo "  hostname: $(_q "${OPEN5GS_RELEASE}-amf-ngap")"
    fi
    echo "mcc: $(_q "${MCC}")"
    echo "mnc: $(_q "${MNC}")"
    echo "tac: $(_q "$((10#${TAC}))")"
    echo "sst: ${S_SST}"
    echo "sd: $(_q "0x${S_SD,,}")"
    echo "ues:"
    echo "  enabled: true"
    echo "  count: ${UE_COUNT}"
    echo "  initialMSISDN: $(_q "${UE_MSIN_START}")"
    echo "  key: $(_q "${UE_KEY^^}")"
    echo "  op: $(_q "${UE_OPC^^}")"
    echo "  opType: OPC"
    echo "  podAnnotations:"
    echo "    ${HASH_ANNOTATION}: __CONFIG_HASH__"
    echo "  apnList:"
    echo "    - type: IPv4"
    echo "      apn: $(_q "${S_DNN}")"
    echo "      slice:"
    echo "        sst: ${S_SST}"
    echo "        sd: $(_q "0x${S_SD,,}")"
    echo "      emergency: false"
  )
  # Inclui o hash do core: se o core mudar, gNB/UEs reiniciam e se reconectam
  UERANSIM_HASH=$(printf '%s%s' "${body}" "${OPEN5GS_HASH:-}" | sha256sum | cut -c1-16)
  printf '%s\n' "${body//__CONFIG_HASH__/$(_q "${UERANSIM_HASH}")}" >"${out}"
  UERANSIM_VALUES="${out}"
}

# ----------------------------------------------------------------------------
#  Assinantes: gera script bash executado dentro do pod "populate"
#  (open5gs-dbctl: remove + add_ue_with_slice => idempotente)
# ----------------------------------------------------------------------------
subscriber_lines() {  # imprime "IMSI K OPC DNN SST SD" por linha
  local i f
  parse_slice "${SLICES[0]}"
  local d_sst=${S_SST} d_sd=${S_SD,,} d_dnn=${S_DNN}
  for (( i = 0; i < UE_COUNT; i++ )); do
    echo "$(ue_imsi "$i") ${UE_KEY^^} ${UE_OPC^^} ${d_dnn} ${d_sst} ${d_sd}"
  done
  for i in "${!SUBSCRIBERS[@]}"; do
    IFS=: read -r -a f <<<"${SUBSCRIBERS[$i]}"
    if (( ${#f[@]} == 6 )); then
      echo "${f[0]} ${f[1]^^} ${f[2]^^} ${f[5]} ${f[3]} ${f[4],,}"
    else
      echo "${f[0]} ${f[1]^^} ${f[2]^^} ${d_dnn} ${d_sst} ${d_sd}"
    fi
  done
}

populate_exec() {  # executa um script bash no pod populate
  local dep; dep=$(populate_deploy)
  [[ -n "${dep}" ]] || die "Deployment 'populate' do Open5GS não encontrado no namespace ${K8S_NAMESPACE}"
  kc -n "${K8S_NAMESPACE}" exec -i "${dep}" -c populate -- /bin/bash -s <<<"$1"
}

sync_subscribers() {
  local script="set -e" imsi k opc dnn sst sd n=0
  while read -r imsi k opc dnn sst sd; do
    [[ -n "${imsi}" ]] || continue
    script+=$'\n'"open5gs-dbctl remove ${imsi} >/dev/null 2>&1 || true"
    script+=$'\n'"open5gs-dbctl add_ue_with_slice ${imsi} ${k} ${opc} ${dnn} ${sst} ${sd} >/dev/null"
    script+=$'\n'"echo '    + ${imsi}  DNN=${dnn}  S-NSSAI=${sst}/${sd}'"
    n=$((n+1))
  done < <(subscriber_lines)
  populate_exec "${script}"
  ok "${n} assinante(s) sincronizado(s)"
}

# ----------------------------------------------------------------------------
#  kubeconfig e atalhos do usuário real (quem chamou o sudo)
# ----------------------------------------------------------------------------
KCTX="open5gs-k3s"   # nome do cluster/contexto/usuário no ~/.kube/config
BASHRC_BEGIN="# >>> open5gs-k3s >>>"
BASHRC_END="# <<< open5gs-k3s <<<"

# Define TARGET_USER / TARGET_HOME / TARGET_GROUP: KUBECONFIG_USER > SUDO_USER > root
resolve_target_user() {
  TARGET_USER="${KUBECONFIG_USER:-${SUDO_USER:-root}}"
  getent passwd "${TARGET_USER}" >/dev/null || die "usuário '${TARGET_USER}' não existe (KUBECONFIG_USER/SUDO_USER)"
  TARGET_HOME=$(getent passwd "${TARGET_USER}" | cut -d: -f6)
  TARGET_GROUP=$(id -gn "${TARGET_USER}")
}

# Copia do k3s.yaml com nomes "default" trocados por ${KCTX} (evita colisão no merge)
_renamed_k3s_kubeconfig() {
  sed -e "s/^  name: default\$/  name: ${KCTX}/" \
      -e "s/^    cluster: default\$/    cluster: ${KCTX}/" \
      -e "s/^    user: default\$/    user: ${KCTX}/" \
      -e "s/^- name: default\$/- name: ${KCTX}/" \
      -e "s/^current-context: default\$/current-context: ${KCTX}/" "$1"
}

# setup_user_kubeconfig SRC: instala/mescla o kubeconfig no ~/.kube/config do usuário-alvo.
# Idempotente: só grava se o conteúdo mudar; backup único do config original.
setup_user_kubeconfig() {
  local src="$1" kdir="${TARGET_HOME}/.kube" cfg="${TARGET_HOME}/.kube/config"
  local own="${TARGET_HOME}/.kube/${KCTX}.yaml" tmp merged cur
  tmp=$(mktemp); merged=$(mktemp)
  _renamed_k3s_kubeconfig "${src}" >"${tmp}"
  grep -q "^current-context: ${KCTX}\$" "${tmp}" || { rm -f "${tmp}" "${merged}"; die "formato inesperado em ${src}"; }
  [[ -d "${kdir}" ]] || install -d -m 0700 -o "${TARGET_USER}" -g "${TARGET_GROUP}" "${kdir}"
  # cópia avulsa (usada por test.sh/subscribers.sh quando sem root)
  cmp -s "${tmp}" "${own}" 2>/dev/null || install -m 0600 -o "${TARGET_USER}" -g "${TARGET_GROUP}" "${tmp}" "${own}"

  if [[ ! -s "${cfg}" ]] || ! grep -q 'server:' "${cfg}"; then
    # inexistente ou vazio (sem clusters): usa o nosso
    if [[ -s "${cfg}" && ! -e "${cfg}.bak-${KCTX}" ]]; then cp -p "${cfg}" "${cfg}.bak-${KCTX}"; fi
    cp "${tmp}" "${merged}"
  else
    # já tem clusters: merge (o 1º arquivo vence em nomes repetidos => nossas credenciais atualizadas)
    cur=$(k3s kubectl --kubeconfig "${cfg}" config current-context 2>/dev/null || true)
    KUBECONFIG="${tmp}:${cfg}" k3s kubectl config view --flatten >"${merged}"
    if [[ -n "${cur}" && "${cur}" != "${KCTX}" ]] && \
       k3s kubectl --kubeconfig "${merged}" config get-contexts "${cur}" &>/dev/null; then
      k3s kubectl --kubeconfig "${merged}" config use-context "${cur}" >/dev/null
      KCTX_NOT_CURRENT=true
    fi
  fi
  if ! cmp -s "${merged}" "${cfg}" 2>/dev/null; then
    if [[ -s "${cfg}" && ! -e "${cfg}.bak-${KCTX}" ]]; then cp -p "${cfg}" "${cfg}.bak-${KCTX}"; fi
    install -m 0600 -o "${TARGET_USER}" -g "${TARGET_GROUP}" "${merged}" "${cfg}"
    KUBECONFIG_CHANGED=true
  fi
  rm -f "${tmp}" "${merged}"
}

# Remove do ~/.kube/config do usuário-alvo só as entradas ${KCTX}
remove_user_kubeconfig() {
  local cfg="${TARGET_HOME}/.kube/config" kbin
  rm -f "${TARGET_HOME}/.kube/${KCTX}.yaml"
  [[ -f "${cfg}" ]] || return 0
  if command -v k3s &>/dev/null; then kbin=(k3s kubectl); elif command -v kubectl &>/dev/null; then kbin=(kubectl); else return 0; fi
  if [[ "$("${kbin[@]}" --kubeconfig "${cfg}" config current-context 2>/dev/null)" == "${KCTX}" ]]; then
    "${kbin[@]}" --kubeconfig "${cfg}" config unset current-context >/dev/null
  fi
  "${kbin[@]}" --kubeconfig "${cfg}" config delete-context "${KCTX}" &>/dev/null || true
  "${kbin[@]}" --kubeconfig "${cfg}" config delete-cluster "${KCTX}" &>/dev/null || true
  "${kbin[@]}" --kubeconfig "${cfg}" config delete-user "${KCTX}" &>/dev/null || true
  chown "${TARGET_USER}:${TARGET_GROUP}" "${cfg}"
}

# Alias k=kubectl + autocomplete no ~/.bashrc (bloco com marcadores, só se não existir)
setup_user_bashrc() {
  local rc="${TARGET_HOME}/.bashrc"
  [[ -f "${rc}" ]] || install -m 0644 -o "${TARGET_USER}" -g "${TARGET_GROUP}" /dev/null "${rc}"
  grep -qF "${BASHRC_BEGIN}" "${rc}" && return 0
  local alias_line='alias k=kubectl'
  # não sobrescreve um alias k já definido pelo usuário
  if grep -qE '^\s*alias k=' "${rc}"; then alias_line='# alias k já definido acima pelo usuário'; fi
  cat >>"${rc}" <<EOB

${BASHRC_BEGIN}
# Adicionado por open5GK3S/install.sh (removido por uninstall.sh --purge)
${alias_line}
if command -v kubectl >/dev/null 2>&1; then
  source <(kubectl completion bash 2>/dev/null)
  complete -o default -F __start_kubectl k
fi
${BASHRC_END}
EOB
  BASHRC_CHANGED=true
}

remove_user_bashrc() {
  local rc="${TARGET_HOME}/.bashrc"
  [[ -f "${rc}" ]] && grep -qF "${BASHRC_BEGIN}" "${rc}" || return 1
  # apaga o bloco e a linha em branco que o precede
  sed -i "/^${BASHRC_BEGIN//\//\\/}\$/,/^${BASHRC_END//\//\\/}\$/d" "${rc}"
  sed -i -e :a -e '/^\n*$/{$d;N;ba' -e '}' "${rc}"
}

# ----------------------------------------------------------------------------
#  Recuperação do plano de usuário (install.sh, scripts/heal.sh, boot)
#  Depois de reboot/restart do k3s os pods voltam em ordem qualquer e o SMF pode
#  ficar com uma associação PFCP que o UPF não reconhece ("Cannot find
#  PFCP-Node"), ou o gNB/UE ficam presos. Sintoma: UE registra mas não pinga.
# ----------------------------------------------------------------------------
_ues_dep()  { echo "deploy/${UERANSIM_RELEASE}-ues"; }
_gnb_has_ngsetup() {
  kc -n "${K8S_NAMESPACE}" logs "deploy/${UERANSIM_RELEASE}" 2>/dev/null | grep -q "NG Setup procedure is successful"
}
# Todos os UEs registrados e pingando o gateway do UPF pela uesimtunN
ue_plane_ok() {
  local i imsi gw; parse_slice "${SLICES[0]}"; gw="${S_GW}"
  for (( i = 0; i < UE_COUNT; i++ )); do
    imsi=$(ue_imsi "$i")
    kc -n "${K8S_NAMESPACE}" exec "$(_ues_dep)" -c ues -- nr-cli "imsi-${imsi}" --exec status 2>/dev/null \
      | grep -q "RM-REGISTERED" || return 1
    kc -n "${K8S_NAMESPACE}" exec "$(_ues_dep)" -c ues -- ping -I "uesimtun${i}" -c 2 -W 2 -q "${gw}" &>/dev/null || return 1
  done
}
_wait_plane() {  # $1 = segundos
  local t=0
  while (( t < $1 )); do ue_plane_ok && return 0; sleep 5; (( t += 5 )); done
  return 1
}
_restart() {  # deployments em sequência, cada um esperando ficar pronto
  local d
  for d in "$@"; do
    kc -n "${K8S_NAMESPACE}" get "deploy/${d}" &>/dev/null || continue
    kc -n "${K8S_NAMESPACE}" rollout restart "deploy/${d}" >/dev/null
    kc -n "${K8S_NAMESPACE}" rollout status "deploy/${d}" --timeout=300s >/dev/null || warn "deploy/${d} demorou a ficar pronto"
  done
}
# Garante UEs registrados com plano de usuário funcionando. Escalonado:
# espera -> reinicia só os UEs (corrida do UERANSIM) -> reinicia UPF, SMF, gNB e UEs
# nessa ordem (refaz a associação PFCP e o NG Setup). Retorna 1 se não resolver.
ensure_user_plane() {
  kc -n "${K8S_NAMESPACE}" get "$(_ues_dep)" &>/dev/null || { info "UERANSIM não implantado; nada a verificar"; return 0; }
  local t=0
  until _gnb_has_ngsetup; do (( t += 3 )); (( t < 120 )) || break; sleep 3; done
  if _gnb_has_ngsetup && _wait_plane 60; then ok "${UE_COUNT} UE(s) registrado(s) e plano de usuário OK"; return 0; fi

  info "UE(s) sem registro/ping; reiniciando o pod dos UEs"
  _restart "${UERANSIM_RELEASE}-ues"
  if _wait_plane 60; then ok "plano de usuário OK após reiniciar os UEs"; return 0; fi

  info "ainda falhando; reiniciando UPF -> SMF -> gNB -> UEs (refaz PFCP/N4 e NG Setup)"
  _restart "${OPEN5GS_RELEASE}-upf" "${OPEN5GS_RELEASE}-smf"
  sleep 5
  _restart "${UERANSIM_RELEASE}" "${UERANSIM_RELEASE}-ues"
  if _wait_plane 120; then ok "plano de usuário OK após reiniciar UPF/SMF/gNB/UEs"; return 0; fi
  return 1
}
