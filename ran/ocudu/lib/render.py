#!/usr/bin/env python3
# =============================================================================
#  ran/ocudu/lib/render.py — manifests of the OCUDU gNB on Kubernetes.
#
#  Reads the ocudu.env variables (from the environment) and writes to stdout: Namespace,
#  Deployment "ocudu-gnb" and the component descriptor. No dependencies.
#
#  The pod runs the SAME command as the native ocudu-gnb@ service:
#    taskset -c <CPUs> gnb -c <folder>/<yml>.yml [-c <folder>/metricas.yml]
#  with the host network and hardware (hostNetwork + privileged), the .yml files read from
#  the host folder and the log in the host /tmp. Stop = SIGINT to the gNB (like Ctrl+C).
# =============================================================================
import json
import os
import sys

E = os.environ


def env(k, d=None):
    v = E.get(k, d)
    if v is None:
        sys.exit("render.py: missing %s" % k)
    return v


NS = env("OCUDU_NAMESPACE")
NODE = env("OCUDU_NODE")
CFG_DIR = env("OCUDU_CONFIG_DIR")
LOG_DIR = env("OCUDU_LOG_DIR")
IMAGE = "%s:%s" % (env("OCUDU_IMAGE"), env("OCUDU_IMAGE_TAG"))
LABELS = {"app.kubernetes.io/name": "ocudu-gnb", "app.kubernetes.io/part-of": "innovanetwork"}

# Container script: checks the .yml, refuses if there is already a gnb on the host (the
# native service, for example) and forwards the Kubernetes TERM as INT to the gNB.
RUN = r'''
set -u
# After a node reboot the gNB does NOT start by itself (the GPS can take up to ~30 min and the RU needs the
# right clock): it only starts if the last "gnb.sh start" (GNB_START_REQUEST, epoch) is newer than the node boot.
# /proc/stat is not isolated per container: btime is the host boot time.
btime=$(awk '/^btime/{print $2}' /proc/stat)
if [ "${GNB_START_REQUEST:-0}" -lt "$btime" ]; then
  echo "ocudu-gnb: the node rebooted after the last start request ($(date -d @"${GNB_START_REQUEST:-0}" '+%F %T' 2>/dev/null))."
  echo "ocudu-gnb: the gNB does NOT start by itself. Check the GPS (ts2phc 's2') and the RU, then run: ./ran/ocudu/gnb.sh start"
  trap 'exit 0' TERM INT
  while :; do sleep 3600 & wait $!; done
fi
cfg="/configs/${GNB_CONFIG}.yml"
[ -r "$cfg" ] || { echo "ocudu-gnb: $cfg not found"; exit 1; }
extra=""
if [ -n "${GNB_EXTRA_CONFIG}" ] && [ -r "/configs/${GNB_EXTRA_CONFIG}" ]; then
  extra="-c /configs/${GNB_EXTRA_CONFIG}"
fi
for c in /proc/[0-9]*/comm; do
  if [ "$(cat "$c" 2>/dev/null)" = gnb ]; then
    echo "ocudu-gnb: a gnb is already running on the host (ocudu-gnb@ service or a terminal): stop it first"
    exit 1
  fi
done
# .yml log (log.filename) in the host /tmp: if it has another owner (e.g. uid 1001 of the image), root
# cannot reopen it because of fs.protected_regular; remove it only in that case
logf=$(awk '/^log:/{l=1;next} l&&/^[^ #]/{l=0} l&&/filename:/{print $2; exit}' "$cfg")
if [ -n "$logf" ] && [ -e "$logf" ] && [ "$(stat -c %u "$logf")" != 0 ]; then
  echo "ocudu-gnb: removing $logf (owner $(stat -c %u "$logf"), not root)"; rm -f "$logf"
fi
command -v taskset >/dev/null || { echo "ocudu-gnb: the image has no taskset (util-linux)"; exit 1; }
echo "ocudu-gnb: taskset -c ${GNB_CPUS} gnb -c $cfg $extra"
taskset -c "${GNB_CPUS}" gnb -c "$cfg" $extra &
pid=$!
# Common (non-realtime) threads that the gNB does not pin inherit all GNB_CPUS. With isolcpus there is no
# balancing between isolated CPUs, and without a realtime limit (sched_rt_runtime_us=-1) one of them can land on
# a CPU 100 % busy with a realtime thread and never run (e.g. the gNB log stopped at 8 KB). The watcher moves
# those threads to GNB_AUX_CPUS (CPUs without gNB work). It does not touch the main thread or the realtime ones.
if [ -n "${GNB_AUX_CPUS:-}" ]; then
  (
    full=$(taskset -cp "$pid" 2>/dev/null | sed 's/.*: //')
    for _ in $(seq 1 60); do
      for t in /proc/"$pid"/task/*; do
        tid=${t##*/}; [ "$tid" = "$pid" ] && continue
        pol=$(sed 's/.*) //' "$t/stat" 2>/dev/null | awk '{print $39}'); [ "$pol" = 0 ] || continue
        aff=$(taskset -cp "$tid" 2>/dev/null | sed 's/.*: //')
        if [ -n "$full" ] && [ "$aff" = "$full" ] && taskset -cp "${GNB_AUX_CPUS}" "$tid" >/dev/null 2>&1; then
          echo "ocudu-gnb: thread $(cat "$t/comm" 2>/dev/null) ($tid) -> CPUs ${GNB_AUX_CPUS}"
        fi
      done
      sleep 2
    done
  ) &
fi
trap 'echo "ocudu-gnb: stopping (SIGINT)"; kill -INT $pid' TERM INT
wait $pid; rc=$?
trap - TERM INT
wait $pid 2>/dev/null; rc2=$?
[ $rc2 -ne 127 ] && rc=$rc2
echo "ocudu-gnb: gnb exited (code $rc)"
exit $rc
'''

