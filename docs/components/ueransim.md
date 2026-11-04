# UERANSIM — simulated gNB and UE

**UERANSIM 3.2.6** simulates a 5G gNB and UEs in software. In InnovaNetwork, each core has its own gNB + UEs pair,
used to test the core **without a radio**: registration, authentication, PDU session and traffic.

| | Open5GS | free5GC |
|---|---|---|
| Namespace | `open5gs` | `free5gc` |
| Deployments | `ueransim` (gNB) and `ueransim-ues` | `ueransim` and `ueransim-ues` |
| gNB on the fiber | `10.10.0.20` | `10.10.0.32` |
| Installed by | `install.sh` (Gradiant chart `ueransim-gnb`) | `free5gc/install.sh` |
| Automatic test | `./test.sh` | `./free5gc/test.sh` |

## 1. How it works

```
pod ueransim-ues                pod ueransim (gNB)                       core
  UE imsi-…9001  ── RLS/UDP 4997 ──►  gNB  ── N2 SCTP 38412 (net1 10.10.0.20) ──► AMF 10.10.0.10
  uesimtun0 = 10.45.0.x               │
                                      └── N3 GTP-U 2152 ─────────────────────────► UPF 10.10.0.11
```

- The simulated gNB uses the **same fiber** as the real gNB (interface `net1`), so it tests the same N2/N3 path.
- Each UE gets a `uesimtunN` interface inside the pod; traffic through it really goes through the core.
- The simulated gNB advertises the **1st slice** of `SLICES`. To test another one, put it first.

## 2. Configuration

In `config.env`:

| Variable | Default | Purpose |
|---|---|---|
| `DEPLOY_UERANSIM` | `true` | `false` removes the simulated gNB and UEs |
| `GNB_SIM_IP` | `10.10.0.20` | simulated gNB IP on the fiber |
| `UE_COUNT` | `1` | number of simulated UEs |
| `UE_MSIN_START` | `0000009001` | first MSIN (consecutive IMSIs, far from the real SIMs) |
| `UE_KEY`, `UE_OPC` | public UERANSIM test keys | registered automatically in the core |
| `UERANSIM_IMAGE_TAG` | empty (3.2.6) | change the image |

In free5GC: `F5_DEPLOY_UERANSIM`, `F5_GNB_SIM_IP`.

The simulated UEs are registered in the core automatically (Open5GS and free5GC) at every installation.

## 3. Use

```bash
kubectl -n open5gs exec -it deploy/ueransim-ues -- bash
```

Inside the pod:

```bash
nr-cli -d                                         # lists the UEs
nr-cli imsi-001010000009001 --exec status         # MM-REGISTERED/NORMAL-SERVICE?
nr-cli imsi-001010000009001 --exec ps-list        # PDU sessions
ip addr show uesimtun0                            # UE IP
ping -I uesimtun0 8.8.8.8                         # traffic through the core (N3 → UPF → N6)
curl --interface uesimtun0 https://example.com
nr-cli imsi-001010000009001 --exec "deregister normal"
```

gNB state:

```bash
kubectl -n open5gs exec deploy/ueransim -- sh -c 'nr-cli $(nr-cli -d) --exec status'
```

## 4. Automatic test

`./test.sh` (Open5GS) checks, in order:

```
==> Pods in namespace open5gs              [ok] all pods Running/Ready
==> NRF                                    [ok] NRF registered 9 NF(s)
==> N2: NG Setup                           [ok] gNB did NG Setup with the AMF
==> UEs: registration and PDU session      [ok] registered (MM-REGISTERED/NORMAL-SERVICE)
                                           [ok] PDU session active, uesimtun0 = 10.45.0.x
                                           [ok] ping 10.45.0.1 (gateway on the UPF)
                                           [ok] ping 8.8.8.8 via uesimtun0
RESULT: 7 checks OK, 0 failures
```

The ping to the gateway tests the user plane (N3) without depending on the internet; the external ping tests
N6/NAT. `-v` shows the AMF, SMF, UPF, gNB and UE logs on failure. Exit code 0/1, useful for automation.

### Traffic test on all UEs

`./scripts/ue-traffic.sh` generates traffic on **all** UEs at the same time, with iperf3: one server per UE
on the core machine (ports 5301, 5302, …) and one client on each `uesimtunN`. The traffic crosses the whole
user plane (UE → gNB → UPF → N6 → core machine) and does not depend on the internet. It prints each UE's
throughput every 2 s and a `TOTAL` per UE at the end; watch the **Core** tab (UPF traffic) while it runs.

```bash
./scripts/ue-traffic.sh 60                 # 60 s download, 20 Mbit/s per UE
./scripts/ue-traffic.sh 60 up              # upload (or: both)
TRAFFIC_RATE=50M ./scripts/ue-traffic.sh   # another rate per UE
```

Needs `iperf3` on the core machine (`sudo apt install iperf3`); the UE image already has it. Public speed-test
servers are not used on purpose: all UEs leave through the same public IP (NAT) and get blocked (HTTP 429).

## 5. In the dashboard

- **Overview**: the simulated UEs show marked as **UERANSIM**, separate from the real SIMs.
- **Control**: start/stop/restart the UERANSIM of the active core; **Start all** checks the NG Setup of the
  simulated gNB.
- **Logs**: `ueransim` and `ueransim-ues`.

## 6. Common problems

| Symptom | Cause / fix |
|---|---|
| UE in `MM-DEREGISTERED/LIMITED-SERVICE` | UERANSIM race with SIB1: `kubectl -n open5gs rollout restart deploy/ueransim-ues` |
| `no cells in coverage` | host firewall blocking pod↔pod (firewalld): run `sudo ./install.sh` |
| registration OK, ping fails after a reboot | SMF↔UPF PFCP out of sync: `./scripts/heal.sh` or restart the UPF from the dashboard |
| simulated gNB without NG Setup | AMF stopped or restarted after the gNB: restart UERANSIM |

More: [troubleshooting.md](../troubleshooting.md).
