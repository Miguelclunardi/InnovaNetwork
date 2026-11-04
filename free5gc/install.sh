#!/usr/bin/env bash
# =============================================================================
#  free5gc/install.sh — free5GC core on the existing k3s (second core).
#
#  Does not install or change k3s, Multus or Open5GS: only creates/updates the
#  free5GC namespace. Runs as a regular user (the user's kubeconfig).
#  Host prerequisite (once, with sudo): free5gc/setup-gtp5g.sh
#
#  Usage: ./free5gc/install.sh                (installs/updates and starts)
#         ./free5gc/install.sh --dry-run      (generates and validates on the server; does not apply)
#         ./free5gc/install.sh --subscribers  (only syncs the config.env subscribers)
#         ./free5gc/install.sh --import-open5gs  (copies the SIMs registered in Open5GS;
#                                     the keys go straight from one database to the other, unseen)
#         ./free5gc/install.sh --stopped      (installs and leaves everything at 0 replicas)
#         ./free5gc/install.sh --no-ueransim
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
    --subscribers) ONLY_SUBS=true ;;
    --import-open5gs) IMPORT=true; ONLY_SUBS=true ;;
    --stopped) STOPPED=true ;;
    --no-ueransim) NO_UERANSIM=true ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $a" ;;
  esac
done

load_config
# shellcheck source=free5gc.env
source "${F5_DIR}/free5gc.env"
declare -p F5_UE_POOLS &>/dev/null || die "F5_UE_POOLS not defined in free5gc/free5gc.env"
# the user's helm/kubectl (load_config points the helm cache to /opt, owned by root)
unset HELM_CACHE_HOME HELM_CONFIG_HOME HELM_DATA_HOME
KUBECTL="kubectl"
[[ $EUID -ne 0 ]] || KUBECTL="kubectl --kubeconfig ${KUBECONFIG_PATH:-/etc/rancher/k3s/k3s.yaml}"
k() { ${KUBECTL} "$@"; }
HELM="$(command -v helm || echo /usr/local/bin/helm)"
STATE="${F5_STATE_DIR:-${HOME}/.config/innovanetwork/free5gc}"
OUT="${GENERATED_DIR}/free5gc"
NS="${F5_NAMESPACE}"

