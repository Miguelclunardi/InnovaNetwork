# Architecture

How InnovaNetwork is built: machines, cluster, components, networks, IPs, ports and folders.

- [1. Overview](#1-overview)
- [2. Machines and roles](#2-machines-and-roles)
- [3. The Kubernetes cluster](#3-the-kubernetes-cluster)
- [4. Components per namespace](#4-components-per-namespace)
- [5. Networks](#5-networks)
- [6. Addresses and ports](#6-addresses-and-ports)
- [7. Network functions and 3GPP interfaces](#7-network-functions-and-3gpp-interfaces)
- [8. From the phone to the internet](#8-from-the-phone-to-the-internet)
- [9. How the dashboard sees everything](#9-how-the-dashboard-sees-everything)
- [10. Installed folders and services](#10-installed-folders-and-services)
- [11. Design principles](#11-design-principles)

---

## 1. Overview

```
                              ┌──────────────────── k3s cluster ─────────────────────┐
                              │                                                       │
  local network (DHCP) ───────┤ CORE MACHINE (server)             RAN MACHINE (node)  │
                              │  ns open5gs: core + UERANSIM       ns ocudu:           │
                              │              + dashboard            pod ocudu-gnb      │
                              │  ns free5gc: core + UERANSIM        (host network)     │
                              │                                                       │
                              │  enp5s0f1 10.10.0.2 ═══ fiber ═══ 10.10.0.1 E810 p4   │
                              └───────────────────────────────────────────┬──────────┘
                                                                          │ E810 p1: fronthaul 7.2 + PTP
                                                                     ┌────┴────┐
                                                                     │  O-RU   │ ))) UEs
                                                                     └─────────┘
```

Three layers, each with its own installer:

| Layer | What it is | Installer | Configuration |
|---|---|---|---|
| **Platform + default core + dashboard** | k3s, Multus, Open5GS, UERANSIM, dashboard | `install.sh` | `config.env` |
| **Optional core** | free5GC + its own UERANSIM | `free5gc/install.sh` | `free5gc/free5gc.env` |
| **Radio** | RAN node + OCUDU gNB | `ran/ocudu/install.sh` + `no-ran.sh` | `ran/ocudu/ocudu.env` |

## 2. Machines and roles

| | Core machine | RAN machine |
|---|---|---|
| Name in the reference setup | `torre2` | `innovaserver` |
| Role in k3s | **server** (control plane + workloads) | **agent** (node dedicated to the radio) |
| Runs | Open5GS, free5GC, UERANSIM, dashboard, dashboard agents | OCUDU gNB (pod) |
| Local network | DHCP (the IP can change on every boot; nothing depends on it) | DHCP |
| N2/N3 fiber | `enp5s0f1` `10.10.0.2/24`, MTU 9000 | E810 port 4 `ens4f3np3` `10.10.0.1/24`, MTU 9000 |
| Other | `10.101.131.10/24` on the O-RU management network | E810 port 1 `ens4f0np0`: fronthaul (VF in DPDK) and PTP grandmaster; GNSS |

## 3. The Kubernetes cluster

- **k3s v1.36.5+k3s1**, flannel VXLAN, CoreDNS, local-path; Traefik disabled.
- **Server with a stable IP.** The server advertises `10.254.254.1` on the virtual interface `k3s0` (created at
  boot by the `open5gs-k3s-netif` unit). The cluster does not depend on the local-network IP, which changes with
  DHCP.
- **RAN node over the fiber.** The agent uses `node-ip 10.10.0.1` and `flannel-iface ens4f3np3` (never the
  fronthaul port). It reaches the server through the route `10.254.254.1/32 via 10.10.0.2` (unit
  `innovanetwork-k3s-route`).
- **Reserved node.** Label `innovanetwork/role=ran` and taint `innovanetwork/ran=true:NoSchedule`: only the gNB
  (which tolerates the taint) and system DaemonSets run there.
- **Cluster networks:** pods `10.42.0.0/16` (server `10.42.0.x`, RAN node `10.42.1.x`), services `10.43.0.0/16`.
- **Multus** (DaemonSet) adds a 2nd interface (`net1`, macvlan over the fiber port) to the pods that talk to the
  gNB: AMF, UPF and the UERANSIM gNB.
- **CPUs.** On the RAN node, the k3s processes stay on the CPUs outside those reserved for the gNB (e.g. 18–31).

## 4. Components per namespace

| Namespace | Components | Installed by |
|---|---|---|
| `open5gs` | Open5GS (NRF, SCP, AMF, SMF, UPF, AUSF, UDM, UDR, PCF, BSF, NSSF, WebUI, MongoDB, populate), UERANSIM (gNB + UEs), **dashboard** | `install.sh` (Gradiant charts + generated values) |
| `free5gc` | free5GC (NRF, AMF, SMF, UPF, AUSF, UDM, UDR, PCF, NSSF, CHF, NEF, WebConsole, MongoDB), UERANSIM | `free5gc/install.sh` (generated manifests) |
| `ocudu` | Deployment `ocudu-gnb` (0 or 1 replica) | `ran/ocudu/install.sh` |
| `kube-system` | CoreDNS, local-path, metrics-server, Multus | k3s / `install.sh` |

**One active core at a time.** Both cores can stay installed (different IPs and pools), but only one is running;
the gNB points to the AMF of one of them (one `.yml` per core). The dashboard does the switch.

Each component namespace has a descriptor ConfigMap with the label `innovanetwork/component`, so that tools (like
the dashboard) can find out what is installed.

## 5. Networks

| Network | Range | Purpose |
|---|---|---|
| Local network | DHCP | SSH/dashboard access; way out to the internet (N6) |
| **N2/N3 fiber** | `10.10.0.0/24`, MTU 9000 | NGAP (N2) and GTP-U (N3) between gNB and core; cluster traffic with the RAN node |
| O-RU management | `10.101.131.0/24` | O-RU CLI (read only, from the dashboard). **Never use a /8**: it would cover the fiber and the cluster |
| Pods / services | `10.42.0.0/16` / `10.43.0.0/16` | SBI, PFCP (N4), MongoDB, dashboard |
| Stable node | `10.254.254.1/32` (`k3s0`) | k3s API (6443) |
| O-RAN 7.2 fronthaul | VLAN 564, E810 port 1 | C/U-plane between DU and O-RU; PTP |
| UE pools | see below | IPs handed to the phones and simulated UEs |

**Only N2 and N3 leave the cluster**, with a fixed IP on the fiber (macvlan `ran-link`). The rest (SBI, N4) stays
on the pod network. **N6:** the UPF NATs the pools and goes out through the default route of the core machine.

## 6. Addresses and ports

### Per core

| | Open5GS (default) | free5GC (optional) |
|---|---|---|
| AMF — N2, SCTP 38412 | `10.10.0.10` | `10.10.0.30` |
| UPF — N3, GTP-U 2152 | `10.10.0.11` | `10.10.0.31` |
| UERANSIM gNB on the fiber | `10.10.0.20` | `10.10.0.32` |
| UE pools | `internet` 10.45/16 · `internet2` 10.46/16 | `internet` 10.60/16 · `internet2` 10.61/16 · `ims` 10.62/16 |
| Network name on the phone | `InnovaOpen5GS` | `InnovaFree5GC` |
| Subscribers (web) | WebUI `:30999` | WebConsole `:31000` |
| OCUDU gNB `.yml` (example) | `gnb_split_open5gs.yml` | `gnb_split_free5gc.yml` |

### Common

| | Value |
|---|---|
| PLMN / TAC | `001-01` / `1` |
| Slices | SST 1 / SD `111111` (`internet`) · SST 2 / SD `222222` (`internet2`) |
| OCUDU gNB | N2 and N3 on `10.10.0.1`; WebSocket metrics `:8001`; log `/tmp/gnb.log` |
| O-RU | management `10.101.131.59` |

### Ports

| Port | Service | Where |
|---|---|---|
| 30998/tcp | dashboard | core machine (NodePort) |
| 30999/tcp | Open5GS WebUI | core machine (NodePort) |
| 31000/tcp | free5GC WebConsole | core machine (NodePort) |
| 38412/sctp | N2 (NGAP) | AMF IP on the fiber |
| 2152/udp | N3 (GTP-U) | UPF IP on the fiber / gNB |
| 8805/udp | N4 (PFCP) | pod network |
| 7777/tcp · 8000/tcp | Open5GS SBI · free5GC SBI | pod network |
| 27017/tcp | MongoDB | pod network |
| 9090/tcp | NF Prometheus metrics (optional) | pod network |
| 8001/tcp | gNB metrics (WebSocket) | `10.10.0.1` |
| 6443/tcp · 10250/tcp · 8472/udp | k3s API · kubelet · flannel VXLAN | between the machines |

## 7. Network functions and 3GPP interfaces

| NF | Role |
|---|---|
| **NRF** | NF registration and discovery; holds the served PLMN |
| **SCP** | routes the SBI calls (Open5GS) |
| **AMF** | N2 with the gNB, N1 (NAS) with the UE: registration, authentication, mobility |
| **SMF** | PDU sessions, IP allocation per DNN, controls the UPF through PFCP |
| **UPF** | GTP-U (N3) ↔ IP (N6), one TUN per DNN, NAT |
| **AUSF / UDM / UDR** | 5G-AKA, subscriber profile, database access |
| **PCF / BSF / NSSF** | policies, session↔PCF binding, slice selection |
| **CHF / NEF** | charging and exposure (free5GC only) |
| **WebUI / WebConsole** | subscriber management |

| Interface | Between | Protocol | In the cluster |
|---|---|---|---|
| N1 | UE ↔ AMF | NAS (inside NGAP) | — |
| N2 | gNB ↔ AMF | NGAP / SCTP 38412 | AMF `net1` on the fiber |
| N3 | gNB ↔ UPF | GTP-U / UDP 2152 | UPF `net1` on the fiber |
| N4 | SMF ↔ UPF | PFCP / UDP 8805 | pod network (headless service, no NAT) |
| N6 | UPF ↔ internet | IP | TUN + NAT in the UPF pod → default route of the machine |
| SBI | NFs | HTTP/2 | pod network |

## 8. From the phone to the internet

1. **Radio:** the phone finds the n78 cell of the O-RU; the O-RU exchanges IQ with the OCUDU DU over the 7.2
   fronthaul (synchronized by the PTP coming from the E810, which follows the GNSS).
2. **N2:** the gNB has already done the *NG Setup* with the AMF (`10.10.0.1` → `10.10.0.10`).
3. **Registration:** Registration Request (SUCI) → AMF → AUSF/UDM/UDR → 5G-AKA with K/OPc from the database.
4. **Session:** PDU Session (DNN + S-NSSAI) → SMF → PFCP on the UPF → IP from the pool (e.g. `10.45.0.2`).
5. **Data:** GTP-U from the gNB (`10.10.0.1`) to the UPF (`10.10.0.11`) → TUN → NAT → internet.

## 9. How the dashboard sees everything

```
browser ── :30998 ──► dashboard pod (ns open5gs)
                          ├─ Kubernetes API ........... pods, logs, scaling Deployments (core, UERANSIM, gNB)
                          ├─ gNB WebSocket :8001 ...... radio metrics, 1/s
                          ├─ host /proc and /sys ...... CPU, memory, UPF traffic
                          └─◄ agents (core machine, POST with a token)
                               ├─ gnb-log ...... gNB log over SSH (tail -F, read only)
                               ├─ gnb-ctl ...... gNB state and start/stop (through ran/ocudu/gnb.sh)
                               ├─ hosts ........ CPU/temperature of the other machines over SSH
                               └─ ru ........... O-RU CLI, "show" commands only
```

Nothing of the dashboard is installed on the RAN machine besides what Kubernetes already runs.

## 10. Installed folders and services

### Core machine

| Path | Content |
|---|---|
| `~/InnovaNetwork` | this repository (configuration and scripts) |
| `/opt/open5gs-k3s/` | Gradiant charts, Helm, state (dashboard passwords, O-RU credentials, `config.env` backups) |
| `/var/lib/open5gs-k3s/dashboard/` | persistent dashboard history (SQLite) |
| `/etc/rancher/k3s/` | k3s configuration and kubeconfig |
| `helm/generated/` | generated values and manifests (not in git) |
| `logs/install.log` | installer log |

| systemd unit | Purpose |
|---|---|
| `k3s` | Kubernetes server |
| `open5gs-k3s-netif` | creates `k3s0` before k3s |
| `open5gs-k3s-heal` | at boot: leaves the cores stopped (`CORE_AUTOSTART=false`) or recovers the user plane |
| `open5gs-k3s-gnb-log` · `-gnb-ctl` · `-hosts` · `-ru` | dashboard agents |

### RAN machine

| Path | Content |
|---|---|
| `~/ocudu` | OCUDU source (the image is built from one of its commits) |
| `~/ocudu/configs/*.yml` | gNB configurations, read by the pod straight from the host |
| `~/innovanetwork-ran/` | `no-ran.sh`, `ocudu.env` and the step logs |
| `/tmp/gnb.log` | gNB log |
| `/etc/rancher/k3s/config.yaml` | k3s agent configuration |

| systemd unit | Purpose |
|---|---|
| `k3s-agent` | Kubernetes node |
| `innovanetwork-k3s-route` | route to the server over the fiber |
| `ocudu-setup`, `dpdk`, `ts2phc`, `ptp4l-gm`, `phc2sys` | machine preparation (part of the setup, not of the project) — see [hardware](hardware/e810-liteon.md) |

## 11. Design principles

| Principle | How it shows |
|---|---|
| Nothing hard-coded | every parameter comes from `config.env`, `free5gc.env` or `ocudu.env`, validated before it is applied |
| Idempotency | running an installer again only applies what changed |
| Isolated hardware | what depends on the setup stays in `ran/ocudu/` and in the hardware profile |
| One core at a time | both stay installed; the switch is done in order and checked |
| Safe at boot | only the dashboard comes up; the core and the radio are started by the operator (the GPS can take a while) |
| Configuration really applied | configuration hash on the pods: when it changes, the pod is recreated |
| Secrets out of git | SIM keys, dashboard and O-RU passwords stay in Secrets and root-owned files |
