# Tutorial 2 — Dashboard tour

**Goal:** sign in as administrator and know what each tab of the *Innova Center Dashboard* shows and does.
**Time:** ~15 min. **Needs:** the core installed ([tutorial 1](01-first-test-ueransim.md) or the [installation](../installation.md)).

## 1. Open and sign in

1. Open `http://<core machine IP>:30998`.
2. Get the administrator password on the core machine:
   ```bash
   sudo cat /opt/open5gs-k3s/state/dashboard-admin-password
   ```
3. Click **🔒 Admin** (top) and sign in. The login is valid for every tab for 8 h.

Without a login you can see everything; actions (start, stop, edit) ask for the login.

The **EN/PT** button at the top switches between English and Portuguese.

## 2. The tabs

| Tab | What it is for | Try it |
|---|---|---|
| **Overview** | summary: UEs on the radio, registered subscribers, sessions, pods, events | find your UE with IMSI, DNN and IP |
| **Radio** | real gNB metrics per UE: throughput, MCS, CQI, BLER, SNR, PRBs | with a phone connected, open a video and watch the DL throughput go up |
| **Core** | gNBs at the AMF, UEs, sessions, UPF traffic per DNN, CPU of each function; **Subscribers** (WebUI) | register a subscriber through the embedded WebUI |
| **Logs** | log of any pod and of the real gNB, live, with a filter | filter the AMF by `Registration` |
| **RU** | O-RU: PTP sync, power, temperature, fronthaul packets on time | check `SYNCHRONIZED` and ~90 % on time |
| **Control** | start/stop/restart the core, UERANSIM and the gNB; switch core | restart UERANSIM and follow the steps |
| **Machines** | CPU per core, memory, temperature, network of the machines | see the isolated gNB cores in blue |
| **History** | recorded metrics of any period; experiments and comparison | open the last 24 h |
| **Settings** | edit `config.env` with a diff and validation | open a section and read the explanations |
| **Documentation** | these documents, inside the dashboard | — |

## 3. A complete action

1. **Control** tab → **UERANSIM** row → **↻ Restart**.
2. Follow it at the top of the tab: each step shows with its time and result.
3. In the **Overview**, the UE disappears and comes back registered within seconds.

## 4. The top of the page

- **active core pill** (Open5GS or free5GC): every tab follows that core;
- **● Record experiment**: marks a period to compare later ([tutorial 8](08-experiments.md));
- **EN/PT**: language;
- light/dark theme.

## Next

With a radio: [OCUDU on Kubernetes](03-ocudu-on-kubernetes.md). Full reference: [components/dashboard.md](../components/dashboard.md).
