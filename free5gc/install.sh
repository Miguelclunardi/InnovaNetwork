#!/usr/bin/env bash
# =============================================================================
#  free5gc/install.sh — core free5GC no k3s que já existe (segundo core).
#
#  Não instala nem altera o k3s, o Multus ou o Open5GS: só cria/atualiza o
#  namespace do free5GC. Roda como usuário comum (kubeconfig do usuário).
#  Pré-requisito no host (uma vez, com sudo): free5gc/setup-gtp5g.sh
#
#  Uso:  ./free5gc/install.sh                (instala/atualiza e sobe)
#        ./free5gc/install.sh --dry-run      (gera e valida no servidor; não aplica)
#        ./free5gc/install.sh --assinantes   (só sincroniza os assinantes do config.env)
#        ./free5gc/install.sh --importar-open5gs  (copia os SIMs cadastrados no Open5GS;
#                                     as chaves vão direto de um banco ao outro, sem aparecer)
#        ./free5gc/install.sh --parado       (instala e deixa tudo em 0 réplicas)
#        ./free5gc/install.sh --sem-ueransim
# =============================================================================
set -Eeuo pipefail

F5_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "${F5_DIR}")"
# shellcheck source=../scripts/lib/common.sh
source "${PROJECT_DIR}/scripts/lib/common.sh"

DRY=false; ONLY_SUBS=false; IMPORT=false; STOPPED=false; NO_UERANSIM=false
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=true ;;
    --assinantes) ONLY_SUBS=true ;;
    --importar-open5gs) IMPORT=true; ONLY_SUBS=true ;;
    --parado) STOPPED=true ;;
    --sem-ueransim) NO_UERANSIM=true ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "opção desconhecida: $a" ;;
  esac
done

load_config
# shellcheck source=free5gc.env
source "${F5_DIR}/free5gc.env"
declare -p F5_UE_POOLS &>/dev/null || die "F5_UE_POOLS não definido em free5gc/free5gc.env"
# helm/kubectl do usuário (load_config aponta o cache do helm para /opt, do root)
unset HELM_CACHE_HOME HELM_CONFIG_HOME HELM_DATA_HOME
KUBECTL="kubectl"
[[ $EUID -ne 0 ]] || KUBECTL="kubectl --kubeconfig ${KUBECONFIG_PATH:-/etc/rancher/k3s/k3s.yaml}"
k() { ${KUBECTL} "$@"; }
HELM="$(command -v helm || echo /usr/local/bin/helm)"
STATE="${F5_STATE_DIR:-${HOME}/.config/innovanetwork/free5gc}"
OUT="${GENERATED_DIR}/free5gc"
NS="${F5_NAMESPACE}"

