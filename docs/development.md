# Development

To understand InnovaNetwork from the inside, present the project and extend it: where each thing is in the code,
how a configuration value becomes a pod, and how to change the cores, the gNB and the dashboard. References use
function names (search with `grep -n`).

## 1. The map, one sentence per piece

| Piece | In one sentence | Where |
|---|---|---|
| `config.env` | **the single source of parameters**: PLMN, slices, fiber IPs, gNB, RU, dashboard | `config.env` |
| `install.sh` | reads `config.env`, prepares the machine, installs k3s and applies everything with Helm, in idempotent steps | `install.sh` |
| `scripts/lib/common.sh` | the installer "library": validates the config and **generates the Helm values** | `scripts/lib/common.sh` |
| Gradiant charts | the ready-made Open5GS and UERANSIM charts (not edited; adjusted with values and post-renderers) | downloaded to `/opt/open5gs-k3s` |
| `helm/postrender/` | small chart fixes at apply time | `amf-ngap-net1.sh`, `drop-gnb-hpa.sh` |
| `free5gc/` | the second core: generates its manifests itself (no chart) from `config.env` + `free5gc.env` | `free5gc/lib/render.py` |
| `dashboard/app/` | the dashboard: a dependency-free Python server + HTML/JS pages | `server.py`, `control.py`, `*.js` |
| `dashboard/i18n/` | the dashboard Portuguese translation (English → Portuguese dictionary) and the script that builds `app/i18n.js` | `pt.json`, `build.py` |
| `dashboard/agent/` | agents that run on the core machine and talk to the RAN node and the O-RU | `gnb-ctl-agent.py`, `gnb-log-agent.py`, `ru-agent.py`, `host-agent.py` |
| `ran/ocudu/` | the OCUDU gNB on Kubernetes: image, node join, Deployment, `gnb.sh` | `install.sh`, `no-ran.sh`, `gnb.sh`, `lib/render.py` |

Size: ~8,000 lines of own code (shell, Python, JavaScript), with no dependencies besides the Python standard
library, Helm and the charts.

---

## 2. From `config.env` to a running pod (the path of a configuration value)

Example: the AMF IP on the fiber, `AMF_N2_IP="10.10.0.10"`.

1. **Defined** in `config.env` (the comment next to it explains that it is the gNB `cu_cp.amf.addr`).
2. **Validated** in `validate_config` (`scripts/lib/common.sh`): checks the format, whether it is inside
   `RAN_LINK_CIDR` and whether it collides with other IPs.
3. **Becomes Helm values** in `_nf_common` (`scripts/lib/common.sh`): each network function gets the Multus
   annotation (`ran_link_annotation`) with its fixed IP on the fiber; the AMF in `common.sh`.
4. **Configuration hash**: `common.sh` puts `open5gs-k3s/config-hash` on the pods — when the config changes, the
   hash changes and the pod is recreated (the charts do not do this by themselves).
5. **Applied** by `step_deploy_core` (`install.sh`) with `helm upgrade --install` and the post-renderer
   `helm/postrender/amf-ngap-net1.sh`, which moves the AMF N2 from `eth0` to `net1` (the fiber interface).
6. **In the pod**: the Multus annotation shows both AMF interfaces (replace `open5gs` with `free5gc` for the
   other core):
   ```bash
   kubectl -n open5gs get pods -o name | grep amf      # pod name
   kubectl -n open5gs get pod <name> -o jsonpath='{.metadata.annotations.k8s\.v1\.cni\.cncf\.io/network-status}'
   # → eth0 10.42.x.x (pod network)  and  net1 10.10.0.10 (fiber)
   ```

The install steps, in order (`install.sh`, `main`): packages → modules (SCTP) → sysctl → desktop/server profile →
interface `k3s0` → k3s → Helm → charts → fiber link (Multus) → core → subscribers → UERANSIM → dashboard → boot
unit → the user's kubeconfig.

---

## 3. The network (what is on each interface)

```
phone ──n78 radio── LiteOn ──fronthaul 7.2 (E810 port 1, DPDK)── OCUDU (RAN node)
                                                                       │ 10.10.0.1  (E810 port)
                                                                fiber 10.10.0.0/24, MTU 9000
                                                                       │ 10.10.0.2  (core machine, enp5s0f1)
                         ┌─────────────── macvlan "ran-link" (Multus) ─┴──────────────┐
                    AMF net1 10.10.0.10 (N2)   UPF net1 10.10.0.11 (N3)   UERANSIM gNB net1 10.10.0.20
                    AMF net1 10.10.0.30        UPF net1 10.10.0.31        UERANSIM gNB net1 10.10.0.32   (free5GC)
                         │ eth0 (pod network, flannel): SBI, PFCP (N4), MongoDB…
                    UPF ──NAT── internet (N6, default route of the core machine)
```

- **Fiber network in Kubernetes**: `render_ran_link_nad` (`common.sh`) creates the NetworkAttachmentDefinition
  `ran-link` (macvlan on `RAN_LINK_IFACE`). Multus is installed by `step_ran_link` (`install.sh`).
