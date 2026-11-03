#!/usr/bin/env bash
# =============================================================================
#  free5gc/setup-gtp5g.sh — gtp5g kernel module (required by the free5GC UPF).
#  Runs ONCE, with sudo, on the core machine. Installs through DKMS: the module is
#  rebuilt by itself when the Ubuntu kernel is updated. Does not affect
#  Open5GS (its UPF uses TUN, not gtp5g).
#
#  Usage: sudo ./free5gc/setup-gtp5g.sh          (version from free5gc.env)
#        sudo ./free5gc/setup-gtp5g.sh --remove
# =============================================================================
set -Eeuo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=free5gc.env
source "${DIR}/free5gc.env"
VER="${F5_GTP5G_VERSION#v}"
[[ $EUID -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }

if [[ "${1:-}" == "--remove" ]]; then
  modprobe -r gtp5g 2>/dev/null || true
  dkms remove "gtp5g/${VER}" --all 2>/dev/null || true
  rm -rf "/usr/src/gtp5g-${VER}" /etc/modules-load.d/gtp5g.conf
  echo "gtp5g removed"; exit 0
fi

command -v dkms >/dev/null || { apt-get update -qq; DEBIAN_FRONTEND=noninteractive apt-get install -y -qq dkms; }
dpkg -s "linux-headers-$(uname -r)" >/dev/null 2>&1 || apt-get install -y -qq "linux-headers-$(uname -r)"

# another version installed earlier (the UPF requires a version range): remove it from DKMS and the kernel
for old in $(dkms status gtp5g 2>/dev/null | sed -n 's#^gtp5g/\([^,]*\),.*#\1#p' | sort -u); do
  [[ "${old}" == "${VER}" ]] && continue
  echo "removing gtp5g ${old}"
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
echo gtp5g > /etc/modules-load.d/gtp5g.conf      # also loads on the next boots
if [[ "$(cat /sys/module/gtp5g/version 2>/dev/null)" != "${VER}" ]]; then
  modprobe -r gtp5g 2>/dev/null || { echo "gtp5g in use (free5GC UPF running?): stop the UPF and run again" >&2; exit 1; }
fi
modprobe gtp5g
echo "ok: $(modinfo gtp5g | grep -E '^version') loaded ($(uname -r)); DKMS: $(dkms status gtp5g | head -1)"
