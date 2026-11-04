# Dashboard — Innova Center Dashboard

A web page that runs **in the core cluster itself** (core machine) and brings the whole of InnovaNetwork into one
place: radio, RU, machines and **the active core** (Open5GS or free5GC — see
[Active core](#active-core-open5gs--free5gc)).

> Step-by-step usage guide: [tutorial 2 — Dashboard tour](../tutorials/02-dashboard-tour.md).
> Experiments: [tutorial 8](../tutorials/08-experiments.md).

| Tab | What it shows | Where it comes from |
|---|---|---|
| **Documentation** | the project `.md` documents (README, `docs/`, `free5gc/`), with search, the branch and commit in use and a link to GitHub | project folder mounted read-only in the pod |
| **Overview** | UEs on the radio (throughput, MCS, CQI, RI, BLER, SNR), subscribers seen by the core (registration, DNN → IP sessions), pods (state, restarts, IP, RAN-link IP), core events (identical warnings/errors grouped with a counter) | gNB metrics + Kubernetes API + AMF/SMF/UPF logs |
| **Radio (gNB)** | UEs identified by **name, IMSI, IP and type** (real SIM / UERANSIM), not only RNTI; RNTIs idle for more than 2 min are hidden ("Show old" button); cell throughput and PRBs; DL/UL throughput per UE; for the chosen UE: BLER, MCS, CQI/rank, PUSCH SNR/RSRP, buffers, TA/PHR; scheduler latency and failures (late HARQ, PDCCH, UCI). 1/5/15 min window, pause, CSV export | gNB metrics WebSocket (OCUDU `remote_control`) |
| **Logs** | log of any pod/container of the namespace (core and UERANSIM) and of the **real gNB**; live, filter by text or `/regex/`, filter by level, colors, download | Kubernetes API; gNB log agent |
| **RU** | LiteOn FlexFi O-RU: PTP sync, RF, DPD, DU connected; power and temperature (radio and CPU); fronthaul U-plane packets (received, early, late); management ports; firmware; radio configuration (frequency/NR-ARFCN, band, SCS, 4T4R, power, compression, VLAN, DU MAC); state changes | SSH to the RU management port (RJ45), `show` commands only |
| **Control** | start / stop / restart each core function and UERANSIM; "Start all" in order, with checks (fiber, PFCP, NG Setup); OCUDU gNB: choose the `.yml`, start, stop, restart, see PTP, the DPDK VF and the pod output. Actions need the administrator password | Kubernetes API (scaling/pods) + `gnb-ctl` agent |
| **Machines** | list of the machines (core and gNB) with CPU, memory and temperature; on click: CPU per core (isolated ones highlighted), load, hugepages, CPU/temperature/memory/network charts, top CPU processes, temperatures, disks and interfaces | `/proc` and `/sys` (core: mounted in the pod; others: SSH) |
| **History** | **persistent** metrics (radio 1 s, core, machines, energy, events) of any period; **experiments** ("● Record experiment" button at the top) with name, notes and a snapshot of the setup; side-by-side **comparison** of 2+ experiments (KPIs with the best highlighted + overlaid charts); CSV export | SQLite in `/var/lib/open5gs-k3s/dashboard` (`DASHBOARD_PERSIST=true`) |
| **Settings** | edits `config.env` (administrator password): fields per section with the file's own explanation, diff before saving, installer validation, backup and restore, and the command to apply | `config.env` of the core machine |
| **Core** | always: gNBs, registered UEs, sessions, UE traffic at the UPF per DNN (N6) and on the gNB link (N3), CPU/memory/threads of each NF, errors/warnings per NF, UPF interfaces. Optional: NF Prometheus metrics | host `/proc` (`open5gs-*d` processes and UPF interfaces) + logs; Prometheus only with `OPEN5GS_METRICS=true` |
| **Slices** | one card per slice (DNN, SST/SD, sessions, UPF downlink/uplink now, share of the traffic, totals); DL/UL charts per slice; a **UE × slice** table (IP of each session, UEs in 2+ slices marked, radio rate per UE); refused session requests per slice (e.g. phones asking for `ims`) | `SLICES` of `config.env` + AMF/SMF logs + UPF tunnel counters (host `/proc`) |

Address: `http://<core-IP>:30998` (`DASHBOARD_NODEPORT`). No password by default; with `DASHBOARD_PASSWORD`, the
browser asks for user `admin` and the password.

### Language (English / Portuguese)

The **EN/PT** button at the top switches the language; the choice is remembered by the browser (`localStorage`).
The first time, the dashboard follows the browser language. A link can force it: `http://<core-IP>:30998/?lang=pt`
or `?lang=en`.

- The page is written in English; the Portuguese mode translates the page in the browser (`app/i18n.js`, built
  from `dashboard/i18n/pt.json` — see [development](../development.md#dashboard-texts-and-translations)).
- Logs, code and the documentation are not translated (they are in English).
- Dates and times follow the language (`pt-BR` or `en-GB` format).

### Administrator login (one for every tab)

The **🔒 Admin** button at the top opens the login. The session (8 h) is valid for **every dashboard tab**
(Control, Settings) and for the other tabs/windows of the same browser (stored in `localStorage`, synchronized by
the `storage` event). **🔓 Admin · Sign out** ends the session everywhere. If the dashboard restarts, the sessions
are dropped and the button goes back to 🔒 by itself (`GET /api/admin` checks the token when the page opens).

### Active core (Open5GS / free5GC)

The dashboard knows both cores: Open5GS (namespace from `config.env`) and, if `free5gc/free5gc.env` exists,
free5GC (the installer passes `FREE5GC_NAMESPACE`, `FREE5GC_AMF_IP`, `FREE5GC_UPF_IP`, `FREE5GC_WEBUI_PORT`,
`FREE5GC_NETWORK_NAME` and `FREE5GC_POOLS` to the pod). **Active core** = the only one with a running AMF; if both
or none are running, the last one chosen wins (stored in `core-ativo.json`, next to the history).

- Every tab follows the active core: the top pill with the core name, functions and logs (grouped per core),
  subscribers (Open5GS WebUI or free5GC WebConsole), sessions, UPF traffic (`ogstun*` or `upfgtp`). Radio, RU,
  Machines and History do not change; each experiment records the core.
- **Control** tab → **Active core** card (only with both installed): clicking the other core opens the switch. The
  dashboard stops the OCUDU gNB (if asked) → stops the current core → marks the new one → brings the new one up in
  order, checking each step → restarts the gNB with the chosen `.yml` (only those pointing to the AMF of the new
  core are offered).
- Permissions in the free5GC namespace: Role/RoleBinding `innovanetwork-dashboard` (created by
  `free5gc/install.sh`) for the dashboard ServiceAccount — read pods/logs, scale Deployments, delete pods.
- Boot: `heal.sh --boot-off` also stops every namespace with the `innovanetwork/core` label.

**Nothing of the dashboard runs on the gNB machine.** The dashboard *pulls* the gNB metrics over the WebSocket,
and the agents (on the core machine) read the log over SSH (`tail -F`, read only) and control the gNB through
Kubernetes.

## Architecture

```
 core machine                                                     RAN machine
┌──────────────────────────────────────────────────────────┐     ┌─────────────────────────────┐
│ k3s, namespace open5gs                                   │     │ OCUDU gNB                   │
│  ┌──────────────────────┐  k8s API (read only)           │     │  remote_control :8001 (WS) ◄──── metrics (1/s)
│  │ pod dashboard        │◄──── pods, NF logs             │     │  log: /tmp/gnb.log ◄─────────┐
│  │ python:3.12-slim     │◄──── :9090/metrics (optional)  │     └─────────────────────────────┘│
│  │ server.py (stdlib)   │──────────────────────────────────────────────── ws://10.10.0.1:8001 │
│  └──────────▲───────────┘                                │                                    │
│      NodePort 30998  ▲ POST /api/ingest/gnb-log (token)  │                                    │
│                      │                                   │                                    │
│  unit open5gs-k3s-gnb-log (installer user) ──── ssh user@10.10.0.1 tail -F ───────────────────┘
└──────────────────────────────────────────────────────────┘
```

- **Backend** (`dashboard/app/server.py`): Python standard library only; no `pip install`. Keeps the last
  `DASHBOARD_HISTORY_SECONDS` (default 15 min) in memory. Restarting the pod clears that history.
- **Page** (`index.html`, `app.js`, `style.css`, `i18n.js`) + **uPlot 1.6.31** (charts, MIT license, stored in the
  repository — works without internet).
- **Kubernetes**: ConfigMap `dashboard-app` (the files), Secret `dashboard` (password and token), ServiceAccount
  with a Role limited to `get/list/watch` on `pods` and `pods/log`, Deployment (user 65534, read-only file
  system, no capabilities), NodePort Service. Everything generated in `helm/generated/dashboard.yaml`.
- **gNB log agent** (`dashboard/agent/gnb-log-agent.py`): unit `open5gs-k3s-gnb-log`, runs as the installer user
  (uses their SSH key), reconnects by itself, drops lines by regex (`GNB_LOG_DROP`) **before** sending them and
  buffers up to 50,000 lines if the dashboard is down.

## Install / update

The dashboard is part of `install.sh` (the step after UERANSIM). To bring up **only the dashboard**, without
touching the core, UERANSIM or the gNB — safe with users on the network:

```bash
sudo ./install.sh --dashboard-only
```

The full installation (`sudo ./install.sh` or `--deploy-only`) also brings the dashboard up. With
`OPEN5GS_METRICS=false` the core values do not change, so the core does **not** restart because of the dashboard.

Changed the page or `config.env`? Run `--dashboard-only` again: the hash of the files goes into the pod
annotation, and the pod restarts by itself.

## Configuration (`config.env`)

| Variable | Default | Purpose |
|---|---|---|
| `DASHBOARD_ENABLED` | `true` | on/off (off removes the objects and the agent unit) |
| `DASHBOARD_NODEPORT` | `30998` | port (30000–32767); opened in UFW/firewalld like the WebUI |
| `DASHBOARD_IMAGE` | `python:3.12-slim` | base image |
| `DASHBOARD_PASSWORD` | empty | password (user `admin`); empty = open |
| `DASHBOARD_HISTORY_SECONDS` | `900` | chart history (60–21600 s) |
| `GNB_METRICS_URL` | `ws://10.10.0.1:8001` | gNB metrics WebSocket; empty = no Radio tab |
| `GNB_NAME` | `OCUDU + LiteOn` | displayed name |
| `GNB_LOG_SSH` | empty | gNB `user@host` for the log agent; empty = no gNB log |
| `GNB_LOG_FILE` | `/tmp/gnb.log` | the `log: filename:` file of the gNB config |
| `DASHBOARD_LOCAL_ROLE` | `Core 5G (k3s)` | role of this machine in the Machines tab |
| `DASHBOARD_HOSTS` | `name\|user@host\|role` | other machines (read over SSH) |
| `DASHBOARD_UE_NAMES` | `001010000000022:Modem Telit FN990` | SIM nicknames; the UERANSIM ones are marked automatically |
| `GNB_LOG_DROP` | `\[PHY *\] \[I\]` | regex of dropped lines; empty = send everything |
| `OPEN5GS_METRICS` | `false` | Prometheus on the NFs (Core tab). **Changing it restarts the core** on the next install |
| `DASHBOARD_CONFIG_EDIT` | `true` | Settings tab and administrator password |
| `DASHBOARD_CONTROL` | `true` | Control tab (needs `DASHBOARD_CONFIG_EDIT`) |
| `CORE_AUTOSTART` | `false` | `false` = at boot only the dashboard comes up; the core is started from the Control tab |
| `GNB_CTL_MODE` | `k8s` | how the gNB card controls OCUDU: `k8s` (pod) or `systemd` (native service) |
| `GNB_CTL_SSH`, `GNB_CTL_DIR` | `user@10.10.0.1`, OCUDU folder | access to the gNB node and folder of the `configs/*.yml` |
| `DASHBOARD_PERSIST`, `…_DAYS`, `…_MAX_GB` | `true`, `365`, `50` | persistent history (History tab) |
| `RU_MGMT_IP`, `RU_SSH_USER`, `RU_MGMT_LOCAL_CIDR`, `RU_POLL_SECONDS` | `10.101.131.59`, `user`, `10.101.131.10/24`, `10` | RU tab |
| `ENERGY_METER_URL`, `ENERGY_METER_HOST` | empty | energy meter (optional) |

### gNB metrics (OCUDU)

The gNB needs `remote_control` enabled (which is what `metricas.yml` does):

```yaml
metrics:
  autostart_stdout_metrics: true
  enable_json: true
remote_control:
  enabled: true
  bind_addr: 0.0.0.0
  port: 8001
```

The dashboard sends `{"cmd":"metrics_subscribe"}` and receives one message per second with
`cells[].cell_metrics`, `cells[].ue_list[]` and `du.du_high.mac.dl[]`. If the gNB goes down, the dashboard
reconnects by itself (growing wait, up to 30 s).

**BLER**: the gNB reports OK/NOK blocks per period; the dashboard computes `NOK / (OK + NOK)`. In the charts it is
per second; in the cards and tables it covers the **last 10 s** (with few blocks the 1 s value swings too much —
hover to see how many blocks were counted). Without transmission in the period, MCS/SNR become a gap instead of 0.

### Who each UE on the radio is (RNTI → name/IMSI/IP)

The gNB only reports the **RNTI** (temporary radio number, changes on every connection). The dashboard combines
three sources:

```
gNB log   [RRC]  ue=62 c-rnti=0x4c22          (RNTI 19490 -> CU-CP UE 62)
gNB log   [NGAP] ue=62 ran_ue=53 amf_ue=55    (UE 62 -> AMF_UE_NGAP_ID 55)
AMF log   [suci-0-001-01-…-0000000040] … AMF_UE_NGAP_ID[55]   (-> IMSI 001010000000040)
SMF log   UE SUPI[imsi-001010000000040] DNN[internet] IPv4[10.45.0.5]
```

- It needs the **gNB log** enabled (`GNB_LOG_SSH`). Without it the cards show only the RNTI and a notice.
- When the dashboard starts, the agent looks for recent links in the last 300 MB of the log (`IDENT_BYTES`, with
  `nice`); after that, each UE is identified on its next message exchange with the core (registration, NAS,
  session).
- The name comes from `DASHBOARD_UE_NAMES`; the type (real SIM/UERANSIM) from the IMSIs generated for UERANSIM.
- It only works with unencrypted SUCI (null scheme, the case of test SIMs) or when the AMF has already written
  `[imsi-…]` right after the `AMF_UE_NGAP_ID`.

### Real gNB log

1. SSH key of the installer user (on the core machine) to the gNB, **passwordless**:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ''          # if you do not have one yet
   ssh-copy-id user@10.10.0.1                                 # asks for the password once
   ssh -o BatchMode=yes user@10.10.0.1 test -r /tmp/gnb.log && echo ok
   ```
2. `GNB_LOG_SSH="user@10.10.0.1"` in `config.env` and `sudo ./install.sh --dashboard-only`.
3. **Logs → gNB (real)** tab. Agent state: `journalctl -u open5gs-k3s-gnb-log -f`.

Volume: with `all_level: info` OCUDU writes ~100 kB/s **when idle** (≈600 lines/s, almost all `[PHY] [I]`), and
much more with traffic. The default filter lets MAC, RRC, NGAP, warnings and errors through. The dashboard keeps
the last 20,000 gNB lines.

> The OCUDU file `/tmp/gnb.log` grows without limit (GBs per day at `info` level). This is the gNB, not the
> dashboard: rotate it or lower `all_level`.

### Open5GS WebUI inside the dashboard (Core tab → Subscribers)

The Core tab has two views: **Metrics** and **Subscribers (Open5GS WebUI)**. The second shows the original WebUI
(`WEBUI_NODEPORT`, login `admin`) in a frame inside the dashboard — subscriber management, slices, QoS — without
opening another tab. The frame uses the same address the dashboard was opened with, changing only the port. It
disappears when `WEBUI_ENABLED=false`.

### Core metrics (Core tab)

Without restarting anything: the dashboard pod already mounts the host `/proc` (read only). It finds the
`open5gs-<nf>d` processes and `mongod` (CPU, memory, threads) and reads the interfaces **inside the UPF network
namespace** (`/proc/<upf-pid>/net/dev`): `ogstun*` = N6 per DNN (rx = uplink, tx = downlink), `net1` = N3 (GTP-U
with the gNB), `eth0` = pod network. Errors/warnings per NF come from the AMF/SMF/UPF logs.

**Prometheus (optional):**

`OPEN5GS_METRICS=true` + `sudo ./install.sh --deploy-only` turns on `metrics.enabled` in the AMF, SMF, UPF and
PCF charts (port 9090, `/metrics`). **It restarts those NFs once** — do it in a window without users. Without it,
the Core tab explains how to enable it, and the Overview keeps showing gNBs, UEs and sessions taken from the logs.

### Machines tab

- **Core machine**: the pod mounts the host `/proc`, `/sys` and `/` **read only** and reads them with
  `dashboard/app/hoststats.py`.
- **Other machines** (`DASHBOARD_HOSTS`, format `name|user@host|role`): the `open5gs-k3s-hosts` unit (core
  machine, installer user) opens one SSH session per machine and sends `hoststats.py` on the standard input
  (`ssh host nice -n 19 python3 - --loop 2`). **Nothing is installed** on the remote machine; the process reads
  `/proc` and `/sys` every 2 s with the lowest priority and goes away when the session drops. It uses the same SSH
  key as the gNB log.
- Without the key, the machine shows as "no data" with the reason. State: `journalctl -u open5gs-k3s-hosts -f`.
- Isolated cores (`isolcpus`, e.g. 0–17 of the gNB) have a blue background; a gNB core at 100 % is normal (DPDK
  loop).

### Slices tab

Shows how each network slice is used. It needs nothing extra: it reads what the dashboard already collects.

- **Which slices exist**: `SLICES` of `config.env` (the installer passes them to the pod as the `SLICES`
  variable, `SST:SD:DNN:CIDR:TUN;…`). Each slice has its own DNN and, in Open5GS, its own UPF tunnel
  (`ogstun`, `ogstun2`…).
- **Who is in each slice**: the PDU sessions taken from the SMF log (IMSI, DNN, IP). The AMF log line
  `UE SUPI[imsi-…] DNN[…] S_NSSAI[SST:… SD:0x…]` gives the slice the UE asked for each DNN; if it differs from the
  slice configured for that DNN the table shows **other S-NSSAI**.
- **Traffic per slice**: the counters of the slice's UPF tunnel (rx = uplink, tx = downlink), sampled every 2 s.
  It is exact per slice because one tunnel carries one DNN. With **free5GC** every DNN goes through one gtp5g
  device (`upfgtp`), so the tab shows sessions but no traffic per slice.
- **Radio rate**: the gNB measures per UE, not per slice. A UE with sessions in two slices (e.g. the Telit with
  `internet` and `internet2`) shows the same radio rate in both rows, marked **shared**; the UPF numbers are the
  ones split per slice.
- **Refused session requests**: `create_sm_context failed()` in the AMF log after a new session request, counted
  per slice and DNN since the AMF pod started. Phones ask for the `ims` DNN (voice) every minute or so; there is
  no `ims` pool in the SMF, so these are refused — harmless, and listed apart from the configured slices.

API: `GET /api/slices?window=300`.

### RU tab (LiteOn FlexFi)

The RU has its own CLI over SSH on the **RJ45 management** port (factory IP `10.101.131.59/24`, manual "User guide
LITEON FlexFi Indoor FR1", sections 5.1.2 and 5.2). The `open5gs-k3s-ru` unit (core machine, installer user)
keeps **one** session open and, every `RU_POLL_SECONDS`, runs read-only commands: `show oru-status`,
`show sync-trace`, `show pm-data`, `show eth-info`, `show uptime`; every 5 min also `show fw-info`,
`show running-config`, `show dl-ul-layer`, `show system`. The agent refuses any command that does not start with
`show`. The RU only accepts a password (not a key), which is why the agent uses a pseudo-terminal.

- **Network**: the RU is on the 10.101.131.0/24 network, on the same switch as the core machine. The agent adds an
  extra IP (`RU_MGMT_LOCAL_CIDR`, default `10.101.131.10/24`) to the `RU_MGMT_IFACE` interface (empty = the main
  interface) before starting (`ExecStartPre=+ip addr replace`), so it comes back by itself after a reboot.
  **Never a /8**: 10.0.0.0/8 would cover the fiber (10.10.0.0/24) and the k3s networks (10.42/10.43).
- **Passwords out of git**: file `/opt/open5gs-k3s/state/ru-credentials` (root, user group, 0640):
  ```bash
  printf 'RU_PASS=%s\nRU_ENABLE=%s\n' 'SSH_PASSWORD' 'ENABLE_PASSWORD' | \
    sudo install -m 0640 -g "$(id -gn)" /dev/stdin /opt/open5gs-k3s/state/ru-credentials
  sudo systemctl restart open5gs-k3s-ru
  ```
  Without the file the unit does not start (the installer warns about it). Password rejected: the agent waits
  5 min before trying again (so that the RU does not lock the user).
- **What it means**: `DuConnected notReady` with the gNB stopped is normal. `Sync` other than `SYNCHRONIZED` = PTP
  without a grandmaster (the RU does not transmit correctly). "Outside the window" = U-plane packets that arrived
  early or late relative to the RU reception window (a timing problem in the fronthaul or in the DU).
- The fronthaul (C/U-plane, VLAN `Control and User Plane vlan`) goes through the SFP+ straight to the FPGA: it does
  **not** show on the `eth0`/`eth1` ports, only in the PM counters.
- History: series `ru` (power, temperatures, counters, 0/1 states) and `ru` events; the setup snapshot of each
  experiment includes the RU firmware and configuration, and the comparison shows power, temperature, packets
  outside the window and % of the time synchronized / with a DU.
- Agent state: `journalctl -u open5gs-k3s-ru -f`. Manual test of one reading (does not send to the dashboard):
  `RU_TARGET=user@10.101.131.59 RU_PASS=... RU_ENABLE=... python3 dashboard/agent/ru-agent.py --once`.

### Control tab (start / stop / restart)

`DASHBOARD_CONTROL=true` (needs `DASHBOARD_CONFIG_EDIT=true`: it uses the same administrator password). Viewing
the state is open; each action asks for the password.

**Core and UERANSIM** (dashboard pod, Role `dashboard-control`: scale Deployments and delete pods — nothing else):
- **Stop** = scale to 0 (nothing is deleted; configuration and subscribers stay). **Start** = scale to 1 and wait
  until it is ready. **Restart** = delete the pod (the Deployment recreates it) and also restart whatever depends
  on it: UPF → SMF (the SMF only resolves the UPF address at startup) and AMF → UERANSIM gNB → UEs.
- **Start all** brings everything up in order: MongoDB → NRF → SCP → AUSF/UDM/UDR/PCF/BSF/NSSF → populate/WebUI →
  UPF → SMF → AMF → UERANSIM gNB → UEs. Each step waits for the pod to be ready and checks the log: UPF with
  `gtp_server()` on the fiber IP, AMF with `ngap_server()` on the fiber IP, SMF with `PFCP associated`, simulated
  gNB with `NG Setup ... successful`. A pod that comes up without the fiber interface (race with Multus at boot:
  `No amf.ngap.address`, `ngapIp is missing`) is **recreated automatically** (up to 2 times). What is already
  running is kept; if a "provider" was (re)started, the dependent that was already running is restarted (e.g. the
  SMF after a new UPF).
- One action at a time; the progress shows in the tab and goes to the events (source `dashboard`) and to the
  history.

**Boot** (`CORE_AUTOSTART=false`): the `open5gs-k3s-heal` unit runs `heal.sh --boot-off`, which sets every
Deployment of the namespace except the dashboard to 0. After powering the machine on, only the dashboard is up;
the rest starts from the Control tab. A `sudo ./install.sh` or `--deploy-only` brings everything up again (Helm
sets the replicas to 1). `CORE_AUTOSTART=true` goes back to the old behavior (everything up + automatic recovery).

**OCUDU gNB** (`GNB_CTL_MODE`, `GNB_CTL_SSH`, `GNB_CTL_DIR`):

| `GNB_CTL_MODE` | The card controls | How |
|---|---|---|
| `k8s` (v3 default) | the `ocudu-gnb` pod (namespace `ocudu`) | the `open5gs-k3s-gnb-ctl` agent runs `ran/ocudu/gnb.sh` with the installer user's kubectl |
| `systemd` (legacy) | the `ocudu-gnb@<yml>` service on the gNB host | the agent runs `systemctl` over SSH, authorized by a polkit rule (`scripts/ocudu/setup-gnb-service.sh`) |

- Every 3 s the agent reads: pod (or service) state, `gnb` PID, last output lines, the `.yml` files with the AMF of
  each one, PTP services and the GPS state (`ts2phc`), and the driver of the DPDK VF (over SSH to the node, same
  key as the log).
- One gNB at a time. If a `gnb` is running outside the dashboard (terminal or native service), the tab warns and
  does not start another.
- After starting, the tab checks: gNB running (and still running 5 s later), **RU with DU connected** and **N2 on
  the AMF** of the active core. A file that points to another AMF is flagged.
- After a node reboot, the card shows **"stopped (node rebooted)"**: the [boot protection](ocudu.md#boot-protection)
  prevents the gNB from starting by itself.
- **The machine must be prepared** (VF/DPDK, PTP, XDP): the button does not do that.

### Energy (MiEnergy meter)

The MiEnergy meter (single-phase) has a page `http://<IP>/Data` with ~70 readings (`v_a`, `i_a`, `p_a`, `fp_a`,
`energia_ativa_total`…). The dashboard reads that page every 2 s, with the same filter as the `collector.py` of the
MiEnergy_Lab_Meter project, **without InfluxDB or Grafana**, and shows it in the Machines tab, on the
`ENERGY_METER_HOST` machine: power on the card; on click, power, voltage, current, power factor, accumulated
energy, consumption since the dashboard started, charts and the table with every reading.

- `ENERGY_METER_URL="http://IP/Data"` + `sudo ./install.sh --dashboard-only`.
- The dashboard pod (on the core machine) must **reach the meter IP**. Test on the core machine:
  `curl -s http://IP/Data | head -c 200`.
- The meter must be on a network reachable from the core machine (no NAT on the way). If it is behind a Wi-Fi
  router, use port forwarding or the router in *access point* mode.

## Persistent history and experiments (History tab)

`DASHBOARD_PERSIST=true` (default `false`) + `sudo ./install.sh --dashboard-only`. Without it, the dashboard keeps
only the last `DASHBOARD_HISTORY_SECONDS` in memory (lost on every pod restart).

**What is recorded** (always, while enabled — nothing to press):

| Series | Content | Resolution |
|---|---|---|
| `cell:<pci>` | DL/UL throughput, PRBs, UEs, scheduler latency and failures | 1 s |
| `ue:<pci>:<rnti>` | every UE field (throughput, MCS, CQI, RI, BLER, SNR, RSRP, buffers, TA, PHR…) + **IMSI/name/IP** | 1 s |
| `du` | MAC latency and CPU | 1 s |
| `host:<machine>` | CPU, memory, temperature, load, network per interface | 2 s |
| `core:cpu`, `core:upf` | CPU of each NF; UPF traffic per interface (N6 per DNN, N3) | 2 s |
| `prom:<nf>` | Prometheus metrics (only with `OPEN5GS_METRICS=true`) | ~5 s |
| `energy` | energy meter (if enabled) | 2 s |
| events | core warnings/errors/sessions (AMF/SMF/UPF) | each event |

Format: SQLite (`/var/lib/open5gs-k3s/dashboard/history.db`, outside the project and `INSTALL_DIR`), compressed
60 s blocks. Order of magnitude: **~150–400 MB per day** with few UEs (more UEs = more data). Retention:
`DASHBOARD_PERSIST_DAYS` (default 365; 0 = never delete) and the cap `DASHBOARD_PERSIST_MAX_GB` (default 50; above
it the oldest blocks are deleted). The pod writes its buffer when stopped (SIGTERM); a hard crash loses up to 60 s.
`uninstall.sh` does **not** delete the history.

**Experiments** — the way to compare setups:
1. Prepare the setup (e.g. you changed the gNB bandwidth) and click **● Record experiment** (top, next to the
   theme). Give it a name and notes (what changed, UE position, test command). The dashboard stores with it: UEs on
   the radio (IMSI/name), version, gNB and the `config.env` of the moment (32-hex keys masked).
2. Run the test (e.g. `iperf3 -u -b 800M` for 2 min). The button turns red with a timer.
3. Click again to **stop**.
4. **History** tab: tick 2 or more experiments → **Compare**: table with means, p95 and peaks of cell DL/UL, BLER
   (every block of the period), MCS, CQI, RI, SNR, scheduler latency, CPU and temperature of each machine — the
   best of each row in green — and overlaid charts with a "time since start" axis.

You can also view **any period** (1 h, 24 h, 7 days, custom) and export CSV (`timestamp, series, IMSI, field,
value`). Deleting an experiment (only the marker; the data stays) needs the administrator password.

Reading a period uses little memory, however long it is: the stored blocks are read in batches and folded into the
charts and KPIs as they go (the CSV is also streamed). Means, minimums, maximums, counts and BLER are exact; p50
and p95 come from a sample of up to 20000 values per field, so they are exact for periods up to ~5.5 h of 1 s
data and a close estimate beyond that.

## Settings tab (editing `config.env`)

Enabled with `DASHBOARD_CONFIG_EDIT=true` (default in the config of this repository) +
`sudo ./install.sh --dashboard-only`.

- **Own administrator password**, generated once by the installer and readable only by root:
  `sudo cat /opt/open5gs-k3s/state/dashboard-admin-password`. 8 h session in the browser (closed tab = signed
  out). The rest of the dashboard stays without a password (or with `DASHBOARD_PASSWORD`).
- **Only changes the value** of variables that already exist in the file (does not create lines). Refuses line
  breaks, `$`, `` ` ``, `\` and `"` in the values — `config.env` is read with `source` by the installer as root.
- Before saving it shows the **diff** and runs the **same validation as the installer** (`validate_config`); on an
  error, nothing is written.
- Each save keeps the previous file in `/opt/open5gs-k3s/state/config-backups/` (last 50); the backup list shows
  the diff and allows restoring.
- Secrets (`UE_KEY`, `UE_OPC`, `SUBSCRIBERS`, `DASHBOARD_PASSWORD`) stay masked until you click "Show secrets".
- If someone changed the file on the server after the page was opened, the save is refused (reload).
- **Saving does not apply.** The dashboard tells you the command needed: `--dashboard-only` (dashboard variables
  only), `--deploy-only` (core/UERANSIM: restarts NFs) or the full install (k3s/host). Running it is still up to
  you, on the core machine — the dashboard has no root access.
- How it works: the pod mounts the project **read only** and only `config.env` writable, through the group of the
  file owner (`supplementalGroups`); the installer makes sure `config.env` has `g+w`.
- After saving from the interface, the file is modified in the server's git: commit it as usual.
- If the file is **replaced** on the server (e.g. `git checkout`, an editor that recreates the file), the dashboard
  refuses to save until a new `sudo ./install.sh --dashboard-only`.

## API (for scripts)

| Route | Returns |
|---|---|
| `GET /api/health` | `{"ok":true}` (no password; used by the probes) |
| `GET /api/cores` | known cores, which one is active and running |
| `GET /api/admin` | `{"enabled":…,"admin":…}` — is the session of the `X-Admin-Token` header still valid? |
| `POST /api/admin/login` · `/api/admin/logout` | `{"password":…}` → `{"token":…,"ttl":28800}` |
| `POST /api/control` | (admin) `{"action":"start|stop|restart","target":…}` · `{"action":"switch","core":"open5gs|free5gc","gnb":true,"config":"<yml>"}` |
| `GET /api/docs` · `GET /api/docs/file?path=` | list of the `.md` files + git (branch, commit, repository) · content of one project `.md` |
| `GET /api/overview` | summary used by the Overview |
| `GET /api/ran?window=300` | series per UE, cell and DU |
| `GET /api/ran.csv?window=900` | CSV per UE (UTC) |
| `GET /api/core` | pods, N2 gNBs, UEs, sessions, events, counters |
| `GET /api/core/metrics?window=300` | NF Prometheus metrics |
| `GET /api/slices?window=300` | per slice: sessions (UEs, IPs), UPF traffic now and series, refused requests |
| `GET /api/logs?pod=&container=&tail=&core=` | log of a pod (of the given core; default: the active one) |
| `GET /api/logs/stream?pod=&container=` | live log (Server-Sent Events) |
| `GET /api/gnb-log?tail=` · `/api/gnb-log/stream` | gNB log |
| `GET /api/history/summary?from=&to=` | KPIs of the period (epoch in seconds) |
| `GET /api/history/data?from=&to=&series=&prefix=&points=` | resampled series (mean and max per bucket) |
| `GET /api/history/csv?from=&to=` · `/api/history/experiments` | full CSV · experiments |
| `POST /api/history/experiments` | `{"action":"start","name":...,"notes":...}` · `{"action":"stop"}` |
| `GET /api/hosts` · `GET /api/hosts/<name>?window=` | machines: summary · details and series |
| `POST /api/ingest/host` | input of the machines agent (`X-Ingest-Token`) |
| `POST /api/ingest/gnb-log` | input of the agent (`X-Ingest-Token` header) |

State values in the API are in English: core components `running` / `stopped` / `starting` / `stopping`; GPS
`locked` / `searching` / `adjusting` / `unlocked` / `stalled` / `no_data`; UE `registered` / `deregistered`.

Example: `curl -s http://IP:30998/api/ran.csv?window=900 -o ran.csv`.

## Common problems

| Symptom | Cause / fix |
|---|---|
| "gNB no data" | gNB stopped or without `remote_control`; test `nc -vz 10.10.0.1 8001` on the core machine |
| Radio tab empty with the gNB up | no UE connected (idle UEs are released by the AMF and leave the cell) |
| Radio cards only with "RNTI …" / "not identified" | gNB log disabled (`GNB_LOG_SSH`) or the UE has not exchanged messages with the core since the dashboard started; wait or force a registration (airplane mode) |
| "gNB (real)" without lines | `journalctl -u open5gs-k3s-gnb-log`: SSH key, wrong `GNB_LOG_FILE`, or the filter dropped everything |
| The page does not open from another PC | UFW/firewalld: the installer opens `DASHBOARD_NODEPORT`; check `sudo ufw status` |
| Pod `ImagePullBackOff` | no access to Docker Hub; set `DASHBOARD_IMAGE` to a reachable Python image |
| Page in the wrong language | **EN/PT** button at the top, or `?lang=en` / `?lang=pt` in the address |

## Development

Run it outside the cluster, on the core machine, without installing anything:

```bash
kubectl proxy --port=18001 &
K8S_API=http://127.0.0.1:18001 NAMESPACE=open5gs GNB_METRICS_URL=ws://10.10.0.1:8001 \
  PORT=18080 BIND=127.0.0.1 python3 dashboard/app/server.py
# on your PC: ssh -L 18080:127.0.0.1:18080 <core machine>  and open http://127.0.0.1:18080
```

After changing any dashboard text, update the Portuguese: `dashboard/i18n/pt.json` + `python3 dashboard/i18n/build.py`.
