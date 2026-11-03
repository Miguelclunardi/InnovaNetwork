<p align="center">
  <img src="dashboard/app/logo.svg" alt="InnovaNetwork" width="120">
</p>

<h1 align="center">InnovaNetwork</h1>

<p align="center">
  <b>A complete 5G Standalone network on Kubernetes</b><br>
  5G core (Open5GS or free5GC) · real OCUDU gNB (O-RAN split 7.2) · UERANSIM · web dashboard for operation and measurement
</p>

<p align="center">
  <img alt="version" src="https://img.shields.io/badge/version-3.0-1f6feb">
  <img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-blue">
  <img alt="kubernetes" src="https://img.shields.io/badge/k3s-v1.36-326ce5">
  <img alt="5G SA" src="https://img.shields.io/badge/5G-Standalone-555">
</p>

<p align="center"><a href="README.pt-BR.md">Leia em português</a></p>

---

**InnovaNetwork** builds and runs a lab 5G SA network **entirely on Kubernetes (k3s)**: the core, the real radio
gNB, the simulated gNB/UE and the dashboard run as pods of a single cluster, configured from text files and
installed by idempotent scripts.

It was built and validated at the **Innova Center** with commercial phones, a **LiteOn FlexFi** O-RU (n78, 4T4R)
and an **Intel E810** card, but it is designed to be **replicable**: everything that depends on the hardware is
isolated and documented.

## Highlights

- **Everything on Kubernetes.** Core, OCUDU gNB, UERANSIM and dashboard in the same k3s cluster, with two
  machines: one for the core and one (a dedicated node) for the radio.
- **Two cores, one at a time.** **Open5GS** (default) and **free5GC** (optional) installed side by side; switching
  is one click in the dashboard.
- **Real radio.** **OCUDU** gNB (CU+DU, split 7.2, DPDK) as a pod, with the same performance as the native service
  (~92 % of the fronthaul packets on time).
- **Operation dashboard.** *Innova Center Dashboard*: per-UE radio metrics, core, RU, machines, logs, control
  (start/stop/switch core), configuration editing, persistent history and comparable experiments. English or
  Portuguese.
- **Configuration in text, nothing hard-coded.** PLMN, slices, IPs, versions and the radio setup come from
  `config.env`, `free5gc/free5gc.env` and `ran/ocudu/ocudu.env`.
- **Safe after a reboot.** After a boot nothing on the radio starts by itself (the GPS can take minutes): the
  operator starts it from the dashboard once the sync is ready.

## Architecture

```
                         CORE machine (k3s server)                          RAN machine (k3s node)
            ┌────────────────────────────────────────────────┐     ┌──────────────────────────────────┐
            │ ns open5gs          ns free5gc (optional)      │     │ ns ocudu                         │
            │  Open5GS  AMF ─┐     free5GC  AMF ─┐           │     │  pod ocudu-gnb (OCUDU CU+DU)     │
 internet ◄─┤  (N6/NAT) UPF ─┤              UPF ─┤           │     │   host network, DPDK, PTP        │
            │  UERANSIM      │     UERANSIM      │           │     │                                  │
            │  dashboard     │                   │           │     │  E810 ── fronthaul 7.2 ──┐       │
            │  :30998  macvlan "ran-link" (N2/N3)│           │     └──────────┬───────────────┼───────┘
            └────────────────────┬───────────────┴───────────┘                │               │
                                 └────────── fiber N2/N3 + cluster ───────────┘        ┌──────┴──────┐
                                             10.10.0.0/24                              │  O-RU (n78) │ ))) phones
                                                                                       └─────────────┘
```

Details, IPs, ports and folders: **[docs/architecture.md](docs/architecture.md)**.

## Components

| Component | Version | Where it runs | Documentation |
|---|---|---|---|
| **Open5GS** (default core) | 2.7.5 | namespace `open5gs` | [components/open5gs.md](docs/components/open5gs.md) |
| **free5GC** (optional core) | v4.3.0 | namespace `free5gc` | [components/free5gc.md](docs/components/free5gc.md) |
| **UERANSIM** (simulated gNB/UE) | 3.2.6 | one pair per core | [components/ueransim.md](docs/components/ueransim.md) |
| **OCUDU** (real gNB) | commit pinned by the user | namespace `ocudu`, RAN node | [components/ocudu.md](docs/components/ocudu.md) |
| **Innova Center Dashboard** | 3.0 | namespace `open5gs`, port 30998 | [components/dashboard.md](docs/components/dashboard.md) |
| **k3s** + Multus | v1.36.5+k3s1 | both machines | [architecture.md](docs/architecture.md) |

