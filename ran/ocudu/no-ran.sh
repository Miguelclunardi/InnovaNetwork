#!/usr/bin/env bash
# =============================================================================
#  ran/ocudu/no-ran.sh — runs ON THE gNB MACHINE (innovaserver), with sudo.
#
#  The core machine copies this script, ocudu.env and (only on "prepare") join.env to
#  ~/innovanetwork-ran/ on the node:   ./ran/ocudu/install.sh copy | prepare
#
#  Usage (on the node):
#    sudo ~/innovanetwork-ran/no-ran.sh image     builds the gNB image from the source in OCUDU_SRC_DIR
#                                                 (current commit, through git archive) and, if the node
#                                                 is already in the cluster, imports it into the k3s containerd
#    sudo ~/innovanetwork-ran/no-ran.sh import    only imports an already built image into k3s
#    sudo ~/innovanetwork-ran/no-ran.sh join      joins the k3s of the core machine as the RAN node (needs
#                                                 the join.env of "prepare"; the token is deleted at the end)
#    sudo ~/innovanetwork-ran/no-ran.sh leave     leaves the cluster (removes the k3s agent)
#         ~/innovanetwork-ran/no-ran.sh status    shows what is installed (no sudo)
#
#  Does not touch: PTP, VF/DPDK, XDP, hugepages, isolated CPUs, netplan, the ocudu-gnb@ service.
# =============================================================================
set -Eeuo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=ocudu.env
source "${DIR}/ocudu.env"
[[ -f "${DIR}/join.env" ]] && source "${DIR}/join.env"

say()  { echo "==> $*"; }
info() { echo "    $*"; }
die()  { echo "[error] $*" >&2; exit 1; }
need_root() { [[ $EUID -eq 0 ]] || die "run with sudo: sudo $0 $1"; }
OWNER="${SUDO_USER:-$(stat -c %U "${OCUDU_SRC_DIR}")}"
ROUTE_UNIT="innovanetwork-k3s-route.service"

image_tag() {
  if [[ -n "${OCUDU_IMAGE_TAG}" ]]; then echo "${OCUDU_IMAGE_TAG}"; return; fi
  sudo -u "${OWNER}" git -C "${OCUDU_SRC_DIR}" rev-parse --short=7 HEAD
}

do_import() {
  local ref="${OCUDU_IMAGE}:$(image_tag)"
  command -v k3s >/dev/null || { info "k3s not installed yet: import later with '$0 import'"; return 0; }
  say "importing ${ref} into the k3s containerd"
  docker image inspect "${ref}" >/dev/null 2>&1 || die "image ${ref} does not exist: run '$0 image'"
  docker save "${ref}" | k3s ctr -n k8s.io images import -
  k3s ctr -n k8s.io images ls -q | grep -F "${ref}" | sed 's/^/    /'
}

do_image() {
  need_root image
  command -v docker >/dev/null || die "docker not installed"
  local tag ref ctx
  tag="$(image_tag)"; ref="${OCUDU_IMAGE}:${tag}"
  ctx="/var/tmp/innovanetwork-ocudu-src"
  say "image ${ref} (OCUDU in ${OCUDU_SRC_DIR}, commit $(sudo -u "${OWNER}" git -C "${OCUDU_SRC_DIR}" rev-parse --short=10 HEAD))"
  if sudo -u "${OWNER}" git -C "${OCUDU_SRC_DIR}" status --porcelain --untracked-files=no | grep -qv '^.. configs/\|^.. docker/'; then
    info "[warn] there are local changes in the source outside configs/ and docker/: the image uses the commit, without them"
  fi
  # Clean context = only the commit (without the ~2 GB native build/, which would break the image cmake)
  rm -rf "${ctx}"; mkdir -p "${ctx}"
  sudo -u "${OWNER}" git -C "${OCUDU_SRC_DIR}" archive HEAD | tar x -C "${ctx}"
  if [[ "${OCUDU_IMAGE_ROHC:-false}" != "true" ]]; then
    # No ROHC (same as the native gnb): the Dockerfile copies /opt/rohc, so we create the empty folder
    # instead of downloading and building the library. Only the temporary copy changes; OCUDU_SRC_DIR does not.
    info "no ROHC (OCUDU_IMAGE_ROHC=false): build_rohc.sh replaced in the temporary copy"
    printf '#!/bin/sh\nmkdir -p /opt/rohc/lib /opt/rohc/include\necho "ROHC disabled (InnovaNetwork)"\n' \
      > "${ctx}/docker/scripts/build_rohc.sh"
    chmod 755 "${ctx}/docker/scripts/build_rohc.sh"
  fi
  say "building (takes ~20-40 min; uses ${OCUDU_BUILD_JOBS} jobs on the non-isolated CPUs)"
  docker build -f "${ctx}/docker/Dockerfile" --target runtime-dpdk \
    --build-arg COMPONENT=gnb \
    --build-arg OS="${OCUDU_IMAGE_OS}" --build-arg OS_VERSION="${OCUDU_IMAGE_OS_VERSION}" \
    --build-arg MARCH="${OCUDU_IMAGE_MARCH}" --build-arg NUM_JOBS="${OCUDU_BUILD_JOBS}" \
    --label "innovanetwork.ocudu.commit=$(sudo -u "${OWNER}" git -C "${OCUDU_SRC_DIR}" rev-parse HEAD)" \
    -t "${ref}" "${ctx}"
  rm -rf "${ctx}"
  docker run --rm --entrypoint /bin/bash "${ref}" -c 'command -v gnb taskset bash' | sed 's/^/    has: /'
  do_import
}