# ---------------------------------------------------------------- validação
step "free5GC ${F5_VERSION} — validação"
is_true "${RAN_LINK_ENABLED}" || die "o free5GC usa o link da fibra: RAN_LINK_ENABLED=true no config.env"
(( ${#F5_UE_POOLS[@]} >= ${#SLICES[@]} )) || die "F5_UE_POOLS precisa de um pool por item de SLICES (${#SLICES[@]})"
for v in F5_AMF_N2_IP F5_UPF_N3_IP F5_GNB_SIM_IP; do
  valid_ipv4 "${!v}" || die "${v} inválido: ${!v}"
  ip_in_cidr "${!v}" "${RAN_LINK_CIDR}" || die "${v}=${!v} fora de RAN_LINK_CIDR (${RAN_LINK_CIDR})"
  for o in AMF_N2_IP UPF_N3_IP GNB_SIM_IP; do
    [[ "${!v}" != "${!o}" ]] || die "${v}=${!v} é o mesmo IP do Open5GS (${o}); use outro"
  done
done
for p in "${F5_UE_POOLS[@]}"; do
  valid_cidr "${p}" || die "pool inválido: ${p}"
  for s in "${SLICES[@]}"; do
    parse_slice "${s}"
    ! cidr_overlap "${p}" "${S_SUBNET}" || die "pool ${p} se sobrepõe ao do Open5GS (${S_SUBNET})"
  done
done
k get crd network-attachment-definitions.k8s.cni.cncf.io >/dev/null 2>&1 || die "Multus não encontrado (rode o install.sh da raiz antes)"
ok "config ok: AMF ${F5_AMF_N2_IP}, UPF ${F5_UPF_N3_IP}, gNB simulado ${F5_GNB_SIM_IP}, pools ${F5_UE_POOLS[*]}"
if ! ${DRY} && ! ${ONLY_SUBS} && ! grep -q '^gtp5g ' /proc/modules; then
  die "módulo gtp5g não carregado (o UPF do free5GC precisa dele). Uma vez, com sudo: sudo ./free5gc/setup-gtp5g.sh"
fi

# Variáveis para os geradores (Python)
export F5_NAMESPACE F5_VERSION F5_REGISTRY F5_MONGO_IMAGE F5_MONGO_SIZE F5_AMF_N2_IP F5_UPF_N3_IP F5_GNB_SIM_IP
export F5_WEBUI_NODEPORT F5_NETWORK_NAME_SHORT F5_UERANSIM_RELEASE F5_LOG_LEVEL
export MCC MNC TAC DNS_SERVERS NETWORK_NAME RAN_LINK_IFACE RAN_LINK_CIDR RAN_LINK_MTU UE_COUNT UE_MSIN_START UE_KEY UE_OPC
F5_UE_POOLS_TXT=$(printf '%s\n' "${F5_UE_POOLS[@]}"); SLICES_TXT=$(printf '%s\n' "${SLICES[@]}")
SUBS_TXT=$(printf '%s\n' "${SUBSCRIBERS[@]+"${SUBSCRIBERS[@]}"}")
export F5_UE_POOLS_ENV="${F5_UE_POOLS_TXT}" SLICES_ENV="${SLICES_TXT}" SUBSCRIBERS_ENV="${SUBS_TXT}"
export F5_WEBUI_URL="http://127.0.0.1:${F5_WEBUI_NODEPORT}"

sync_subs() {
  step "Assinantes (WebConsole)"
  local i
  for i in $(seq 1 60); do
    curl -s -o /dev/null --max-time 2 "${F5_WEBUI_URL}" && break; sleep 2
  done
  python3 "${F5_DIR}/lib/subscribers.py"
}
import_open5gs() {
  step "Importando os SIMs do Open5GS (${K8S_NAMESPACE}) para o free5GC"
  local m
  m=$(k -n "${K8S_NAMESPACE}" get pod -l app.kubernetes.io/name=mongodb -o name | head -1)
  [[ -n "${m}" ]] || die "MongoDB do Open5GS não encontrado (o Open5GS precisa estar no ar para exportar)"
  k -n "${K8S_NAMESPACE}" exec "${m}" -c mongodb -- mongosh --quiet open5gs --eval \
    'print(EJSON.stringify(db.subscribers.find({}, {imsi: 1, security: 1, slice: 1, _id: 0}).toArray(), {relaxed: true}))' \
    | python3 "${F5_DIR}/lib/subscribers.py" --from-open5gs
}
if ${ONLY_SUBS}; then sync_subs; ! ${IMPORT} || import_open5gs; exit 0; fi

# ---------------------------------------------------------------- certificados
# PKI de teste própria (o free5GC exige os arquivos mesmo com SBI em http). Fica fora do git.
make_certs() {
  local nf
  mkdir -p "${STATE}/cert"; chmod 700 "${STATE}"
  if [[ ! -f "${STATE}/cert/root.pem" ]]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=free5gc-root" \
      -keyout "${STATE}/cert/root.key" -out "${STATE}/cert/root.pem" 2>/dev/null
  fi
  for nf in nrf amf smf ausf udm udr pcf nssf chf nef; do
    [[ -f "${STATE}/cert/${nf}.pem" ]] && continue
    openssl req -newkey rsa:2048 -nodes -subj "/CN=${nf}" -keyout "${STATE}/cert/${nf}.key" \
      -out "${STATE}/cert/${nf}.csr" 2>/dev/null
    openssl x509 -req -in "${STATE}/cert/${nf}.csr" -CA "${STATE}/cert/root.pem" -CAkey "${STATE}/cert/root.key" \
      -CAcreateserial -days 3650 -out "${STATE}/cert/${nf}.pem" \
      -extfile <(printf 'subjectAltName=DNS:%s,DNS:%s.%s.svc.cluster.local' "${nf}" "${nf}" "${NS}") 2>/dev/null
    rm -f "${STATE}/cert/${nf}.csr"
  done
  chmod 600 "${STATE}"/cert/*
}

# ---------------------------------------------------------------- manifestos
step "Gerando manifestos (${OUT})"
mkdir -p "${OUT}"
python3 "${F5_DIR}/lib/render.py" manifests >"${OUT}/free5gc.json"
python3 "${F5_DIR}/lib/render.py" ueransim >"${OUT}/ueransim-values.json"
make_certs
ok "manifestos: $(python3 -c 'import json,sys;print(len(json.load(open(sys.argv[1]))["items"]))' "${OUT}/free5gc.json") objetos; certificados em ${STATE}/cert"

if ${DRY}; then
  step "Validação no servidor (dry-run; nada é aplicado)"
  if k get ns "${NS}" >/dev/null 2>&1; then
    k apply --dry-run=server -f "${OUT}/free5gc.json" | sed 's/^/    /'
  else
    # namespace ainda não existe: valida o próprio namespace e os demais só no cliente
    k apply --dry-run=server -f <(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(json.dumps(d["items"][0]))' "${OUT}/free5gc.json") | sed 's/^/    /'
    k apply --dry-run=client -f "${OUT}/free5gc.json" | sed 's/^/    /'
  fi
  "${HELM}" template "${F5_UERANSIM_RELEASE}" "${CHARTS_DIR}/charts/ueransim-gnb" -n "${NS}" \
    -f "${OUT}/ueransim-values.json" >/dev/null && ok "values do UERANSIM ok"
  exit 0
fi

step "Aplicando no namespace ${NS}"
k apply -f <(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(json.dumps(d["items"][0]))' "${OUT}/free5gc.json") >/dev/null
k -n "${NS}" create secret generic free5gc-cert --from-file="${STATE}/cert" --dry-run=client -o yaml \
  | k apply -f - >/dev/null
k apply --server-side --field-manager=innovanetwork --force-conflicts -f "${OUT}/free5gc.json" >/dev/null
ok "aplicado"

if ${STOPPED}; then
  k -n "${NS}" scale deploy --all --replicas=0 >/dev/null
  ok "free5GC instalado e PARADO (0 réplicas): inicie pela aba Controle ou com: kubectl -n ${NS} scale deploy --all --replicas=1"
  exit 0
fi

step "Subindo em ordem"
for d in mongodb nrf udr udm ausf nssf pcf chf nef webui upf smf amf; do
  if k -n "${NS}" rollout status "deploy/${d}" --timeout=300s >/dev/null 2>&1; then
    ok "${d}"
  else
    k -n "${NS}" get pods -l "nf=${d}" | sed 's/^/    /'
    die "${d} não ficou pronto (kubectl -n ${NS} logs deploy/${d})"
  fi
done
sync_subs

if ! ${NO_UERANSIM} && is_true "${F5_DEPLOY_UERANSIM}"; then
  step "UERANSIM do free5GC (gNB ${F5_GNB_SIM_IP} -> AMF ${F5_AMF_N2_IP})"
  "${HELM}" upgrade --install "${F5_UERANSIM_RELEASE}" "${CHARTS_DIR}/charts/ueransim-gnb" -n "${NS}" \
    -f "${OUT}/ueransim-values.json" --post-renderer "${PROJECT_DIR}/helm/postrender/drop-gnb-hpa.sh" \
    --wait --timeout 10m >/dev/null || die "UERANSIM do free5GC falhou (kubectl -n ${NS} get pods)"
  # helm não mexe em réplicas que alguém zerou (core parado): volta o gNB e depois os UEs
  for d in "${F5_UERANSIM_RELEASE}" "${F5_UERANSIM_RELEASE}-ues"; do
    k -n "${NS}" scale deploy "${d}" --replicas=1 >/dev/null 2>&1 || continue
    k -n "${NS}" rollout status deploy "${d}" --timeout=180s >/dev/null || die "${d} não subiu"
  done
  ok "UERANSIM no ar (teste: ./free5gc/test.sh)"
fi

step "Pronto"
info "WebConsole: http://<IP do torre2>:${F5_WEBUI_NODEPORT}  (usuário admin; troque a senha padrão)"
info "gNB OCUDU: no .yml, cu_cp.amf.addr = ${F5_AMF_N2_IP}"
info "Pods: kubectl -n ${NS} get pods"
