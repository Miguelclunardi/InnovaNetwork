# Tutorial 5 — Switch core

**Goal:** install free5GC next to Open5GS and switch between the two from the dashboard, with the phone coming
back by itself on the new network.
**Time:** ~30 min. **Needs:** Open5GS core and dashboard installed; for the radio, the gNB on Kubernetes.

## 1. Install free5GC

🖥️ Core machine:

```bash
sudo ./free5gc/setup-gtp5g.sh               # UPF kernel module (once)
./free5gc/install.sh                        # brings free5GC up
./free5gc/install.sh --import-open5gs       # copies the SIMs from Open5GS
./free5gc/test.sh                           # "6 ok, 0 failure(s)"
sudo ./install.sh --dashboard-only          # the dashboard gets the "Active core" card
```

## 2. Create the gNB `.yml` for free5GC

📡 RAN machine, a copy of the current `.yml` with another AMF:

```bash
cd ~/ocudu/configs
cp gnb_split_open5gs.yml gnb_split_free5gc.yml
sed -i 's/addr: 10.10.0.10/addr: 10.10.0.30/' gnb_split_free5gc.yml
grep -n -A2 "amf:" gnb_split_free5gc.yml          # addr: 10.10.0.30
```

## 3. Switch

Dashboard → **🔒 Admin** → **Control** tab → **Active core** card:

1. click **free5GC**;
2. leave **restart the OCUDU gNB with** ticked and choose `gnb_split_free5gc` (only the `.yml` files of this AMF
   show);
3. **Switch now**.

The progress shows line by line (shortened example):

```
active core: Open5GS → free5GC
stopping the OCUDU gNB (gnb_split_open5gs.yml) before the switch
stopping Open5GS (core + UERANSIM)
starting free5GC in order
… NRF ✓ … UPF ✓ … SMF ✓ (PFCP associated) … AMF ✓ (listening on 10.10.0.30) … UERANSIM: NG Setup ✓
starting the OCUDU gNB with gnb_split_free5gc.yml
gNB running with gnb_split_free5gc.yml · RU: DU connected · AMF: gNB connected (N2)
ready: active core = free5GC
```

It takes ~1 min. The phones drop and come back with the **InnovaFree5GC** network and IPs `10.60.x.x`
(`internet`) and `10.62.x.x` (`ims`).

## 4. Check

| Where | Expected |
|---|---|
| top of the dashboard | **free5GC** pill |
| Overview | phones registered with `10.60/16` IPs |
| Core → Subscribers | free5GC WebConsole (`:31000`) |
| `kubectl -n open5gs get deploy` | Open5GS functions at 0 replicas (the dashboard stays up) |

## 5. Back to Open5GS

Same path: **Active core** card → **Open5GS** → `.yml` `gnb_split_open5gs` → **Switch now**
(~5 min: Open5GS has more functions and waits for NRF/SCP).

## Rules

- Always through the **Active core** card: it follows the right order and restarts the gNB on the right AMF.
- Do not run installers during the switch.
- `sudo ./install.sh --deploy-only` only with Open5GS active.