namespace = {
    "apiVersion": "v1", "kind": "Namespace",
    "metadata": {"name": NS, "labels": {"innovanetwork/component": "ocudu"}},
}

deployment = {
    "apiVersion": "apps/v1", "kind": "Deployment",
    "metadata": {"name": "ocudu-gnb", "namespace": NS, "labels": LABELS},
    "spec": {
        "replicas": int(env("OCUDU_REPLICAS", "0")),  # 0 = stopped; start = 1 (gnb.sh or dashboard)
        "strategy": {"type": "Recreate"},    # never two gNBs at the same time
        "selector": {"matchLabels": {"app.kubernetes.io/name": "ocudu-gnb"}},
        "template": {
            "metadata": {"labels": LABELS},
            "spec": {
                "nodeSelector": {"kubernetes.io/hostname": NODE},
                "tolerations": [{"key": "innovanetwork/ran", "operator": "Exists", "effect": "NoSchedule"}],
                "hostNetwork": True,         # N2/N3 on 10.10.0.1, metrics :8001, like on the host
                "hostPID": True,             # to see a native gnb and refuse
                "dnsPolicy": "ClusterFirstWithHostNet",
                "terminationGracePeriodSeconds": 30,
                "containers": [{
                    "name": "gnb",
                    "image": IMAGE,
                    "imagePullPolicy": "Never",   # local image, imported into the k3s containerd
                    # privileged + root: DPDK/vfio, hugepages, /proc/self/pagemap, RT. The official image
                    # runs as USER 1001; the native ocudu-gnb@ service runs as root (same here).
                    "securityContext": {"privileged": True, "runAsUser": 0, "runAsGroup": 0},
                    "command": ["/bin/bash", "-c", RUN],
                    # Kubernetes limits the pod hugepages to what it requests (no request = 0 and DPDK
                    # fails with "Cannot init memory"). Memory: request only, no limit.
                    "resources": {
                        "requests": {"hugepages-1Gi": env("OCUDU_HUGEPAGES_1G"), "memory": env("OCUDU_MEMORY_REQUEST")},
                        "limits": {"hugepages-1Gi": env("OCUDU_HUGEPAGES_1G")},
                    },
                    "env": [
                        {"name": "GNB_CONFIG", "value": env("OCUDU_GNB_CONFIG", env("OCUDU_DEFAULT_CONFIG"))},
                        {"name": "GNB_EXTRA_CONFIG", "value": env("OCUDU_EXTRA_CONFIG", "")},
                        {"name": "GNB_CPUS", "value": env("OCUDU_CPUS")},
                        {"name": "GNB_AUX_CPUS", "value": env("OCUDU_AUX_CPUS", "")},
                        {"name": "GNB_START_REQUEST", "value": env("OCUDU_START_REQUEST", "0")},
                    ],
                    "volumeMounts": [
                        {"name": "configs", "mountPath": "/configs", "readOnly": True},
                        {"name": "hugepages", "mountPath": "/dev/hugepages"},
                        {"name": "logs", "mountPath": LOG_DIR},
                    ],
                }],
                "volumes": [
                    {"name": "configs", "hostPath": {"path": CFG_DIR, "type": "Directory"}},
                    {"name": "hugepages", "hostPath": {"path": "/dev/hugepages", "type": "Directory"}},
                    {"name": "logs", "hostPath": {"path": LOG_DIR, "type": "Directory"}},
                ],
            },
        },
    },
}

# Component descriptor (v3 contract): tools like the dashboard discover what is installed.
descriptor = {
    "apiVersion": "v1", "kind": "ConfigMap",
    "metadata": {"name": "innovanetwork-component", "namespace": NS,
                 "labels": {"innovanetwork/component": "ocudu"}},
    "data": {
        "kind": "ran",
        "type": "ocudu",
        "name": "gNB OCUDU",
        "deployment": "ocudu-gnb",
        "node": NODE,
        "config_dir": CFG_DIR,
        "config_env": "GNB_CONFIG",
        "default_config": env("OCUDU_DEFAULT_CONFIG"),
        "image": IMAGE,
    },
}

print(json.dumps({"apiVersion": "v1", "kind": "List", "items": [namespace, descriptor, deployment]},
                 indent=1, ensure_ascii=False))
