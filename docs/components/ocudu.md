# OCUDU — real gNB on Kubernetes

The **OCUDU** gNB (CU + DU in the same process, O-RAN split 7.2, DPDK) runs as the `ocudu-gnb` pod on the **RAN
node**, a machine that joins the k3s cluster as an agent, dedicated to the radio.

> **Depends on your setup.** InnovaNetwork moves to Kubernetes a gNB that **already works** on the machine. The
> host preparation (kernel, isolated CPUs, hugepages, VF/DPDK, PTP/GNSS) and the gNB `.yml` files belong to your
> setup. Reference: [hardware/e810-liteon.md](../hardware/e810-liteon.md).

- [1. How it works](#1-how-it-works)
- [2. Files](#2-files)
- [3. Configuration (`ocudu.env`)](#3-configuration-ocuduenv)
- [4. The image](#4-the-image)
- [5. The RAN node](#5-the-ran-node)
- [6. The pod](#6-the-pod)
- [7. One `.yml` per core](#7-one-yml-per-core)
- [8. Boot protection](#boot-protection)
- [9. Control from the dashboard](#9-control-from-the-dashboard)
- [10. Commands](#10-commands)
- [11. Native mode (legacy)](#11-native-mode-legacy)
- [12. Remove and roll back](#12-remove-and-roll-back)

---

## 1. How it works

```
core machine (k3s server, 10.254.254.1)               RAN machine (k3s agent, 10.10.0.1)
  dashboard ── gnb.sh ── Kubernetes API                 kubelet ── pod ocudu-gnb (namespace ocudu)
  AMF 10.10.0.10 / UPF 10.10.0.11 (net1)                 host network · privileged · hugepages
        ▲                                                 taskset -c 0-17 gnb -c <yml> -c metricas.yml
        └────────── fiber 10.10.0.0/24 ────────────────── N2/N3 on 10.10.0.1 · metrics :8001
                    (k3s API, flannel, N2/N3)             E810: VF in DPDK ── fronthaul 7.2 ── O-RU
```

- **A single cluster.** The RAN node joins the k3s of the core machine over the fiber. Label
  `innovanetwork/role=ran`, taint `innovanetwork/ran=true:NoSchedule`: only the gNB runs there.
- **The gNB runs exactly as on the host:** same binary (built from the same commit), same command and CPUs, `.yml`
  files read from the host `~/ocudu/configs`, log in the host `/tmp/gnb.log`, host network (N2/N3 on `10.10.0.1`,
  metrics on `:8001`). Measured result: ~92 % of the fronthaul packets on time, the same as native.
- **On/off = replicas.** `gnb.sh start` sets 1 replica; `stop`, 0.

**Why an own manifest and not the official `ocudu-gnb` chart:** the chart requires the Kubernetes static CPU
Manager, rewrites the DPDK arguments (`eal_args`), passes a single `-c` and runs as an unprivileged user. The own
manifest reproduces the validated native command, without changing the behavior of the gNB. The chart may become
a future option.

## 2. Files

| File | Runs on | Purpose |
|---|---|---|
| `ran/ocudu/ocudu.env` | — | setup parameters |
| `ran/ocudu/install.sh` | core machine | `copy` · `prepare` (sudo) · no argument: namespace and Deployment · `--dry-run` · `--remove` |
| `ran/ocudu/no-ran.sh` | **RAN node** (`~/innovanetwork-ran/`), sudo | `image` · `import` · `join` · `leave` · `status` |
| `ran/ocudu/gnb.sh` | core machine | `start [yml]` · `stop` · `status` · `log [-f]` · `configs` |
| `ran/ocudu/lib/render.py` | core machine | generates the Namespace, descriptor ConfigMap and Deployment |


## 3. Configuration (`ocudu.env`)

| Variable | Reference | Meaning |
|---|---|---|
| `OCUDU_NODE` | `innovaserver` | node name in Kubernetes (hostname) |
| `OCUDU_NODE_SSH` | `innovaserver@10.10.0.1` | SSH from the core machine to the node (passwordless) |
| `OCUDU_NODE_IP` / `OCUDU_NODE_IFACE` | `10.10.0.1` / `ens4f3np3` | node IP and interface in the cluster (the fiber) |
| `OCUDU_SERVER_VIA` | `10.10.0.2` | next hop to the server (`10.254.254.1`) |
| `OCUDU_NAMESPACE` | `ocudu` | namespace |
| `OCUDU_SRC_DIR` | `/home/innovaserver/ocudu` | OCUDU Git repository (image source) |
| `OCUDU_CONFIG_DIR` | `…/ocudu/configs` | folder of the `.yml` files, mounted read-only in the pod |
| `OCUDU_DEFAULT_CONFIG` | `gnb_split_open5gs` | initial `.yml` |
| `OCUDU_EXTRA_CONFIG` | `metricas.yml` | 2nd `-c` (turns on `remote_control` on port 8001, used by the dashboard) |
| `OCUDU_CPUS` | `0-17` | gNB CPUs (`taskset`) |
| `OCUDU_HUGEPAGES_1G` / `OCUDU_MEMORY_REQUEST` | `2Gi` / `2Gi` | resources requested by the pod |
| `OCUDU_LOG_DIR` | `/tmp` | log folder on the host |
| `OCUDU_IMAGE` / `OCUDU_IMAGE_TAG` | `innovanetwork/ocudu-gnb` / empty | image; empty tag = short commit of the source |
| `OCUDU_IMAGE_OS*`, `OCUDU_IMAGE_MARCH`, `OCUDU_BUILD_JOBS` | `ubuntu 24.04`, `native`, `8` | build |
| `OCUDU_IMAGE_ROHC` | `false` | build with ROHC (needs to download the library) |

## 4. The image

`sudo ~/innovanetwork-ran/no-ran.sh image` (on the node):

1. exports the **current commit** of `OCUDU_SRC_DIR` with `git archive` to `/var/tmp/innovanetwork-ocudu-src`
   (without the native `build/` folder, which would break CMake). **Uncommitted changes are not included**;
2. `docker build` with the **official OCUDU Dockerfile**: target `runtime-dpdk`, `COMPONENT=gnb`, Ubuntu 24.04,
   `-march=native` (the image only runs on this CPU or a compatible one);
3. checks that the image has `gnb`, `taskset` and `bash`;
4. imports it into the k3s containerd (`docker save | k3s ctr -n k8s.io images import -`), if the node is
   already in the cluster.

Result: `innovanetwork/ocudu-gnb:<commit>` (~140 MB). The Deployment uses `imagePullPolicy: Never`: the image
only exists on the node, with no registry.

## 5. The RAN node

`sudo ~/innovanetwork-ran/no-ran.sh join` (after `sudo ./ran/ocudu/install.sh prepare` on the core machine):

| Step | Detail |
|---|---|
| Checks | aborts if another Kubernetes holds the kubelet ports (10250/10248) and says how to stop it; cleans up leftovers of an earlier attempt |
| Route | unit `innovanetwork-k3s-route`: `10.254.254.1/32 via 10.10.0.2` (persistent, no netplan) |
| Firewall | UFW (if active) opens the server and the k3s networks |
| `/etc/rancher/k3s/config.yaml` | `node-ip`, `flannel-iface` (the fiber), label and taint |
| k3s | official installer, **same version as the server**, agent mode; the temporary token is deleted right after |
| Image | imported, if already built |

`leave` uninstalls the k3s agent and the route (the UFW rules stay). `status` shows the agent, the route, a
pending token, the OCUDU commit and whether a native gNB is running.

## 6. The pod

| Item | Value | Why |
|---|---|---|
| `nodeSelector` + toleration | RAN node | the NIC and the O-RU only exist there |
| `hostNetwork`, `hostPID` | yes | N2/N3/metrics on the host IPs; the pod sees the host `gnb` processes |
| `privileged`, `runAsUser: 0` | yes | DPDK (`vfio-pci` VF, `/proc/self/pagemap`, hugepages), like the native service |
| hugepages | `hugepages-1Gi: 2Gi` request and limit | Kubernetes limits the pod hugetlb to what it requests |
| mounts | `.yml` (read only), `/dev/hugepages`, `/tmp` | same configuration and same log as the host |
| strategy | `Recreate`, 0 or 1 replica | never two gNBs on the same RU |

The entry script of the pod:

1. applies the [boot protection](#boot-protection);
2. **refuses to start** if there is already a `gnb` process on the host (native service or terminal);
3. removes the old log if its owner is not root (the kernel does not allow reopening another owner's file in
   `/tmp`);
4. runs `taskset -c $GNB_CPUS gnb -c /configs/$GNB_CONFIG.yml -c /configs/metricas.yml`;
5. forwards the Kubernetes `SIGTERM` as `SIGINT` (the gNB exits cleanly, like Ctrl+C).

## 7. One `.yml` per core

The `.yml` files live in `~/ocudu/configs/` on the node and are read straight from the host. For each core there
is a copy in which only `cu_cp.amf.addr` changes:

| File (example) | AMF | Core |
|---|---|---|
| `gnb_split_open5gs.yml` | `10.10.0.10` | Open5GS |
| `gnb_split_free5gc.yml` | `10.10.0.30` | free5GC |

In both: gNB N2 and N3 on `10.10.0.1` (`cu_cp.amf.bind_addr`, `cu_up.ngu.socket.bind_addr`). The UPF N3 address is
not in the `.yml`: the SMF sends it in the session. **Do not change `metricas.yml`**: it is the one that turns on
the metrics read by the dashboard.

| Changed… | Needs |
|---|---|
| a `.yml` | restart the gNB (the pod reads the host folder) |
| the OCUDU source | commit → `no-ran.sh image` → `./ran/ocudu/install.sh` → restart ([tutorial](../tutorials/07-change-the-gnb.md)) |

<a id="boot-protection"></a>
## 8. Boot protection

After a boot the GNSS can take up to ~30 min to give a valid time, and the NIC clock jumps when that happens. A gNB
started before that leaves the O-RU synchronized to the wrong time. That is why **the gNB never starts by itself
after a node reboot**:

- every `gnb.sh start` writes the time of the request (`GNB_START_REQUEST`) into the Deployment;
- when it starts, the pod compares it with the host boot time (`btime` from `/proc/stat`);
- a request **older** than the boot → the pod stays up **without starting the gNB** and shows:
  `the gNB does NOT start by itself. Check the GPS (ts2phc 's2') and the RU, then run: ./ran/ocudu/gnb.sh start`.

The dashboard shows **"stopped (node rebooted)"**. After a valid GNSS, adjusted PTP and a rebooted O-RU, start it
again (dashboard or `gnb.sh start`). `install.sh` keeps the request in force and does not take down a running gNB.

## 9. Control from the dashboard

With `GNB_CTL_MODE="k8s"` in `config.env`, the `open5gs-k3s-gnb-ctl` agent (core machine):

- reads every 3 s the Deployment and the pod (replicas, `.yml`, phase, restarts, last 25 log lines), the `gnb`
  process on the node, the available `.yml` files with the AMF of each one, the PTP services, the GPS state and the
  VF driver;
- runs the dashboard requests with `ran/ocudu/gnb.sh` (start with the chosen `.yml`, restart, stop).

After starting, the dashboard checks: pod running (and still running 5 s later), **DU connected** on the O-RU and
**N2 on the AMF** of the active core. The core switch also restarts the gNB through Kubernetes.

## 10. Commands

```bash
# core machine
./ran/ocudu/gnb.sh configs                  # .yml files and the AMF of each one
./ran/ocudu/gnb.sh start <yml>              # start
./ran/ocudu/gnb.sh stop                     # stop
./ran/ocudu/gnb.sh status                   # replicas, .yml, pod, node, restarts
./ran/ocudu/gnb.sh log -f                   # gNB output
kubectl -n ocudu describe pod -l app.kubernetes.io/name=ocudu-gnb
kubectl describe node <RAN node>            # label, taint, allocatable hugepages

# RAN node
sudo ~/innovanetwork-ran/no-ran.sh status
tail -f /tmp/gnb.log                        # full gNB log
```

## 11. Native mode (legacy)

Before v3 the gNB ran as the systemd service `ocudu-gnb@<yml>` on the host, created by
`scripts/ocudu/setup-gnb-service.sh` (with a polkit rule so that the dashboard can control it without sudo). The
mode is still available with `GNB_CTL_MODE="systemd"`. The two modes do not run at the same time: the pod refuses
to start with a `gnb` on the host, and `gnb.sh start` refuses with the native service active.

## 12. Remove and roll back

| Undo | Command |
|---|---|
| gNB through Kubernetes → native | `./ran/ocudu/gnb.sh stop`; `GNB_CTL_MODE="systemd"` + `sudo ./install.sh --dashboard-only` |
| Deployment and namespace | `./ran/ocudu/install.sh --remove` |
| node of the cluster | on the node: `sudo ~/innovanetwork-ran/no-ran.sh leave`; on the core: `kubectl delete node <node>` |

Another Kubernetes on the node (e.g. MicroK8s) cannot run together with the k3s agent: they use the same ports.
Stop one before starting the other.
