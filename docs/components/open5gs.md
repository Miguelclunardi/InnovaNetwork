# Open5GS — default core

**Open5GS 2.7.5 5G Standalone** core in the `open5gs` namespace, installed by the root `install.sh` with the
[Gradiant](https://github.com/Gradiant/5g-charts) Helm charts (pinned commit) and values generated from
`config.env`. Validated with UERANSIM and with commercial phones through the OCUDU gNB.

| | |
|---|---|
| Functions | NRF, SCP, AMF, SMF, UPF, AUSF, UDM, UDR, PCF, BSF, NSSF + MongoDB + WebUI (4G and SEPP disabled) |
| Configuration | `config.env` → `helm/generated/open5gs-values.yaml` |
| N2 / N3 | `10.10.0.10` / `10.10.0.11` on the fiber (Multus) |
| Pools | `internet` 10.45.0.0/16 · `internet2` 10.46.0.0/16 |
| Subscribers | WebUI `http://<core machine>:30999` (`admin` / `1423` — change it) or `scripts/subscribers.sh` |
| Test | `./test.sh` → `7 checks OK` |

General architecture: [../architecture.md](../architecture.md). Installation: [../installation.md](../installation.md).

## Contents

1. [What install.sh does](#1-what-installsh-does)
2. [Operation](#2-operation-day-to-day)
3. [Modification](#3-modification): `config.env` reference, PLMN, slices, IPs, subscribers, versions, fiber
4. [Desktop × Server](#4-desktop--server)
5. [Tests](#5-tests)
6. [Uninstall](#6-uninstall)
7. [Common problems](#7-common-problems)
8. [Limitations](#8-known-limitations)
9. [References](#9-references)

---

## 1. What install.sh does

Each step only acts if something changed — running it again is safe.

1. **Validates** `config.env` (MCC/MNC/TAC/SD, overlapping CIDRs, IMSI length, keys…).
2. **Detects the environment**: desktop/server, interface and IP (default route), AVX, RAM, NetworkManager, UFW, firewalld, Docker.
3. Missing **packages** (`curl git iptables lksctp-tools bash-completion …`).
4. **Modules** `sctp tun br_netfilter overlay` (loaded and persisted).
5. **sysctl**: `ip_forward`, `bridge-nf-call-iptables`, inotify, buffers.
6. **Host profile**: NetworkManager ignores `cni0/flannel*/veth*/k3s0`; UFW rules; **firewalld** with the cluster networks in the `trusted` zone; warnings (Docker, AVX, RAM).
7. **Stable interface** `k3s0` (unit `open5gs-k3s-netif`), so that the cluster does not depend on the host IP.
8. **k3s** `K3S_VERSION` through `/etc/rancher/k3s/config.yaml` (node-ip, flannel interface, CIDRs, no Traefik, kubelet with a higher pull QPS, kubeconfig 0600). Config changed ⇒ k3s restart.
9. **Helm** `HELM_VERSION` (SHA-256 checked) if there is no Helm 3 on the system.
10. **Gradiant charts** at commit `GRADIANT_CHARTS_REF` + `helm dependency build`.
11. **Open5GS**: generates `helm/generated/open5gs-values.yaml` and runs `helm upgrade --install --wait`.
12. **Subscribers**: syncs the simulated UEs + `SUBSCRIBERS` into MongoDB.
13. **UERANSIM**: generates `helm/generated/ueransim-values.yaml`, installs it with the post-renderer, waits for the NG Setup and makes sure the UEs are registered **and pinging the UPF** (if needed it restarts the UEs and, after that, UPF → SMF → gNB → UEs).
14. **Boot recovery** (`AUTO_HEAL`): installs the `open5gs-k3s-heal` unit.
15. **kubeconfig of the real user** (`$SUDO_USER`): creates/merges `~/.kube/config` (0600), alias `k` + completion, and tests `kubectl get nodes` as that user.

After UERANSIM come the **dashboard and the agents** ([dashboard.md](dashboard.md)) and the boot units.

Options: `--deploy-only` (skips 3–9: only values, deploy, subscribers, dashboard and kubeconfig), `--dashboard-only` (only the dashboard and the agents), `-h`.

---

## 2. Operation (day to day)

Every command below runs **without sudo**, except where stated.

### 2.1 See the state

```bash
kubectl get nodes                                  # node Ready
kubectl -n open5gs get pods -o wide                # 16 pods 1/1 Running
kubectl -n open5gs get svc                         # services (amf-ngap 38412/SCTP, webui 30999…)
./test.sh                                          # full check (exit 0 = OK)
```

`k` is an alias for `kubectl` (with completion) in new terminals.

### 2.2 Logs

```bash
kubectl -n open5gs logs deploy/open5gs-amf -f      # AMF live (registrations, gNBs)
kubectl -n open5gs logs deploy/open5gs-smf -f      # PDU sessions, allocated IPs
kubectl -n open5gs logs deploy/open5gs-upf         # PFCP, TUN
kubectl -n open5gs logs deploy/ueransim            # gNB
kubectl -n open5gs logs deploy/ueransim-ues        # UEs
kubectl -n open5gs logs deploy/open5gs-amf --previous   # previous run (after a crash)
sudo journalctl -u k3s -f                          # k3s (sudo)
less logs/install.log                              # installer history
```

### 2.3 Using the simulated UE

```bash
kubectl -n open5gs exec -it deploy/ueransim-ues -- bash
# inside the pod:
nr-cli -d                                          # lists the UEs (imsi-001010000000001…)
nr-cli imsi-001010000000001 --exec status          # RM-REGISTERED? MM-REGISTERED/NORMAL-SERVICE?
nr-cli imsi-001010000000001 --exec ps-list         # PDU sessions
ip addr show uesimtun0                             # UE IP
ping -I uesimtun0 8.8.8.8                          # traffic through the core
curl --interface uesimtun0 https://example.com
traceroute -i uesimtun0 8.8.8.8
nr-cli imsi-001010000000001 --exec "deregister normal"   # deregister
```

gNB: `kubectl -n open5gs exec deploy/ueransim -- sh -c 'nr-cli $(nr-cli -d) --exec status'`.

### 2.4 WebUI

`http://<NODE_IP>:30999` (`admin` / `1423`; change the password on the first access). It lets you create/edit
subscribers, AMBR, QoS (5QI/ARP), a fixed IP and multiple slices per subscriber.

### 2.5 Subscribers

```bash
./scripts/subscribers.sh list                                   # IMSI, K, OPc, DNN, IP
./scripts/subscribers.sh add 001010000000200 <K> <OPc>          # 1st slice/DNN
./scripts/subscribers.sh add 001010000000201 <K> <OPc> 1 111111 internet
./scripts/subscribers.sh remove 001010000000200
./scripts/subscribers.sh sync                                   # re-applies what is in config.env
./scripts/subscribers.sh reset                                  # DELETES all of them (asks for confirmation)
```

`add`/`remove` are not stored in `config.env`; to persist them, use `SUBSCRIBERS` (see §3.5).

### 2.6 Restart components

```bash
kubectl -n open5gs rollout restart deploy/open5gs-amf          # one NF
kubectl -n open5gs rollout restart deploy/ueransim-ues          # UEs (e.g. UE stuck in LIMITED-SERVICE)
kubectl -n open5gs rollout restart deploy                       # everything (core + RAN)
```

> Restart **all NFs together** instead of one by one when there are SBI errors with old IPs (discovery cache —
> see [troubleshooting](../troubleshooting.md)).

### 2.7 Stop, start and reboot

The normal way is the dashboard **Control** tab (**▶ Start all** / **■ Stop all**), which follows the right order
and checks each step. See [../operation.md](../operation.md).

**At boot**, the behavior depends on `CORE_AUTOSTART`:

| `CORE_AUTOSTART` | After powering the machine on |
|---|---|
| `false` (default) | the `open5gs-k3s-heal` unit runs `heal.sh --boot-off`: **only the dashboard stays up**; the core (and free5GC) start stopped and are started from the dashboard |
| `true` | everything comes up, and the same unit checks whether the simulated UE pings the UPF; if not, it restarts the UEs and then UPF → SMF → gNB → UEs (after a reboot the pods come back in any order and the UPF may not recognize the SMF: `Cannot find PFCP-Node`) |

```bash
journalctl -u open5gs-k3s-heal -b      # what the unit did on this boot
./scripts/heal.sh                      # manual user-plane recovery
```

Stopping the whole k3s (frees CPU/RAM; the RAN node loses the server meanwhile):

```bash
sudo systemctl stop k3s && sudo /usr/local/bin/k3s-killall.sh
sudo systemctl start k3s
```

### 2.8 Subscriber backup and restore

```bash
# backup
kubectl -n open5gs exec deploy/open5gs-mongodb -- mongodump --db open5gs --archive > backup-open5gs-$(date +%F).archive
# restore (replaces the collections)
kubectl -n open5gs exec -i deploy/open5gs-mongodb -- mongorestore --drop --archive < backup-open5gs-YYYY-MM-DD.archive
```

The MongoDB volume (PVC `local-path`) lives in `/var/lib/rancher/k3s/storage/` and survives reboots and
`helm upgrade`; it is deleted by `./uninstall.sh`.

### 2.9 Apply a configuration change

```bash
vim config.env
sudo ./install.sh --deploy-only     # fast: only regenerates the values and deploys
./test.sh
```

Use the full `sudo ./install.sh` when you change something of the host/k3s (interface, node IP, versions,
firewall).

---

## 3. Modification

**General rule**: edit `config.env` → `sudo ./install.sh --deploy-only` (or the full one) → `./test.sh`.

How changes are applied: the values in `helm/generated/` are regenerated; a **hash** of the configuration goes as
an annotation on each pod (`open5gs-k3s/config-hash`). If it changed, the NFs are recreated (`Recreate` strategy,
all together) and so are the gNB/UEs; the subscribers are re-synced.

### 3.1 config.env reference

| Variable | Default | Purpose |
|----------|--------|--------|
| `ENV_PROFILE` | `auto` | `auto`/`desktop`/`server` (see §4) |
| `NODE_IP_MODE` | `stable` | `stable`: k3s uses the virtual interface `STABLE_IFACE` with `STABLE_IP` (default `k3s0` / `10.254.254.1`), recreated at every boot. This way the cluster does not depend on the host IP (DHCP, switching between Wi‑Fi and cable, another network). `iface`: uses the physical NIC, and if the IP changes the install must run again |
| `STABLE_IFACE`, `STABLE_IP` | `k3s0`, `10.254.254.1` | virtual interface and IP of the node (the IP must be private and outside the LAN and `K3S_*_CIDR`) |
| `NODE_IFACE`, `NODE_IP` | empty (default route) | physical interface and IP of the host. In `stable` mode they are only used for the WebUI URL and to advertise the external N3 (`EXPOSE_RAN`); in `iface` mode they are also the k3s node |
| `KUBECONFIG_USER` | empty (`$SUDO_USER`) | user that gets `~/.kube/config` |
| `SHELL_EXTRAS` | `true` | alias `k` + completion in `~/.bashrc` |
| `INSTALL_DIR` | `/opt/open5gs-k3s` | cloned charts, helm, state |
| `AUTO_INSTALL_MODULES_EXTRA` | `true` | installs `linux-modules-extra` if SCTP is missing |
| `CONFIGURE_UFW`, `CONFIGURE_FIREWALLD` | `true` | opens the cluster in the active firewall |
| `K3S_VERSION`, `HELM_VERSION` | `v1.36.5+k3s1`, `v3.22.1` | pinned versions |
| `GRADIANT_CHARTS_REPO`, `GRADIANT_CHARTS_REF` | GitHub, commit `3f998fb` | source and version of the charts |
| `OPEN5GS_IMAGE_TAG`, `UERANSIM_IMAGE_TAG` | empty (2.7.5 / 3.2.6) | change images |
| `K8S_NAMESPACE`, `OPEN5GS_RELEASE`, `UERANSIM_RELEASE` | `open5gs`, `open5gs`, `ueransim` | names in k8s |
| `K3S_CLUSTER_CIDR`, `K3S_SERVICE_CIDR` | `10.42.0.0/16`, `10.43.0.0/16` | cluster networks |
| `K3S_EXTRA_ARGS` | `()` | extra `k3s server` flags |
| `HELM_TIMEOUT` | `20m` | `helm --wait` timeout |
| `MCC`, `MNC` | `001`, `01` | PLMN |
| `TAC` | `1` | Tracking Area Code (decimal) |
| `AMF_REGION_ID`, `AMF_SET_ID` | `2`, `1` | GUAMI |
| `NETWORK_NAME` | `InnovaOpen5GS` | network name shown on the UE |
| `SLICES` | `internet` 10.45/16 and `internet2` 10.46/16 | slices/DNN/pools (see §3.3) |
| `DNS_SERVERS`, `UE_MTU` | `8.8.8.8 8.8.4.4`, `1400` | handed to the UE |
| `WEBUI_ENABLED`, `WEBUI_NODEPORT` | `true`, `30999` | WebUI |
| `DASHBOARD_*`, `GNB_METRICS_URL`, `GNB_LOG_*`, `OPEN5GS_METRICS` | see [dashboard.md](dashboard.md) | logs and metrics dashboard |
| `MONGODB_PERSISTENCE`, `MONGODB_PERSISTENCE_SIZE` | `true`, `2Gi` | database volume |
| `MONGODB_IMAGE_REGISTRY/REPOSITORY/TAG` | empty (Bitnami latest) | alternative image (e.g. CPU without AVX) |
| `DEPLOY_UERANSIM` | `true` | `false` removes the simulated gNB/UEs (for a real RAN) |
| `AUTO_HEAL` | `true` | `open5gs-k3s-heal` unit: at boot, checks the user plane and restarts UEs/UPF/SMF/gNB if needed |
| `EXPOSE_RAN` | `false` | exposes N2/N3 on `NODE_IP` for an external gNB (see §3.7) |
| `UE_COUNT`, `UE_MSIN_START`, `UE_KEY`, `UE_OPC` | `1`, `0000000001`, test keys | simulated UEs (registered automatically) |
| `SUBSCRIBERS` | `()` | extra subscribers (real SIMs) |
| `TEST_*` | ping 4×, 8.8.8.8, 180 s | `test.sh` parameters |

### 3.2 PLMN and TAC

```bash
MCC="001"; MNC="01"          # 2- or 3-digit MNC: "01" ≠ "001"
TAC="1"                      # decimal (hex TAC 0x000064 = 100)
UE_MSIN_START="0000000001"   # 15 − len(MCC) − len(MNC) digits (10 with a 2-digit MNC, 9 with a 3-digit MNC)
```

The PLMN is applied to: AMF (GUAMI, TAI, supported PLMN), **NRF (served PLMN)**, gNB and UEs/IMSIs. Subscribers of
the previous PLMN stay in the database — remove them with `./scripts/subscribers.sh remove <IMSI>`.

> Use test PLMNs (`001-01`, `999-70`). With a real radio, never transmit with an operator PLMN and follow the
> spectrum regulations.

### 3.3 Slices, DNN and IP pools

```bash
SLICES=(
  "1:111111:internet:10.45.0.0/16"     # SST:SD:DNN:POOL
  "2:222222:ims:10.46.0.0/16"
)
```

Each item generates: S-NSSAI in the AMF, NSI in the NSSF, a session (pool, gateway `.1`, DNN) in the SMF and a TUN
with NAT in the UPF (`ogstun`, `ogstun2`, …). Rules: **SD is mandatory** (6 hex, no `0x`), one DNN per slice, pools
with no overlap among themselves nor with the cluster networks (validated). The **1st slice** is the one of the
UERANSIM gNB/UEs — to test another one, put it first.

### 3.4 IPs and network

| What to change | How |
|-------------|------|
| UE IP pool | 4th field of each `SLICES` item |
| UE DNS / MTU | `DNS_SERVERS`, `UE_MTU` |
| k3s node address | `NODE_IP_MODE`, `STABLE_IFACE`, `STABLE_IP`, `NODE_IFACE`, `NODE_IP` → `sudo ./install.sh` (rewrites the k3s config and restarts it) |
| Cluster networks | `K3S_CLUSTER_CIDR`, `K3S_SERVICE_CIDR` → **requires** `sudo ./uninstall.sh --k3s` first |
| WebUI port | `WEBUI_NODEPORT` (30000–32767) |

### 3.5 Persistent subscribers

```bash
UE_COUNT="3"                     # simulated UEs 001010000000001..003, registered automatically
SUBSCRIBERS=(
  "001010000000101:<K 32 hex>:<OPc 32 hex>"                 # 1st slice/DNN
  "001010000000102:<K>:<OPc>:2:222222:ims"                  # specific slice/DNN
)
```

The sync does *remove + add* of each listed IMSI (changes made in the WebUI to those IMSIs are overwritten); IMSIs
outside `config.env` are not touched.

### 3.6 Versions

Change `K3S_VERSION`, `HELM_VERSION`, `GRADIANT_CHARTS_REF` (commit/tag), `OPEN5GS_IMAGE_TAG`,
`UERANSIM_IMAGE_TAG` and run `sudo ./install.sh`. When you bump `GRADIANT_CHARTS_REF`, check whether the HPA bug
(`helm/postrender/`) and the NRF `servingList` are still the same (`helm template` helps — see §3.8).

### 3.7 Link to the real gNB (N2/N3 fiber)

```bash
RAN_LINK_ENABLED=true
RAN_LINK_IFACE="enp5s0f1"      # port of the core machine connected to the gNB
RAN_LINK_CIDR="10.10.0.0/24"   # the core machine uses .2, the gNB .1
RAN_LINK_MTU="9000"
AMF_N2_IP="10.10.0.10"         # = cu_cp.amf.addr in the gNB .yml
UPF_N3_IP="10.10.0.11"         # N3 address advertised by the UPF
GNB_SIM_IP="10.10.0.20"        # UERANSIM gNB on the same network
```

The installer creates the NetworkAttachmentDefinition `ran-link` (macvlan) and gives the AMF, the UPF and the
UERANSIM gNB a 2nd interface (`net1`) with those IPs. The post-renderer `helm/postrender/amf-ngap-net1.sh` makes
the AMF listen for N2 on `net1`. Alternative without a dedicated port (experimental): `EXPOSE_RAN=true` exposes
N2/N3 on the node IP.

### 3.8 Changing more than config.env

| I want to… | Where |
|--------|------|
| Change an NF parameter that `config.env` does not expose | `render_open5gs_values()` in `scripts/lib/common.sh` (generates the values YAML). Possible values: the `values.yaml` of each subchart in `/opt/open5gs-k3s/5g-charts/charts/open5gs-<nf>/`. |
| Override the whole config file of an NF | `<nf>.customOpen5gsConfig` in the values (supported by the charts). |
| Add a new variable to `config.env` | declare it in `config.env`, give it a default in `load_config()`, validate it in `validate_config()`, use it in the render. |
| Change the simulated gNB/UE | `render_ueransim_values()` in `scripts/lib/common.sh`. |
| Filter/change the rendered manifests | post-renderers in `helm/postrender/`. |
| See what will be applied without applying it | `helm template open5gs /opt/open5gs-k3s/5g-charts/charts/open5gs -f /opt/open5gs-k3s/5g-charts/charts/open5gs/values-5g.yaml -f helm/generated/open5gs-values.yaml` |
| See what is applied | `helm -n open5gs get values open5gs`, `kubectl -n open5gs get cm open5gs-amf -o yaml` |

After editing scripts: `bash -n *.sh scripts/*.sh scripts/lib/*.sh helm/postrender/*.sh` and, if possible,
`shellcheck`.

---

## 4. Desktop × Server

The same `config.env` serves both; the host differences are detected (`ENV_PROFILE=auto`).

| Aspect | Desktop | Server | Handling |
|---------|---------|--------|------------|
| Profile | NetworkManager active or a login manager (gdm etc.) | neither (netplan + networkd), even with `graphical.target` | `auto` or force `desktop`/`server` |
| NetworkManager | active — would try to manage `cni0`/`flannel.1`/`veth*` | usually absent | `unmanaged-devices` file if NM is active |
| Interface | `enp*`, `wlp*` (Wi-Fi) | `ens*`, `eno*`, bonds, VLANs | default route or `NODE_IFACE`/`NODE_IP` |
| IP | DHCP may change, Wi‑Fi or cable | usually fixed | `NODE_IP_MODE=stable`: the k3s node stays on `k3s0` (10.254.254.1) and an IP change does not affect the cluster |
| SCTP | the `generic` kernel already has it | `-virtual`/cloud kernels may not | installs `linux-modules-extra-$(uname -r)` |
| Firewall | firewalld/UFW may be active | same | cluster networks opened automatically |
| Docker | common | rare | warning (FORWARD DROP policy) |
| kubectl | may already exist in `/usr/local/bin` | usually comes from k3s | `~/.kube/config` of `$SUDO_USER`; scripts use an explicit kubeconfig |
| Architecture | x86_64 | x86_64 or arm64 | Helm downloaded for the right architecture |

The way out to the internet (N6) always follows the current default route. With more than one NIC, set
`NODE_IFACE` and `NODE_IP` to choose the IP advertised to an external gNB (`EXPOSE_RAN`).

---

## 5. Tests

`./test.sh` (or `./test.sh -v` for the AMF/SMF/UPF/gNB/UE logs on failure). Validation output:

```
==> Pods in namespace open5gs
    [ok] all pods Running/Ready (16)
==> NRF
    [ok] NRF registered 9 NF(s)
==> N2: NG Setup
    [ok] gNB did NG Setup with the AMF (open5gs-amf-ngap:38412/SCTP)
==> UEs: registration (5GMM) and PDU session (DNN internet, S-NSSAI 1/111111)
    [ok] imsi-001010000000001: registered (MM-REGISTERED/NORMAL-SERVICE)
    [ok] imsi-001010000000001: PDU session active, uesimtun0 = 10.45.0.2 (pool 10.45.0.0/16)
    [ok] imsi-001010000000001: ping 10.45.0.1 (gateway on the UPF) via uesimtun0
    [ok] imsi-001010000000001: ping 8.8.8.8 via uesimtun0 (0% packet loss; rtt 15.670 ms)
RESULT: 7 checks OK, 0 failures
```

The ping to the gateway tests the user plane (N3/GTP-U → UPF) without depending on the internet; the external
ping tests N6/NAT. Exit code 0/1 (useful for automation).

---

## 6. Uninstall

```bash
sudo ./uninstall.sh            # releases + MongoDB PVC + namespace (k3s stays)
sudo ./uninstall.sh --k3s      # + the whole k3s + the open5gs-k3s context of ~/.kube/config
sudo ./uninstall.sh --purge    # + sysctl, modules, NetworkManager, UFW/firewalld, /opt/open5gs-k3s,
                               #   helm/generated/ and the ~/.bashrc block
sudo ./uninstall.sh --purge -y # no confirmation
```

Other contexts of your `~/.kube/config` are kept. apt packages are not removed.

---

## 7. Common problems

Full guide: **[troubleshooting.md](../troubleshooting.md)**. The most common:

| Symptom | Quick fix |
|---------|----------------|
| `connection to the server localhost:8080 was refused` | The user kubeconfig is missing: `sudo ./install.sh --deploy-only` (or `sudo k3s kubectl …`). |
| UE `no cells in coverage` | Host firewall blocking pod↔pod (firewalld): run `sudo ./install.sh`. |
| UE in `LIMITED-SERVICE` | `kubectl -n open5gs rollout restart deploy/ueransim-ues`. |
| Registration rejected, SCP `No SEPP` | PLMN outside the NRF `serving` list — already handled; check `MCC`/`MNC` and run the install. |
| Pods `CrashLoopBackOff` in the first minutes | Normal while MongoDB comes up. |
| MongoDB *Illegal instruction* | CPU without AVX → `MONGODB_IMAGE_*`. |

---

## 8. Known limitations

- Single node, no high availability; standalone MongoDB.
- N4, SBI and N6 over the pod network; only N2 and N3 on the fiber (Multus/macvlan).
- UERANSIM tests only the 1st slice per installation.
- IPv4 only in the UE pools; SBI over HTTP (no TLS), as in the default charts.

---

## 9. References

- Open5GS — https://open5gs.org · https://github.com/open5gs/open5gs
- Gradiant 5g-charts — https://github.com/Gradiant/5g-charts
- UERANSIM — https://github.com/aligungr/UERANSIM
- k3s — https://docs.k3s.io
- towards5gs-helm (architecture reference) — https://github.com/Orange-OpenSource/towards5gs-helm
- 3GPP TS 23.501 (5GS architecture), TS 23.502 (procedures), TS 38.413 (NGAP), TS 29.281 (GTP-U)
