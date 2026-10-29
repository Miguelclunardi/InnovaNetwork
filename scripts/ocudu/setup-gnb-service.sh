#!/usr/bin/env bash
# =============================================================================
#  scripts/ocudu/setup-gnb-service.sh — roda UMA vez, com sudo, NO HOST DO gNB.
#
#  Cria o serviço ocudu-gnb@<arquivo>.service (gNB OCUDU com <arquivo>.yml da
#  pasta configs/) e uma regra do polkit que deixa SÓ o usuário do gNB iniciar,
#  parar e reiniciar esse serviço sem senha — nada de sudo sem senha. O painel
#  (aba Controle) usa isso pelo agente gnb-ctl da máquina do core.
#
#  O serviço roda o binário e os .yml direto da pasta do OCUDU do usuário
#  (escolha do usuário: mais prático; quem controla esse usuário controla o gNB).
#  Não prepara a máquina (interface, DPDK, XDP, PTP): isso continua manual.
#
#  Uso (no host do gNB):
#    sudo bash setup-gnb-service.sh [--user innovaserver] [--dir /home/innovaserver/ocudu] [--cpus 0-17]
#                                   [--extra metricas.yml]   (2º -c, se existir em configs/; "" = nenhum)
#    sudo bash setup-gnb-service.sh --remove
#  A partir da máquina do core:
#    scp scripts/ocudu/setup-gnb-service.sh innovaserver@10.10.0.1:/tmp/
#    ssh -t innovaserver@10.10.0.1 sudo bash /tmp/setup-gnb-service.sh
# =============================================================================
set -Eeuo pipefail

USER_NAME="${SUDO_USER:-innovaserver}"
DIR=""
CPUS="0-17"
EXTRA="metricas.yml"   # métricas JSON + remote_control (porta 8001), como no "-c ../../../configs/metricas.yml"
REMOVE=false
UNIT=/etc/systemd/system/ocudu-gnb@.service
RULE=/etc/polkit-1/rules.d/50-ocudu-gnb.rules

while (( $# )); do
  case "$1" in
    --user) USER_NAME="$2"; shift 2 ;;
    --dir) DIR="$2"; shift 2 ;;
    --cpus) CPUS="$2"; shift 2 ;;
    --extra) EXTRA="$2"; shift 2 ;;
    --remove) REMOVE=true; shift ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
done
[[ $EUID -eq 0 ]] || { echo "rode com sudo" >&2; exit 1; }

if ${REMOVE}; then
  systemctl stop 'ocudu-gnb@*.service' 2>/dev/null || true
  rm -f "${UNIT}" "${RULE}"
  systemctl daemon-reload
  echo "removido: ${UNIT} e ${RULE}"
  exit 0
fi

id "${USER_NAME}" &>/dev/null || { echo "usuário inexistente: ${USER_NAME}" >&2; exit 1; }
[[ -n "${DIR}" ]] || DIR="$(getent passwd "${USER_NAME}" | cut -d: -f6)/ocudu"
[[ "${USER_NAME}" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "usuário inválido" >&2; exit 1; }
[[ "${DIR}" =~ ^/[A-Za-z0-9/_.-]+$ ]] || { echo "pasta inválida: ${DIR}" >&2; exit 1; }
[[ "${CPUS}" =~ ^[0-9,-]+$ ]] || { echo "--cpus inválido: ${CPUS}" >&2; exit 1; }
[[ -z "${EXTRA}" || "${EXTRA}" =~ ^[A-Za-z0-9_.-]+\.yml$ ]] || { echo "--extra inválido: ${EXTRA}" >&2; exit 1; }
# 2º arquivo: entra no comando só se existir na hora de iniciar (o gNB aceita vários -c)
if [[ -n "${EXTRA}" ]]; then
  X="${DIR}/configs/${EXTRA}"
  EXEC="/bin/sh -c 'C=; if [ -r ${X} ]; then C=\"-c ${X}\"; fi; exec /usr/bin/taskset -c ${CPUS} ${DIR}/build/apps/gnb/gnb -c ${DIR}/configs/%i.yml \$\$C'"
else
  EXEC="/usr/bin/taskset -c ${CPUS} ${DIR}/build/apps/gnb/gnb -c ${DIR}/configs/%i.yml"
fi
[[ -x "${DIR}/build/apps/gnb/gnb" ]] || { echo "não achei ${DIR}/build/apps/gnb/gnb" >&2; exit 1; }
[[ -d "${DIR}/configs" ]] || { echo "não achei ${DIR}/configs" >&2; exit 1; }

cat >"${UNIT}" <<EOF
# Gerado por open5GK3S/scripts/ocudu/setup-gnb-service.sh
# gNB OCUDU com ${DIR}/configs/<instância>.yml — ex.: systemctl start ocudu-gnb@gnb_split_open5gs
[Unit]
Description=gNB OCUDU com %i.yml (painel open5GK3S)
After=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory=${DIR}/build/apps/gnb
# um gNB por vez: recusa se já houver um gnb (aberto no terminal, por exemplo)
ExecStartPre=/bin/sh -c 'if pgrep -x gnb >/dev/null; then echo "ja existe um gnb rodando fora deste servico: pare-o antes"; exit 1; fi'
ExecStartPre=/usr/bin/test -r ${DIR}/configs/%i.yml
ExecStart=${EXEC}
# Ctrl+C, como no terminal: o gNB fecha a célula e a RU direito
KillSignal=SIGINT
TimeoutStopSec=30
LimitMEMLOCK=infinity
LimitNOFILE=65536
Restart=no
EOF

cat >"${RULE}" <<EOF
// Gerado por open5GK3S/scripts/ocudu/setup-gnb-service.sh
// ${USER_NAME} pode iniciar/parar/reiniciar SÓ as units ocudu-gnb@*.service (painel open5GK3S).
polkit.addRule(function (action, subject) {
  if (action.id == "org.freedesktop.systemd1.manage-units" && subject.user == "${USER_NAME}") {
    var unit = action.lookup("unit") || "";
    var verb = action.lookup("verb") || "";
    if (/^ocudu-gnb@[A-Za-z0-9_.-]+\.service\$/.test(unit) &&
        ["start", "stop", "restart", "reset-failed"].indexOf(verb) >= 0) {
      return polkit.Result.YES;
    }
  }
});
EOF
chmod 0644 "${UNIT}" "${RULE}"
systemctl daemon-reload
systemctl try-restart polkit.service 2>/dev/null || true

echo "ok: ${UNIT}"
echo "ok: ${RULE} (usuário ${USER_NAME})"
echo
echo "Teste (como ${USER_NAME}, sem sudo; não inicia nada, só confere a permissão):"
echo "  systemctl stop ocudu-gnb@teste.service && echo permissao-ok"