- **PFCP without NAT**: headless Service: the SMF talks straight to the UPF pod IP.
- **k3s node on `k3s0`** (10.254.254.1, `step_stable_netif`, `install.sh`): the cluster does not depend on the
  university IP (DHCP).

---

## 4. The two cores

| | Open5GS | free5GC |
|---|---|---|
| How it is installed | Gradiant charts + generated values (`common.sh`) | manifests generated from scratch by `free5gc/lib/render.py` (the official chart hard-coded PLMN/IPs) |
| Own configuration | `config.env` | `free5gc/free5gc.env` (+ the common part of `config.env`) |
| Start order | `CoreOps.ORDERS["open5gs"]` (`dashboard/app/control.py`) | `CoreOps.ORDERS["free5gc"]` (`control.py`); in the render, `ORDER` (`render.py`) |
| Particularities | NRF with the PLMN `servingList` (`common.sh`), `Recreate` (`common.sh`) | IMS voice advertised (`imsVoPS: 1`, `render.py`), extra `ims` DNN (`render.py`), network name (`render.py`) |

`render.py` in 4 parts: reads the environment → builds the official config of each function (`CFG` onwards) →
creates Deployments/Services (`deployment`, `service`, `manifests`) → the dashboard Role (`dashboard_rbac`) and the
UERANSIM values (`ueransim`).

---

## 5. The dashboard from the inside

```
browser ──HTTP :30998──► pod "dashboard" (namespace open5gs)
                             server.py ── Kubernetes API (pods, logs, scaling)
                                       ── gNB WebSocket (metrics, ws://10.10.0.1:8001)
                                       ◄─ agents on the core machine (POST /api/ingest/*): gNB log, gNB control, RU, machines
                             control.py ── start/stop/switch core, in order and checked
                             i18n.js ..... (browser) Portuguese mode: translates the page with dashboard/i18n/pt.json
```

| To show… | Open |
|---|---|
| how the dashboard knows that a phone registered | the log regular expressions: Open5GS `server.py` (`RE_REG_OK`), free5GC `server.py` (`RE5_REG_OK`); applied by `CoreState.line` (`server.py`) and `_line_f5` |
| where the pod/NF list comes from | `CoreCollector` (`server.py`) |
| which core is active | `CoreSet.active` (`server.py`): the only one with a running AMF; otherwise, the last one chosen |
| the core switch | `Controller._switch` (`control.py`): stops the gNB → stops the current core → stores the active one → brings the new one up in order → restarts the gNB |
| the check of each step | `CoreOps._verify` (`control.py`): waits for the pod and searches the log, e.g. AMF "Listen on 10.10.0.30" |
| how the gNB is started | `GnbCtl` (`control.py`) → agent `dashboard/agent/gnb-ctl-agent.py` → `ran/ocudu/gnb.sh` → replicas of the `ocudu-gnb` Deployment (`k8s` mode) |
| the single login | `Admin` at the end of `dashboard/app/settings.js`; on the server `class Admin` (`server.py`) |
| the Documentation tab | `dashboard/app/docs.js` (Markdown reader) and `docs_list`/`doc_read` in `server.py` |
| the languages | `dashboard/app/i18n.js` (generated) from `dashboard/i18n/i18n.tmpl.js` + `pt.json` |

The dashboard has no dependencies: only the Python standard library and uPlot (charts) stored in the repository.
It is installed as ConfigMap + Deployment by `render_dashboard` (`common.sh`).

### Dashboard texts and translations

- Write every text in **English** in the HTML/JS/Python.
- Add the Portuguese to `dashboard/i18n/pt.json`: `exact` for whole texts (also used for multi-word fragments),
  `patterns` for texts with variable parts (`{0}`, `{1}`… are placeholders, e.g.
  `["updated {0} ago", "atualizado há {0}"]`).
- Run `python3 dashboard/i18n/build.py` and commit `pt.json` and `app/i18n.js` together.
- Check: open the dashboard with `?lang=pt` and look for English left on the page.
- Logs, code (`<pre>`, `<code>`), the documentation body and elements with the class `notr` are never translated.

---

## 6. Demo scripts

Each script: **what to say → what to show → where it is in the code**. Every command runs on the core machine,
in the repository folder.

### 6.1 "It is all Kubernetes" (2 min)

```bash
kubectl get nodes -o wide                 # k3s nodes
kubectl get pods -n open5gs -o wide       # Open5GS + UERANSIM + dashboard
kubectl get pods -n free5gc               # the second core (0 pods when stopped)
kubectl get net-attach-def -A             # the "ran-link" network on the fiber (Multus)
```
Code: `install.sh` (`main`) and `docs/architecture.md`.

### 6.2 "One single configuration" (3 min)

Open `config.env` at the slices section: two slices, each with SST, SD, DNN and pool. Show that the same file
feeds Open5GS (`common.sh`), free5GC (`render.py`), UERANSIM and the dashboard. In the dashboard: **Settings** tab
(edits the file with a diff and validation).

### 6.3 "A phone joining the network" (5 min)

