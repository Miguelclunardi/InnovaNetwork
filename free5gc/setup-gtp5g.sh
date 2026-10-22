#!/usr/bin/env bash
# =============================================================================
#  free5gc/setup-gtp5g.sh — módulo do kernel gtp5g (exigido pelo UPF do free5GC).
#  Roda UMA vez, com sudo, na máquina do core. Instala via DKMS: o módulo é
#  recompilado sozinho quando o kernel do Ubuntu for atualizado. Não afeta o
#  Open5GS (o UPF dele usa TUN, não gtp5g).
#
#  Uso: sudo ./free5gc/setup-gtp5g.sh            (versão de free5gc.env)
#       sudo ./free5gc/setup-gtp5g.sh --remove
# =============================================================================
set -Eeuo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=free5gc.env
source "${DIR}/free5gc.env"
VER="${F5_GTP5G_VERSION#v}"
[[ $EUID -eq 0 ]] || { echo "rode com sudo" >&2; exit 1; }

if [[ "${1:-}" == "--remove" ]]; then
  modprobe -r gtp5g 2>/dev/null || true
  dkms remove "gtp5g/${VER}" --all 2>/dev/null || true
  rm -rf "/usr/src/gtp5g-${VER}" /etc/modules-load.d/gtp5g.conf
  echo "gtp5g removido"; exit 0
fi

command -v dkms >/dev/null || { apt-get update -qq; DEBIAN_FRONTEND=noninteractive apt-get install -y -qq dkms; }
dpkg -s "linux-headers-$(uname -r)" >/dev/null 2>&1 || apt-get install -y -qq "linux-headers-$(uname -r)"

# outra versão instalada antes (o UPF exige uma faixa de versões): sai do DKMS e do kernel
for old in $(dkms status gtp5g 2>/dev/null | sed -n 's#^gtp5g/\([^,]*\),.*#\1#p' | sort -u); do
  [[ "${old}" == "${VER}" ]] && continue
  echo "removendo gtp5g ${old}"
  modprobe -r gtp5g 2>/dev/null || true
  dkms remove "gtp5g/${old}" --all || true
  rm -rf "/usr/src/gtp5g-${old}"
done
if ! dkms status "gtp5g/${VER}" 2>/dev/null | grep -q installed; then
  rm -rf "/usr/src/gtp5g-${VER}"
  mkdir -p "/usr/src/gtp5g-${VER}"
  curl -fsSL "https://codeload.github.com/free5gc/gtp5g/tar.gz/refs/tags/v${VER}" \
    | tar xz -C "/usr/src/gtp5g-${VER}" --strip-components=1
  dkms add "gtp5g/${VER}" 2>/dev/null || true
  dkms build "gtp5g/${VER}"
  dkms install "gtp5g/${VER}" --force
fi
echo gtp5g > /etc/modules-load.d/gtp5g.conf      # carrega também nos próximos boots
if [[ "$(cat /sys/module/gtp5g/version 2>/dev/null)" != "${VER}" ]]; then
  modprobe -r gtp5g 2>/dev/null || { echo "gtp5g em uso (UPF do free5GC rodando?): pare o UPF e rode de novo" >&2; exit 1; }
fi
modprobe gtp5g
echo "ok: $(modinfo gtp5g | grep -E '^version') carregado ($(uname -r)); DKMS: $(dkms status gtp5g | head -1)"
