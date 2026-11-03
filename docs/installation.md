# Installation

From scratch to a phone browsing the internet. The installation has three independent parts; do them in order and
stop wherever you want.

| Part | Result | Where | Time |
|---|---|---|---|
| [1. Core and dashboard](#1-open5gs-core-ueransim-and-dashboard) | Open5GS + UERANSIM + dashboard, tested | core machine | 15–30 min |
| [2. free5GC (optional)](#2-free5gc-optional) | second core, switchable from the dashboard | core machine | 15 min |
| [3. Radio: OCUDU on Kubernetes](#3-radio-ocudu-on-kubernetes) | real gNB as a pod on the RAN node | both machines | ~1 h |

Next: [day-to-day operation](operation.md).

---

## 0. Requirements

### Core machine

- Ubuntu 24.04 LTS (desktop or server), x86_64; CPU with **AVX** (MongoDB 8); 8 GiB of RAM; 20 GiB free.
- Internet access (apt, k3s, Helm, GitHub, Docker Hub) and `sudo`.
- For the radio: a dedicated network port connected to the RAN machine (fiber or copper), ideally MTU 9000.

### RAN machine (part 3 only)

The machine must **already run the OCUDU gNB natively** with your radio. InnovaNetwork moves that gNB to
Kubernetes; it does **not** prepare the machine. First make sure you have:

- a low-latency kernel, isolated CPUs for the gNB (`isolcpus`) and 1 GiB hugepages;
- a NIC with a VF on `vfio-pci` (DPDK) for the fronthaul and working PTP (grandmaster with GNSS or another one);
- the OCUDU source in a Git folder (e.g. `~/ocudu`) and the gNB `.yml` files in `~/ocudu/configs/`;
- Docker installed (to build the image);
- **passwordless** SSH from the core machine to the RAN machine (`ssh-copy-id user@fiber-ip`).

The reference setup is described in [hardware/e810-liteon.md](hardware/e810-liteon.md).

---

## 1. Open5GS core, UERANSIM and dashboard

**Core machine.**

```bash
git clone https://github.com/Miguelclunardi/InnovaNetwork.git ~/InnovaNetwork
cd ~/InnovaNetwork
nano config.env
```

`config.env` is commented line by line. The minimum to review:

| Section | Variables | Example |
|---|---|---|
| PLMN | `MCC`, `MNC`, `TAC`, `NETWORK_NAME` | `001`, `01`, `1`, `InnovaOpen5GS` |
| Slices | `SLICES` (`SST:SD:DNN:pool`) | `"1:111111:internet:10.45.0.0/16"` |
| Fiber to the gNB | `RAN_LINK_ENABLED`, `RAN_LINK_IFACE`, `RAN_LINK_CIDR`, `AMF_N2_IP`, `UPF_N3_IP` | `true`, `enp5s0f1`, `10.10.0.0/24`, `10.10.0.10`, `10.10.0.11` |
| gNB in the dashboard | `GNB_METRICS_URL`, `GNB_LOG_SSH`, `GNB_CTL_MODE`, `GNB_CTL_SSH`, `GNB_CTL_DIR` | `ws://10.10.0.1:8001`, … |
| O-RU in the dashboard | `RU_MGMT_IP`, `RU_SSH_USER`, `RU_MGMT_LOCAL_CIDR` | `10.101.131.59` |

Without a radio, leave `RAN_LINK_ENABLED=false` and the gNB/O-RU variables empty.

```bash
sudo ./install.sh        # 5–15 min the 1st time; log in logs/install.log
./test.sh                # pods → NRF → NG Setup → registration → session → ping
```

Expected:

```
RESULT: 7 checks OK, 0 failures
```

The installer, in steps that only act when something changed: validates the configuration → packages, modules
(SCTP) and sysctl → stable interface `k3s0` → k3s → Helm and charts → Multus and the fiber network → Open5GS →
subscribers → UERANSIM → dashboard and agents → boot units → the user's `~/.kube/config`.

At the end it shows the dashboard address and where the **administrator password** is:

```bash
sudo cat /opt/open5gs-k3s/state/dashboard-admin-password
```

Useful options:

| Command | Does |
|---|---|
| `sudo ./install.sh --deploy-only` | re-applies only the core, UERANSIM, subscribers and dashboard (does not touch packages or k3s) |
| `sudo ./install.sh --dashboard-only` | reinstalls only the dashboard and the agents (does not touch the core or the gNB) |
| `sudo ./uninstall.sh` | removes the core (levels `--k3s`, `--purge`) |

Core details: [components/open5gs.md](components/open5gs.md). Guided tutorial:
[First test with UERANSIM](tutorials/01-first-test-ueransim.md).

### O-RU credentials (optional)

The dashboard RU tab reads the O-RU over SSH. The password stays out of git, in a root-owned file:

```bash
printf 'RU_PASS=%s\nRU_ENABLE=%s\n' 'SSH_PASSWORD' 'ENABLE_PASSWORD' | \
  sudo install -m 0640 -g "$(id -gn)" /dev/stdin /opt/open5gs-k3s/state/ru-credentials
sudo systemctl restart open5gs-k3s-ru
```

---

## 2. free5GC (optional)

**Core machine**, with part 1 installed.

```bash
sudo ./free5gc/setup-gtp5g.sh             # UPF kernel module (once; DKMS)
nano free5gc/free5gc.env                  # IPs on the fiber, pools, network name
./free5gc/install.sh                      # no sudo; namespace free5gc
./free5gc/install.sh --import-open5gs     # copies the SIMs registered in Open5GS
./free5gc/test.sh                         # "6 ok, 0 failure(s)"
sudo ./install.sh --dashboard-only        # the dashboard starts offering the core switch
```

free5GC comes up running. To keep it as a standby, switch back to Open5GS from the dashboard (Control tab →
Active core). Details: [components/free5gc.md](components/free5gc.md).

---

## 3. Radio: OCUDU on Kubernetes

> **Depends on your setup.** The values in `ran/ocudu/ocudu.env` are those of the reference setup (Intel E810 +
> LiteOn, split 7.2). Review all of them before you start.

Each step says which machine it runs on. `./ran/ocudu/…` commands run on the **core machine**, inside the
repository; `~/innovanetwork-ran/no-ran.sh …` commands run on the **RAN machine**.

### 3.1 Configure — core machine

```bash
nano ran/ocudu/ocudu.env
```

| Variable | Example | Meaning |
|---|---|---|
| `OCUDU_NODE`, `OCUDU_NODE_SSH` | `innovaserver`, `innovaserver@10.10.0.1` | node name and SSH access over the fiber |
| `OCUDU_NODE_IP`, `OCUDU_NODE_IFACE` | `10.10.0.1`, `ens4f3np3` | node IP and interface in the cluster (the fiber, **never** the fronthaul) |
| `OCUDU_SERVER_VIA` | `10.10.0.2` | IP of the core machine on the fiber (route to `10.254.254.1`) |
| `OCUDU_SRC_DIR`, `OCUDU_CONFIG_DIR` | `/home/innovaserver/ocudu`, `…/configs` | gNB source and `.yml` files on the node |
| `OCUDU_DEFAULT_CONFIG`, `OCUDU_EXTRA_CONFIG` | `gnb_split_open5gs`, `metricas.yml` | default `.yml` and the 2nd `-c` (metrics on port 8001) |
| `OCUDU_CPUS` | `0-17` | gNB CPUs (`taskset`) |
| `OCUDU_HUGEPAGES_1G`, `OCUDU_MEMORY_REQUEST` | `2Gi`, `2Gi` | hugepages and memory requested by the pod |
| `OCUDU_IMAGE*`, `OCUDU_BUILD_JOBS` | `innovanetwork/ocudu-gnb`, `8` | image (tag = source commit) and build |

### 3.2 Copy the scripts to the node — core machine

```bash
./ran/ocudu/install.sh copy
```

Creates `~/innovanetwork-ran/` on the node (mode 700) with `no-ran.sh` and `ocudu.env`.

### 3.3 Build the gNB image — RAN machine (sudo)

```bash
sudo ~/innovanetwork-ran/no-ran.sh image 2>&1 | tee ~/innovanetwork-ran/build.log
```

Exports the **current commit** of the source (`git archive`, without the native `build/` folder) and builds it with
the **official OCUDU Dockerfile** (target `runtime-dpdk`, `-march=native`). Result:
`innovanetwork/ocudu-gnb:<commit>` (~140 MB, ~15 min). It loads the machine: avoid it during experiments.

### 3.4 Open the server and create the token — core machine (sudo)

```bash
sudo ./ran/ocudu/install.sh prepare
```

Opens the firewall for the node (UFW, if active) and creates a join token **valid for 2 h**, copied to the node in
`~/innovanetwork-ran/join.env` (mode 600). The token never shows on the screen.

### 3.5 Join the cluster — RAN machine (sudo)

```bash
sudo ~/innovanetwork-ran/no-ran.sh join 2>&1 | tee ~/innovanetwork-ran/join.log
```

Checks for conflicts (another Kubernetes on the kubelet ports), creates the route to the server, writes the agent
configuration (IP, interface, label, taint), installs the k3s agent with the same version as the server, deletes
the token and imports the image. Check on the core machine:

```bash
kubectl get nodes -o wide     # the RAN node "Ready", INTERNAL-IP 10.10.0.1
```

If the image was built afterwards: `sudo ~/innovanetwork-ran/no-ran.sh import`.

### 3.6 Create the Deployment — core machine

```bash
./ran/ocudu/install.sh --dry-run   # generates and validates, without applying
./ran/ocudu/install.sh             # namespace ocudu + Deployment with 0 replicas (gNB stopped)
```

### 3.7 Start the gNB — core machine

Before: core running, valid PTP/GNSS, O-RU ready and **no native gNB running** on the node.

```bash
./ran/ocudu/gnb.sh configs                            # available .yml files and the AMF of each one
./ran/ocudu/gnb.sh start gnb_split_open5gs
./ran/ocudu/gnb.sh log -f                             # wait for "N2: Connection to AMF … completed"
```

### 3.8 Control it from the dashboard

In `config.env`: `GNB_CTL_MODE="k8s"` (and the node's `GNB_CTL_SSH`, `GNB_CTL_DIR`). Then:

```bash
sudo ./install.sh --dashboard-only
```

The **Control** tab now shows the **gNB (Kubernetes)** card, with start/stop/restart and the choice of the `.yml`.
Complete tutorial with expected results: [OCUDU on Kubernetes](tutorials/03-ocudu-on-kubernetes.md).

---

## Final check

| What | How | Expected |
|---|---|---|
| Cluster | `kubectl get nodes` | two `Ready` nodes |
| Core | `./test.sh` | `7 checks OK` |
| gNB | `./ran/ocudu/gnb.sh log` | `N2: Connection to AMF … completed`, `gNB started` |
| O-RU | dashboard → RU tab | `SYNCHRONIZED`, DU `Ready`, ~90 % of the packets on time |
| Phone | dashboard → Overview | registered, session with an IP from the pool |

## Uninstall

| What | Command |
|---|---|
| gNB (Deployment and namespace) | `./ran/ocudu/install.sh --remove` |
| RAN node | on the node: `sudo ~/innovanetwork-ran/no-ran.sh leave`; on the core: `kubectl delete node <node>` |
| free5GC | `./free5gc/uninstall.sh`; module: `sudo ./free5gc/setup-gtp5g.sh --remove` |
| core and dashboard | `sudo ./uninstall.sh` (`--k3s` removes k3s; `--purge` everything the installer created) |
