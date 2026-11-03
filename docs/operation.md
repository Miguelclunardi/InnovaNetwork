# Operation

Day-to-day use of the network. Almost everything is done from the **dashboard**
(`http://<core machine IP>:30998`).

- [1. Administrator login](#1-administrator-login)
- [2. After powering the machines on](#2-after-powering-the-machines-on)
- [3. Start and stop](#3-start-and-stop)
- [4. Switch core](#4-switch-core)
- [5. The OCUDU gNB](#5-the-ocudu-gnb)
- [6. Subscribers (SIMs)](#6-subscribers-sims)
- [7. Change the configuration](#7-change-the-configuration)
- [8. Test](#8-test)
- [9. Useful commands](#9-useful-commands)

---

## 1. Administrator login

Viewing the state is open. Actions (start, stop, switch core, edit the configuration) need the administrator
password:

- **🔒 Admin**, at the top: one login covers every tab and window of the same browser, for 8 h;
- **🔓 Admin · Sign out** ends the session;
- the password is in `sudo cat /opt/open5gs-k3s/state/dashboard-admin-password` (core machine).

The **EN/PT** button at the top switches the dashboard language (remembered by the browser).

## 2. After powering the machines on

For safety, **only the dashboard comes up by itself** (`CORE_AUTOSTART=false`). The core and the gNB are started
by the operator.

| # | Where | What to do | Ready when |
|---|---|---|---|
| 1 | dashboard | **🔒 Admin** → **Control** tab → check the **Active core** → **▶ Start all** | every step ✓ (AMF listening on N2, SMF associated with the UPF) |
| 2 | RAN machine | wait for the GNSS: `journalctl -u ts2phc -f` (or the GPS line of the **Status** button) | lines with `offset … s2` (up to ~30 min after the boot) |
| 3 | RAN machine | if the clock jumped (normal after a boot): `sudo systemctl restart ptp4l-gm phc2sys` | `phc2sys` with an offset of a few ns |
| 4 | O-RU | reboot the O-RU (it synchronized with the old clock) | **RU** tab: `SYNCHRONIZED` |
| 5 | dashboard | **gNB (Kubernetes)** card: choose the `.yml` of the active core → **▶ Start** | the tab checks pod running, DU connected and N2 on the AMF |
| 6 | dashboard | **Overview** | phones registered with an IP |

> If the RAN machine reboots, the gNB pod comes back **without starting the gNB** and shows "stopped (node
> rebooted)". This is the boot protection: start it again from the dashboard after steps 2–4. See
> [components/ocudu.md](components/ocudu.md#boot-protection).

The local-network IPs (DHCP) can change after a reboot. Only the address used to open the dashboard changes; the
cluster and the fiber use fixed IPs.

## 3. Start and stop

**Control** tab:

| Action | What happens |
|---|---|
| **▶ Start all** | brings the active core up in order (MongoDB → NRF → … → UPF → SMF → AMF → UERANSIM), checking each step in the logs |
| **■ Stop all** | scales the core and UERANSIM to 0 (nothing is deleted: configuration and subscribers stay) |
| per-function buttons | start / stop / restart one function; restarting the UPF also restarts the SMF, and the AMF restarts the UERANSIM gNB |
| gNB card | start with a `.yml` / restart / stop the OCUDU gNB |

Before powering the machines off, stop the gNB and then the core.

## 4. Switch core

Available with free5GC installed. **Disconnects everyone** connected during the switch.

1. **Control** tab → **Active core** card → click the other core.
2. Leave **restart the OCUDU gNB with** ticked and choose the `.yml` that points to the AMF of the new core (the
   dashboard only lists those).
3. **Switch now.** The dashboard stops the gNB → stops the current core → marks the new one → brings the new one up,
   checking each step → restarts the gNB.

Typical times: Open5GS → free5GC ~1 min; free5GC → Open5GS ~5 min. Every tab then follows the active core
(functions, logs, subscribers, sessions, traffic).

> Always use the **Active core** card. Stopping one core and starting the other with the separate buttons does not
> touch the gNB, which keeps pointing to the old AMF.

Tutorial: [Switch core](tutorials/05-switch-core.md).

## 5. The OCUDU gNB

From the dashboard (**gNB (Kubernetes)** card) or from the command line, on the core machine:

```bash
./ran/ocudu/gnb.sh configs                 # available .yml files and the AMF of each one
./ran/ocudu/gnb.sh start <yml>             # start (without extension; default: the current one)
./ran/ocudu/gnb.sh stop                    # SIGINT to the gNB, like Ctrl+C
./ran/ocudu/gnb.sh status                  # replicas, .yml, pod, node, restarts
./ran/ocudu/gnb.sh log -f                  # gNB output (full log: /tmp/gnb.log on the node)
```

| Changed… | Do |
|---|---|
| a `.yml` in `~/ocudu/configs/` (RAN node) | restart the gNB. The pod reads the host folder; no rebuild needed |
| the OCUDU source | commit → rebuild the image → `./ran/ocudu/install.sh` → restart. See [tutorial 7](tutorials/07-change-the-gnb.md) |
| the core AMF restarted | restart the gNB (it does not redo N2 by itself) |

## 6. Subscribers (SIMs)

| Core | Where |
|---|---|
| Open5GS | dashboard → **Core** → **Subscribers** (WebUI `:30999`); or `SUBSCRIBERS` in `config.env` + `sudo ./install.sh --deploy-only`; or `./scripts/subscribers.sh` |
| free5GC | dashboard → **Core** → **Subscribers** (WebConsole `:31000`); or `./free5gc/install.sh --import-open5gs` |

The keys (K/OPc) never go into git and never show on the screen during the import. Tutorial:
[Phone on the network](tutorials/04-phone-on-the-network.md).

## 7. Change the configuration

| Where | Apply with | Effect |
|---|---|---|
| dashboard → **Settings** tab (edits `config.env` with a diff and validation) | the command the dashboard shows | saving **does not apply** |
| `config.env` — core/UERANSIM | `sudo ./install.sh --deploy-only` | recreates the functions that changed (disconnects users) |
| `config.env` — dashboard | `sudo ./install.sh --dashboard-only` | only the dashboard restarts |
| `config.env` — host/k3s | `sudo ./install.sh` | may restart k3s |
| `free5gc/free5gc.env` | `./free5gc/install.sh` | recreates free5GC |
| `ran/ocudu/ocudu.env` | `./ran/ocudu/install.sh` | updates the Deployment (keeps the `.yml` and the on/off state) |

Be careful:

- run `--deploy-only` **with Open5GS as the active core**: Helm sets the Open5GS replicas back to 1;
- do not run an installer and a core switch at the same time;
- after recreating the AMF, restart the gNB.

Tutorial: [Change PLMN, slices and IPs](tutorials/06-change-configuration.md).

## 8. Test

| Test | Command (core machine) | Expected |
|---|---|---|
| Open5GS + UERANSIM | `./test.sh` (`-v` shows logs on failure) | `7 checks OK` |
| free5GC + UERANSIM | `./free5gc/test.sh` | `6 ok, 0 failure(s)` |
| real gNB | dashboard → **RU** and **Radio** | `SYNCHRONIZED`, DU `Ready`, ~90 % on time; UEs with throughput |
| phone | dashboard → **Overview** | registered, session with an IP from the active core pool |

The tests only read the state and use the simulated UE; the tested core must be running.

## 9. Useful commands

```bash
kubectl get nodes -o wide                         # both machines Ready?
kubectl get pods -A -o wide                       # everything, with the node of each pod
kubectl -n open5gs logs deploy/open5gs-amf -f     # AMF live
kubectl -n ocudu logs deploy/ocudu-gnb -f         # gNB
journalctl -u open5gs-k3s-gnb-ctl -f              # gNB control agent (core machine)
less logs/install.log                             # installer history
```

Problems: [troubleshooting.md](troubleshooting.md).