1. Dashboard → **Logs** → AMF (live; in the filter field, `imsi-`).
2. Turn the phone's airplane mode on and off.
3. Show in order: NG Setup (already done) → Registration Request → authentication → Registration Complete → PDU
   session with an IP (SMF).
4. **Overview**: the phone appears with IMSI, DNN and IP; **Radio**: its throughput, MCS, SNR.
Code: the expressions of section 5 (`server.py`).

### 6.4 "Switching core in one click" (3–6 min)

Dashboard → **🔒 Admin** → **Control** → **Active core** card → click the other core → "Switch now" with
"restart the gNB" ticked. Show the progress line by line (each step checked in the log) and the phone coming back
with the name of the other network (InnovaOpen5GS / InnovaFree5GC).
Code: `control.py` (`_switch`).

### 6.5 "Automatic end-to-end test" (1 min)

```bash
./test.sh            # Open5GS: pods → NRF → NG Setup → registration → session → ping 8.8.8.8 (7 checks)
./free5gc/test.sh    # free5GC: 6 checks
```

### 6.6 "The radio from the inside"

Dashboard → **RU**: PTP sync, power, temperature, fronthaul packets **on time / early / late** (the health
indicator of the fronthaul: ~91 % on time is normal). **Machines** → RAN node: the cores reserved for the gNB
(0–17) have a blue background.

### 6.7 "Reproducible experiments"

**● Record experiment** button (top) → name and notes → later, **History** tab: KPIs of the period and side-by-side
comparison of two experiments. Each experiment stores the core in use.

---

## 7. Frequently asked questions

| Question | Short answer |
|---|---|
| Why k3s and not a "full" Kubernetes? | it is certified Kubernetes in a single binary: light, with containerd, ServiceLB and local-path ready |
| Why only N2 and N3 on the fiber? | they are the only interfaces that talk to the gNB; the rest stays on the internal cluster network |
| Why does the k3s server have its own IP (`k3s0`)? | the local-network IP changes (DHCP) and the cluster cannot depend on it |
| Why two cores? | different research needs different cores; one at a time, without mixing |
| Why does the gNB use the host network and privileges? | DPDK, the NIC VF and PTP need direct hardware access, like the native service |
| Why an own manifest for the gNB, and not the official chart? | the chart changes the command and the DPDK arguments; the manifest reproduces the validated command |
| What happens on a reboot? | only the dashboard comes up; the core and the gNB are started by the operator, after the GNSS ([operation](operation.md#2-after-powering-the-machines-on)) |
| Where are the passwords? | never in git: a Kubernetes Secret and root-owned files in `/opt/open5gs-k3s/state/` |

---

## 8. Extending the project

| I want to… | Where to change |
|---|---|
| expose a new Open5GS parameter | declare it in `config.env` → default in `load_config` and validation in `validate_config` (`scripts/lib/common.sh`) → use it in `render_open5gs_values` |
| change the configuration of a free5GC function | `CFG` in `free5gc/lib/render.py` |
| another gNB/hardware on the RAN node | `ran/ocudu/ocudu.env` and the `.yml` files; the Deployment in `ran/ocudu/lib/render.py` |
| a new core | follow the `free5gc/` model: own installer, namespace with the `innovanetwork/core` label, start order in `CoreOps.ORDERS` (`dashboard/app/control.py`) |
| a tab or metric in the dashboard | backend in `dashboard/app/server.py`, page in `index.html` + `*.js`, Portuguese in `dashboard/i18n/pt.json` |
| a new agent | `dashboard/agent/`, unit created in `install.sh` (model: `setup_gnb_ctl_agent`), data through `POST /api/ingest/*` with the token |

### Modifying the Open5GS code

Open5GS comes from the chart images (`OPEN5GS_IMAGE_TAG`). To use modified code:

1. clone `https://github.com/open5gs/open5gs` at the version in use (`v2.7.5`) and make the changes;
2. build an image compatible with the chart one (same binaries in `/opt/open5gs/bin`);
3. import it into k3s: `docker save <image> | sudo k3s ctr -n k8s.io images import -`;
4. point `OPEN5GS_IMAGE_TAG` (and the repository, if it changed) and run `sudo ./install.sh --deploy-only`.

### Modifying the OCUDU code

Commit in the OCUDU repository → `sudo ~/innovanetwork-ran/no-ran.sh image` → `./ran/ocudu/install.sh` → restart
the gNB. Step by step: [tutorial 7](tutorials/07-change-the-gnb.md).

### Checks before proposing a change

```bash
bash -n install.sh uninstall.sh test.sh scripts/*.sh scripts/lib/*.sh free5gc/*.sh ran/ocudu/*.sh
shellcheck install.sh scripts/lib/common.sh            # if available
python3 -m py_compile dashboard/app/*.py dashboard/agent/*.py free5gc/lib/*.py ran/ocudu/lib/*.py
./free5gc/install.sh --dry-run; ./ran/ocudu/install.sh --dry-run
./test.sh
```

Running the dashboard outside the cluster: [components/dashboard.md](components/dashboard.md#development).
