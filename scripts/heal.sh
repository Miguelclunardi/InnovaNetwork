#!/usr/bin/env bash
# =============================================================================
#  scripts/heal.sh — verifica e recupera o core depois de reboot/restart do k3s.
#
#  Espera o k3s e os pods ficarem prontos, confere se os UEs estão registrados
#  e pingando o UPF e, se não estiverem, reinicia em ordem os UEs e depois
#  UPF -> SMF -> gNB -> UEs (refaz a associação PFCP/N4 e o NG Setup).
#
#  Uso:  ./scripts/heal.sh          (usa sudo automaticamente se precisar)
#        ./scripts/heal.sh --boot   (modo da unit open5gs-k3s-heal: espera até 15 min)
#  Código de saída: 0 = plano de usuário OK, 1 = não recuperou.
# =============================================================================
set -Eeuo pipefail
source "$(dirname "$(readlink -f "$0")")/lib/common.sh"

BOOT=false
for a in "$@"; do
  case "$a" in
    --boot) BOOT=true ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "opção desconhecida: $a" ;;
  esac
done

load_config
${BOOT} || [[ -r "${KUBECONFIG_PATH}" ]] || exec sudo --preserve-env=CONFIG "$0" "$@"
validate_config

wait_s=120; ${BOOT} && wait_s=900
step "Aguardando o k3s"
t=0
until k3s_ready; do (( t += 5 )); (( t < wait_s )) || die "k3s não respondeu em ${wait_s}s"; sleep 5; done
ok "API do k3s pronta"

step "Aguardando os pods de ${K8S_NAMESPACE}"
kc get ns "${K8S_NAMESPACE}" &>/dev/null || { info "namespace ${K8S_NAMESPACE} não existe; nada a fazer"; exit 0; }
# No boot os pods antigos ainda aparecem por alguns segundos antes de serem recriados
${BOOT} && sleep 30
if kc -n "${K8S_NAMESPACE}" wait --for=condition=Ready pod --all --timeout="${wait_s}s" >/dev/null 2>&1; then
  ok "todos os pods prontos"
else
  warn "nem todos os pods ficaram prontos em ${wait_s}s; seguindo mesmo assim"
fi

step "Plano de usuário (registro + ping ao UPF)"
if ensure_user_plane; then
  exit 0
fi
err "não recuperou sozinho — rode ./test.sh -v e veja docs/troubleshooting.md"
exit 1
