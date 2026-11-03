# Tutorial 6 — Change PLMN, slices and IPs

**Goal:** change the network configuration and apply it without breaking anything.
**Time:** ~15 min. **Needs:** core installed; administrator login in the dashboard.

## How a configuration reaches the core

```
config.env ──► validate_config ──► Helm values (helm/generated/) ──► helm upgrade ──► ConfigMap ──► pod
                                     + configuration hash on the pod: changed → the pod is recreated
```

You never edit `amf.yaml` or `smf.yaml` by hand: they are generated. To see the result:

```bash
kubectl -n open5gs get configmap open5gs-amf -o jsonpath='{.data.amf\.yaml}' | less
```

## 1. Edit

**From the dashboard:** **Settings** tab → the section you want → change it → check the diff → save. The
dashboard validates with the same rules as the installer and keeps a backup.

**From the terminal:** `nano config.env` on the core machine.

## 2. Examples

**Network name on the phone:**

```bash
NETWORK_NAME="MyNetwork5G"
```

**A third slice:**

```bash
SLICES=(
  "1:111111:internet:10.45.0.0/16"
  "2:222222:internet2:10.46.0.0/16"
  "3:333333:iot:10.47.0.0/16"          # SST:SD:DNN:pool
)
```

Each slice generates an S-NSSAI in the AMF, an NSI in the NSSF, a session in the SMF and a TUN with NAT in the UPF.
On the gNB, the new slice also has to be in the `.yml` (`cu_cp` / `du` → `slicing`). On free5GC, give the pool in
`F5_UE_POOLS`.

**PLMN:**

```bash
MCC="001"; MNC="01"; TAC="1"
```

The PLMN changes the AMF, the NRF, the UERANSIM gNB and the IMSIs of the simulated UEs. The real gNB `.yml`
(`cu_cp` → `plmn`, `tac`) and the SIMs have to follow.

## 3. Apply

| What changed | Command (core machine) | Impact |
|---|---|---|
| core / UERANSIM (PLMN, slices, name, subscribers) | `sudo ./install.sh --deploy-only` | recreates the affected functions; users drop for ~1 min |
| only the dashboard | `sudo ./install.sh --dashboard-only` | only the dashboard restarts |
| free5GC | `./free5gc/install.sh` | recreates free5GC |

After recreating the AMF, **restart the gNB** (dashboard → gNB card → **↻ Restart**): it does not redo N2 by
itself.

## 4. Check

```bash
./test.sh
kubectl -n open5gs get configmap open5gs-amf -o jsonpath='{.data.amf\.yaml}' | grep -A2 network_name
```

## Be careful

- Run `--deploy-only` with **Open5GS as the active core**.
- IP pools with no overlap among themselves and with `10.42/16`, `10.43/16` and the fiber (the validation refuses).
- Use a test PLMN and follow the spectrum regulations.
