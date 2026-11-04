# InnovaNetwork documentation

Start from your goal:

| I want to… | Read |
|---|---|
| understand what it is and how the pieces fit together | [Architecture](architecture.md) |
| test the core on one machine, without a radio | [Tutorial 1 — First test with UERANSIM](tutorials/01-first-test-ueransim.md) |
| build the complete network with a real radio | [Installation](installation.md) |
| run the network day to day | [Operation](operation.md) |
| solve a problem | [Troubleshooting](troubleshooting.md) |
| change or extend the code | [Development](development.md) |

## Guides

| Document | Content |
|---|---|
| [architecture.md](architecture.md) | machines and roles, components, networks (cluster, fiber, fronthaul), IPs, ports, folders, the path of a call |
| [installation.md](installation.md) | requirements and installation order: core and dashboard → free5GC (optional) → OCUDU on Kubernetes |
| [operation.md](operation.md) | after a boot, start/stop, switch core, subscribers, change the configuration, tests |
| [troubleshooting.md](troubleshooting.md) | known cluster, core, radio and dashboard problems, with cause and fix |
| [development.md](development.md) | code map, the path of a configuration value, how to extend cores, gNB and dashboard |

## Components

| Document | Content |
|---|---|
| [components/open5gs.md](components/open5gs.md) | default core: functions, installer, `config.env` reference, PLMN, slices, subscribers, versions |
| [components/free5gc.md](components/free5gc.md) | optional core: installation, subscribers, phones, limitations |
| [components/ueransim.md](components/ueransim.md) | simulated gNB and UE: how they are installed, `nr-cli`, tests |
| [components/ocudu.md](components/ocudu.md) | real gNB on Kubernetes: image, RAN node, Deployment, one `.yml` per core, boot protection |
| [components/dashboard.md](components/dashboard.md) | Innova Center Dashboard: tabs, configuration, agents, history, languages, API |
| [hardware/e810-liteon.md](hardware/e810-liteon.md) | reference profile: Intel E810, PTP/GNSS, DPDK, XDP, LiteOn O-RU, n78 cell |

## Tutorials

Step by step, from start to finish, with the expected result of each step.

| # | Tutorial | Time |
|---|---|---|
| 1 | [First test with UERANSIM](tutorials/01-first-test-ueransim.md) — install the core and see a UE browsing | 20 min |
| 2 | [Dashboard tour](tutorials/02-dashboard-tour.md) — login, tabs and what each one shows | 15 min |
| 3 | [OCUDU on Kubernetes](tutorials/03-ocudu-on-kubernetes.md) — image, RAN node and the gNB as a pod | 1 h |
| 4 | [Phone on the network](tutorials/04-phone-on-the-network.md) — register the SIM, start the gNB and connect | 20 min |
| 5 | [Switch core](tutorials/05-switch-core.md) — install free5GC and switch from the dashboard | 30 min |
| 6 | [Change PLMN, slices and IPs](tutorials/06-change-configuration.md) — edit and apply the configuration | 15 min |
| 7 | [Change the gNB](tutorials/07-change-the-gnb.md) — edit the `.yml` or rebuild OCUDU | 30 min |
| 8 | [Record and compare experiments](tutorials/08-experiments.md) — measure two setups in the dashboard | 20 min |

## Conventions

- **Core machine** = the k3s server (in the reference setup, `torre2`). **RAN machine** = the k3s node with the
  radio (in the reference setup, `innovaserver`). Each command says which machine it runs on.
- `sudo` only where stated. The other commands run as a regular user, inside the repository folder.
- Example values (IPs, interface names, `.yml`) are those of the reference setup; adjust them to yours.
