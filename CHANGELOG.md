# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Every version has a Git tag.

## [Unreleased]

### Changed
- **English everywhere:** documentation, commands, script output and code comments are in English. Every
  document keeps a Portuguese translation (`*.pt-BR.md`). Docs renamed to English paths (`docs/architecture.md`,
  `docs/components/`, `docs/tutorials/`…).
- **Dashboard in English or Portuguese:** EN/PT button at the top (or `?lang=pt` / `?lang=en`); translations in
  `dashboard/i18n/pt.json`. The Documentation tab opens the `*.pt-BR.md` version in Portuguese mode.
- `ran/ocudu/gnb.sh`: commands `start`/`stop`/`status` (the Portuguese `iniciar`/`parar`/`estado` still work).
- State codes sent by the dashboard API are in English (`running`/`stopped`/`starting`/`stopping`; GPS
  `locked`/`searching`/`adjusting`/`unlocked`/`stalled`; UE `registered`/`deregistered`).
- English option names, with the Portuguese ones kept as aliases: `free5gc/install.sh --subscribers`,
  `--import-open5gs`, `--stopped`, `--no-ueransim`; `ran/ocudu/install.sh copy|prepare|--remove`;
  `ran/ocudu/no-ran.sh image|import|join|leave|status`. Script prefixes are now `[warn]` and `[error]`.
- The Open5GS and UERANSIM values hashes ignore comments, so editing a comment no longer recreates pods.
  **Once**, at the first `--deploy-only` after this change, the core and the UEs are recreated (new hash
  formula) — run it in a window without users.
- `install.sh` no longer restarts k3s when only comments of its config file change.
- The gNB pod script text changed (English boot message): the next `./ran/ocudu/install.sh` recreates the
  gNB pod.

## [3.0] — 2026-10-28 · tag `v3.0-innovanetwork`

### Added
- **OCUDU gNB on Kubernetes** (`ran/ocudu/`): image built from the OCUDU commit with the official Dockerfile;
  the RAN machine joins the cluster as a dedicated node (label and taint); Deployment with host network, DPDK and
  hugepages; `gnb.sh` to start/stop/follow the logs.
- **gNB boot protection:** after a node reboot the gNB does not start by itself (it waits for the operator, after
  the GNSS).
- **Dashboard controls the gNB through Kubernetes** (`GNB_CTL_MODE=k8s`): "gNB (Kubernetes)" card; a core switch
  restarts the pod on the right AMF.
- New documentation: architecture, installation, operation, components, reference hardware, 8 tutorials,
  troubleshooting and development guide. Apache-2.0 license, `CONTRIBUTING.md`.

### Changed
- The OCUDU gNB no longer runs as a systemd service of the host (the `systemd` mode is still available as legacy).

### Validated
- Open5GS and free5GC with commercial phones through the gNB on Kubernetes; fronthaul ~92 % on time (same as
  native); reboot of the RAN node with automatic return to the cluster.

## [2.1] — 2026-10-26 · `v2.1-innovanetwork`
- Reference state with two cores and the native gNB; radio lessons (GNSS/PTP, XDP).

## [2.0] — 2026-10-26 · `v2.0-innovanetwork`
- **Two cores:** optional free5GC v4.3.0 next to Open5GS; the active core is switched from the dashboard, which
  restarts the gNB.
- Single administrator login; Documentation tab.

## [1.0 – 1.4] — 2026-10-21 to 22 · `v1.0-ueransim`, `v1.0-dashboard` … `v1.4-dashboard`
- Open5GS core on k3s with UERANSIM, idempotent installer, `config.env`, end-to-end test.
- *Innova Center Dashboard*: radio, core, logs, RU, machines, control, configuration, history and experiments.
- Link to the real OCUDU gNB over the fiber (Multus/macvlan for N2/N3).