# ---------------------------------------------------------------- validation
step "free5GC ${F5_VERSION} — validation"
is_true "${RAN_LINK_ENABLED}" || die "free5GC uses the fiber link: RAN_LINK_ENABLED=true in config.env"
(( ${#F5_UE_POOLS[@]} >= ${#SLICES[@]} )) || die "F5_UE_POOLS needs one pool per SLICES item (${#SLICES[@]})"
for v in F5_AMF_N2_IP F5_UPF_N3_IP F5_GNB_SIM_IP; do
  valid_ipv4 "${!v}" || die "invalid ${v}: ${!v}"
  ip_in_cidr "${!v}" "${RAN_LINK_CIDR}" || die "${v}=${!v} outside RAN_LINK_CIDR (${RAN_LINK_CIDR})"
  for o in AMF_N2_IP UPF_N3_IP GNB_SIM_IP; do
    [[ "${!v}" != "${!o}" ]] || die "${v}=${!v} is the same IP as Open5GS (${o}); use another one"
  done
done
for p in "${F5_UE_POOLS[@]}"; do
  valid_cidr "${p}" || die "invalid pool: ${p}"
  for s in "${SLICES[@]}"; do
    parse_slice "${s}"
    ! cidr_overlap "${p}" "${S_SUBNET}" || die "pool ${p} overlaps the Open5GS one (${S_SUBNET})"
  done
done
k get crd network-attachment-definitions.k8s.cni.cncf.io >/dev/null 2>&1 || die "Multus not found (run the root install.sh first)"
ok "config ok: AMF ${F5_AMF_N2_IP}, UPF ${F5_UPF_N3_IP}, simulated gNB ${F5_GNB_SIM_IP}, pools ${F5_UE_POOLS[*]}"
if ! ${DRY} && ! ${ONLY_SUBS} && ! grep -q '^gtp5g ' /proc/modules; then
  die "gtp5g module not loaded (the free5GC UPF needs it). Once, with sudo: sudo ./free5gc/setup-gtp5g.sh"
fi

# Variables for the generators (Python)
export F5_NAMESPACE F5_VERSION F5_REGISTRY F5_MONGO_IMAGE F5_MONGO_SIZE F5_AMF_N2_IP F5_UPF_N3_IP F5_GNB_SIM_IP
export F5_WEBUI_NODEPORT F5_NETWORK_NAME F5_UERANSIM_RELEASE F5_LOG_LEVEL
export K8S_NAMESPACE MCC MNC TAC DNS_SERVERS NETWORK_NAME RAN_LINK_IFACE RAN_LINK_CIDR RAN_LINK_MTU UE_COUNT UE_MSIN_START UE_KEY UE_OPC
F5_UE_POOLS_TXT=$(printf '%s\n' "${F5_UE_POOLS[@]}"); SLICES_TXT=$(printf '%s\n' "${SLICES[@]}")
SUBS_TXT=$(printf '%s\n' "${SUBSCRIBERS[@]+"${SUBSCRIBERS[@]}"}")
export F5_EXTRA_DNNS_ENV="$(printf '%s\n' "${F5_EXTRA_DNNS[@]}")"
export F5_UE_POOLS_ENV="${F5_UE_POOLS_TXT}" SLICES_ENV="${SLICES_TXT}" SUBSCRIBERS_ENV="${SUBS_TXT}"
export F5_WEBUI_URL="http://127.0.0.1:${F5_WEBUI_NODEPORT}"

sync_subs() {
  step "Subscribers (WebConsole)"
  local i
  for i in $(seq 1 60); do
    curl -s -o /dev/null --max-time 2 "${F5_WEBUI_URL}" && break; sleep 2
  done
  python3 "${F5_DIR}/lib/subscribers.py"
}
import_open5gs() {
  step "Importing the Open5GS SIMs (${K8S_NAMESPACE}) into free5GC"
  local m
  m=$(k -n "${K8S_NAMESPACE}" get pod -l app.kubernetes.io/name=mongodb -o name | head -1)
  [[ -n "${m}" ]] || die "Open5GS MongoDB not found (Open5GS must be up to export)"
  k -n "${K8S_NAMESPACE}" exec "${m}" -c mongodb -- mongosh --quiet open5gs --eval \
    'print(EJSON.stringify(db.subscribers.find({}, {imsi: 1, security: 1, slice: 1, _id: 0}).toArray(), {relaxed: true}))' \
    | python3 "${F5_DIR}/lib/subscribers.py" --from-open5gs
}
if ${ONLY_SUBS}; then sync_subs; ! ${IMPORT} || import_open5gs; exit 0; fi

# ---------------------------------------------------------------- certificates
# Own test PKI (free5GC requires the files even with the SBI over http). Kept out of git.
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

# ---------------------------------------------------------------- manifests
step "Generating manifests (${OUT})"
mkdir -p "${OUT}"
python3 "${F5_DIR}/lib/render.py" manifests >"${OUT}/free5gc.json"
python3 "${F5_DIR}/lib/render.py" ueransim >"${OUT}/ueransim-values.json"
make_certs
ok "manifests: $(python3 -c 'import json,sys;print(len(json.load(open(sys.argv[1]))["items"]))' "${OUT}/free5gc.json") objects; certificates in ${STATE}/cert"

if ${DRY}; then
  step "Server-side validation (dry-run; nothing is applied)"
  if k get ns "${NS}" >/dev/null 2>&1; then
    k apply --dry-run=server -f "${OUT}/free5gc.json" | sed 's/^/    /'
  else
    # the namespace does not exist yet: validate the namespace itself, and the rest only on the client
    k apply --dry-run=server -f <(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(json.dumps(d["items"][0]))' "${OUT}/free5gc.json") | sed 's/^/    /'
    k apply --dry-run=client -f "${OUT}/free5gc.json" | sed 's/^/    /'
  fi
  "${HELM}" template "${F5_UERANSIM_RELEASE}" "${CHARTS_DIR}/charts/ueransim-gnb" -n "${NS}" \
    -f "${OUT}/ueransim-values.json" >/dev/null && ok "UERANSIM values ok"
  exit 0
fi

step "Applying to namespace ${NS}"
k apply -f <(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(json.dumps(d["items"][0]))' "${OUT}/free5gc.json") >/dev/null
k -n "${NS}" create secret generic free5gc-cert --from-file="${STATE}/cert" --dry-run=client -o yaml \
  | k apply -f - >/dev/null
k apply --server-side --field-manager=innovanetwork --force-conflicts -f "${OUT}/free5gc.json" >/dev/null
ok "applied"

if ${STOPPED}; then
  k -n "${NS}" scale deploy --all --replicas=0 >/dev/null
  ok "free5GC installed and STOPPED (0 replicas): start it from the Control tab or with: kubectl -n ${NS} scale deploy --all --replicas=1"
  exit 0
fi

step "Starting in order"
for d in mongodb nrf udr udm ausf nssf pcf chf nef webui upf smf amf; do
  if k -n "${NS}" rollout status "deploy/${d}" --timeout=300s >/dev/null 2>&1; then
    ok "${d}"
  else
    k -n "${NS}" get pods -l "nf=${d}" | sed 's/^/    /'
    die "${d} did not become ready (kubectl -n ${NS} logs deploy/${d})"
  fi
done
sync_subs

if ! ${NO_UERANSIM} && is_true "${F5_DEPLOY_UERANSIM}"; then
  step "free5GC UERANSIM (gNB ${F5_GNB_SIM_IP} -> AMF ${F5_AMF_N2_IP})"
  "${HELM}" upgrade --install "${F5_UERANSIM_RELEASE}" "${CHARTS_DIR}/charts/ueransim-gnb" -n "${NS}" \
    -f "${OUT}/ueransim-values.json" --post-renderer "${PROJECT_DIR}/helm/postrender/drop-gnb-hpa.sh" \
    --wait --timeout 10m >/dev/null || die "free5GC UERANSIM failed (kubectl -n ${NS} get pods)"
  # helm does not touch replicas someone set to 0 (core stopped): bring back the gNB, then the UEs.
  # Restart both: the UERANSIM gNB does not reconnect by itself if the AMF was restarted.
  for d in "${F5_UERANSIM_RELEASE}" "${F5_UERANSIM_RELEASE}-ues"; do
    k -n "${NS}" scale deploy "${d}" --replicas=1 >/dev/null 2>&1 || continue
    k -n "${NS}" rollout restart deploy "${d}" >/dev/null
    k -n "${NS}" rollout status deploy "${d}" --timeout=180s >/dev/null || die "${d} did not come up"
  done
  ok "UERANSIM up (test: ./free5gc/test.sh)"
fi

step "Done"
info "WebConsole: http://<core machine IP>:${F5_WEBUI_NODEPORT}  (user admin; change the default password)"
info "OCUDU gNB: in the .yml, cu_cp.amf.addr = ${F5_AMF_N2_IP}"
info "Pods: kubectl -n ${NS} get pods"