do_join() {
  need_root join
  [[ -n "${K3S_URL:-}" && -n "${K3S_TOKEN:-}" && -n "${K3S_VERSION:-}" && -n "${STABLE_IP:-}" ]] \
    || die "join.env is missing: on the core machine, run 'sudo ./ran/ocudu/install.sh prepare'"
  ip -br addr show "${OCUDU_NODE_IFACE}" | grep -q "${OCUDU_NODE_IP}/" \
    || die "${OCUDU_NODE_IFACE} does not have ${OCUDU_NODE_IP}"

  # Known problems (docs/troubleshooting.md, section 6):
  # 1) another Kubernetes on the machine (e.g. MicroK8s) holds the kubelet ports and k3s does not start
  local busy
  busy="$(ss -ltnpH '( sport = :10250 or sport = :10248 or sport = :6443 )' 2>/dev/null | grep -v '"k3s' || true)"
  if [[ -n "${busy}" ]]; then
    echo "${busy}" | sed 's/^/    /'
    die "another Kubernetes is using the kubelet ports (10250/10248). MicroK8s? 'sudo microk8s stop' (deletes nothing; comes back with 'sudo microk8s start')"
  fi
  # 2) leftovers of a failed attempt: old certificates make the server refuse the node
  if [[ -d /var/lib/rancher/k3s/agent ]] && ! systemctl is-active -q k3s-agent; then
    say "cleaning up leftovers of an earlier attempt (/var/lib/rancher/k3s/agent)"
    systemctl stop k3s-agent 2>/dev/null || true
    rm -rf /var/lib/rancher/k3s/agent
  fi

  say "route to the k3s server (${STABLE_IP} via ${OCUDU_SERVER_VIA}) — unit ${ROUTE_UNIT}"
  cat > "/etc/systemd/system/${ROUTE_UNIT}" <<EOF
# InnovaNetwork: route to the k3s server (core machine) over the fiber. Generated by ran/ocudu/no-ran.sh
[Unit]
Description=InnovaNetwork: route ${STABLE_IP} via ${OCUDU_SERVER_VIA} (k3s)
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
  ping -c1 -W2 "${STABLE_IP}" >/dev/null || die "no answer from ${STABLE_IP} over the fiber"
  info "ok: ${STABLE_IP} answers"

  if ufw status 2>/dev/null | grep -q "Status: active"; then
    say "UFW: opening the cluster (only from the core machine and the k3s networks)"
    ufw allow from "${OCUDU_SERVER_VIA}" comment 'InnovaNetwork k3s' >/dev/null
    ufw allow from "${STABLE_IP}" comment 'InnovaNetwork k3s' >/dev/null
    ufw allow from 10.42.0.0/16 comment 'InnovaNetwork k3s pods' >/dev/null
    ufw allow from 10.43.0.0/16 comment 'InnovaNetwork k3s services' >/dev/null
  fi

  say "k3s agent configuration"
  mkdir -p /etc/rancher/k3s
  cat > /etc/rancher/k3s/config.yaml <<EOF
# Generated by InnovaNetwork ran/ocudu/no-ran.sh — RAN node
node-name: "${OCUDU_NODE}"
node-ip: "${OCUDU_NODE_IP}"
flannel-iface: "${OCUDU_NODE_IFACE}"
node-label:
  - "innovanetwork/role=ran"
node-taint:
  - "innovanetwork/ran=true:NoSchedule"
EOF
  say "installing k3s ${K3S_VERSION} (agent) and joining ${K3S_URL}"
  curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="${K3S_VERSION}" K3S_URL="${K3S_URL}" \
    K3S_TOKEN="${K3S_TOKEN}" sh -s - agent
  rm -f "${DIR}/join.env"
  info "token deleted (${DIR}/join.env)"
  systemctl is-active k3s-agent | sed 's/^/    k3s-agent: /'
  if docker image inspect "${OCUDU_IMAGE}:$(image_tag)" >/dev/null 2>&1; then do_import; fi
  say "done. On the core machine: kubectl get nodes"
}

do_leave() {
  need_root leave
  [[ -x /usr/local/bin/k3s-agent-uninstall.sh ]] && /usr/local/bin/k3s-agent-uninstall.sh
  systemctl disable --now "${ROUTE_UNIT}" 2>/dev/null || true
  rm -f "/etc/systemd/system/${ROUTE_UNIT}"; systemctl daemon-reload
  info "k3s agent removed. On the core machine: kubectl delete node ${OCUDU_NODE}"
  info "(the 'InnovaNetwork k3s' UFW rules stay; remove them with 'sudo ufw status numbered' if you want)"
}

do_state() {
  echo "k3s-agent:  $(systemctl is-active k3s-agent 2>/dev/null || true)"
  echo "route:      $(ip route show "${STABLE_IP:-10.254.254.1}" 2>/dev/null || true)"
  echo "join.env:   $([[ -f "${DIR}/join.env" ]] && echo present || echo absent)"
  echo "OCUDU:      $(git -C "${OCUDU_SRC_DIR}" rev-parse --short=7 HEAD 2>/dev/null)"
  echo "native gnb: $(systemctl list-units --no-legend --state=active 'ocudu-gnb@*' | awk '{print $1}' | tr '\n' ' ')"
}

case "${1:-}" in
  image)     do_image ;;
  import)    need_root import; do_import ;;
  join)      do_join ;;
  leave)     do_leave ;;
  status)    do_state ;;
  *) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