## Quick start

**Core only, with a simulated UE** (one Ubuntu 24.04 machine, no radio), in ~15 minutes:

```bash
git clone https://github.com/Miguelclunardi/InnovaNetwork.git
cd InnovaNetwork
sudo ./install.sh        # k3s, Open5GS, UERANSIM and dashboard (idempotent)
./test.sh                # registration, PDU session and ping through the core: "7 checks OK"
```

Open the dashboard at `http://<machine IP>:30998`.

Complete network with a real radio: follow the **[installation](docs/installation.md)**.

## Documentation

| | |
|---|---|
| 🧭 **[Documentation overview](docs/README.md)** | where to start, depending on your goal |
| 🏗️ **[Architecture](docs/architecture.md)** | machines, components, networks, IPs, ports and folders |
| ⚙️ **[Installation](docs/installation.md)** | from scratch to a phone browsing the internet |
| 🕹️ **[Operation](docs/operation.md)** | day to day: start, switch core, reboot, tests |
| 🎓 **[Tutorials](docs/README.md#tutorials)** | step by step: first test, phone on the network, core switch, OCUDU on k8s, experiments… |
| 🧩 **Components** | [Open5GS](docs/components/open5gs.md) · [free5GC](docs/components/free5gc.md) · [UERANSIM](docs/components/ueransim.md) · [OCUDU](docs/components/ocudu.md) · [Dashboard](docs/components/dashboard.md) |
| 🔧 **[Reference hardware](docs/hardware/e810-liteon.md)** | Intel E810 + LiteOn FlexFi: PTP/GNSS, DPDK, XDP, n78 cell |
| 🩺 **[Troubleshooting](docs/troubleshooting.md)** | symptom → cause → fix |
| 🛠️ **[Development](docs/development.md)** | code map and how to extend it |

The same documentation is shown in the dashboard, in the **Documentation** tab (in Portuguese too: every document
has a `*.pt-BR.md` translation).

## Repository layout

```
InnovaNetwork/
├── install.sh · uninstall.sh · test.sh   # Open5GS core + UERANSIM + dashboard (core machine)
├── config.env                            # main configuration
├── free5gc/                              # optional free5GC core (own installer)
├── ran/ocudu/                            # OCUDU gNB on Kubernetes (own installer, depends on the setup)
├── dashboard/                            # dashboard (app/), core-machine agents (agent/), translations (i18n/)
├── scripts/                              # installer library, boot recovery, subscribers
├── helm/                                 # Multus and chart post-renderers
└── docs/                                 # documentation (English; Portuguese in *.pt-BR.md)
```

## Requirements

| | Core machine | RAN machine (optional) |
|---|---|---|
| OS | Ubuntu 24.04 LTS | Ubuntu 24.04 LTS, low-latency kernel |
| CPU / RAM | 4+ vCPU with AVX · 8 GiB | isolated CPUs for the gNB · 1 GiB hugepages |
| Network | internet; dedicated port for the N2/N3 fiber | NIC with SR-IOV/DPDK and PTP (e.g. Intel E810) + GNSS |
| Radio | — | O-RAN 7.2 O-RU (e.g. LiteOn FlexFi) |

## Versions

| Version | Content |
|---|---|
| **v3.0** | OCUDU on Kubernetes (dedicated node), dashboard controlling the gNB through Kubernetes, new documentation |
| v2.x | two cores (Open5GS + free5GC), switched from the dashboard |
| v1.x | Open5GS core on k3s with UERANSIM; dashboard |

Full history: [CHANGELOG.md](CHANGELOG.md).

## Contributing

Contributions are welcome: new hardware profiles, fixes and documentation. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache License 2.0](LICENSE). The projects used (Open5GS, free5GC, UERANSIM, OCUDU, k3s, Gradiant charts,
uPlot) keep their own licenses.

> **Responsible use:** use a test PLMN (`001-01`) and follow the spectrum regulations of your region when
> transmitting with a real radio.
