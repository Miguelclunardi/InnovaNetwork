# Tutorial 4 — Phone on the network

**Goal:** register a programmable SIM, connect a commercial phone and browse.
**Time:** ~20 min. **Needs:** core and gNB working ([tutorial 3](03-ocudu-on-kubernetes.md)); a programmable SIM
with PLMN `001-01` (known IMSI, K and OPc); a 5G SA phone with band n78.

## 1. Register the SIM

Pick **one** way.

**WebUI (Open5GS)** — dashboard → **Core** tab → **Subscribers** (or `http://<core machine>:30999`, `admin`):

1. **+** → IMSI (e.g. `001010000000040`), Subscriber Key (K), Operator Key (**OPc**);
2. slice SST `1` / SD `111111`, DNN `internet` (add SST `2` / SD `222222`, DNN `internet2` if you want the 2nd slice);
3. save.

**Configuration file** — stays recorded and is re-applied on every installation:

```bash
# config.env (core machine)
SUBSCRIBERS=(
  "001010000000040:<K 32 hex>:<OPc 32 hex>"
)
```
```bash
sudo ./install.sh --deploy-only
```

**Command line:**

```bash
./scripts/subscribers.sh add 001010000000040 <K> <OPc>
./scripts/subscribers.sh list
```

> The keys only live in the core database and in your local `config.env`. Never publish them in git.

## 2. Prepare the phone

- Network: **5G** (SA) or "5G preferred";
- APN/DNN: `internet` (most phones use the SIM default);
- if it does not find the network by itself: manual operator selection → `00101` or `InnovaOpen5GS`.

## 3. Bring the network up

In the dashboard, **Control** tab: active core up and **gNB (Kubernetes)** running with the `.yml` of the active
core. **RU** tab: `SYNCHRONIZED`, DU `Ready`.

## 4. Connect

Take the phone out of airplane mode. Follow it:

| Where | What shows |
|---|---|
| **Logs** → `open5gs-amf` (filter `imsi-001010000000040`) | Registration Request → authentication → `Registration complete` |
| **Logs** → `open5gs-smf` | session `DNN[internet] IPv4[10.45.0.x]` |
| **Overview** | the SIM registered, with the session and the IP |
| **Radio** | the UE with name/IMSI, MCS, SNR and throughput |

The name **InnovaOpen5GS** shows on the phone after the registration.

## 5. Measure

Open a speed test on the phone and follow the DL/UL throughput in the **Radio** tab. To compare setups, record an
experiment ([tutorial 8](08-experiments.md)).

## If it does not connect

| Symptom | See |
|---|---|
| the network does not show | gNB running? O-RU synchronized? band n78 on the phone? |
| it shows but rejects the registration | wrong IMSI/K/OPc (AMF: authentication failure) or a different PLMN |
| it registers and leaves right after | on free5GC: IMS voice ([free5gc.md](../components/free5gc.md#5-commercial-phones)) |
| PRACH in the gNB log, but no registration | the O-RU synchronized before the GNSS ([hardware](../hardware/e810-liteon.md#4-sync-wait-for-the-gnss)) |

More: [troubleshooting.md](../troubleshooting.md#5-radio-and-ocudu-gnb).
