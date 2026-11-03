# Tutorial 1 — First test with UERANSIM

**Goal:** install the Open5GS core on one machine and watch a simulated UE register, open a session and browse.
**Time:** ~20 min. **Needs:** Ubuntu 24.04 with `sudo` and internet. No radio.

## 1. Get the project

```bash
git clone https://github.com/Miguelclunardi/InnovaNetwork.git ~/InnovaNetwork
cd ~/InnovaNetwork
```

## 2. Adjust the configuration for a single machine

Open `config.env` and turn off what depends on a radio:

```bash
RAN_LINK_ENABLED=false      # no fiber to a real gNB
GNB_METRICS_URL=""          # no real gNB in the dashboard
GNB_LOG_SSH=""
GNB_CTL_SSH=""
RU_MGMT_IP=""               # no O-RU
DASHBOARD_HOSTS=()          # no other machines
```

The rest can stay as it is: PLMN `001-01`, TAC `1`, slices `internet` and `internet2`.

## 3. Install

```bash
sudo ./install.sh
```

Follow the steps (`==> …`). The first time it takes 5–15 min, almost all of it image downloads. At the end:

```
[ok] dashboard up: http://<IP>:30998
```

If something fails, the `[error]` message names the step; the full log is in `logs/install.log`.

## 4. Test

```bash
./test.sh
```

Expected:

```
RESULT: 7 checks OK, 0 failures
```

## 5. Look inside

```bash
kubectl -n open5gs get pods -o wide                 # ~17 pods Running
kubectl -n open5gs logs deploy/open5gs-amf | grep -iE "NG Setup|Registration complete"
kubectl -n open5gs exec -it deploy/ueransim-ues -- bash
```

Inside the UE pod:

```bash
nr-cli -d                                           # imsi-001010000009001
nr-cli imsi-001010000009001 --exec status           # MM-REGISTERED / NORMAL-SERVICE
ip -br addr show uesimtun0                          # 10.45.0.x: IP given by the SMF
ping -I uesimtun0 -c 3 8.8.8.8                      # the traffic goes through the UPF
curl --interface uesimtun0 -s https://example.com | head -5
exit
```

## 6. See it in the dashboard

Open `http://<machine IP>:30998`:

- **Overview:** the simulated UE shows as *UERANSIM*, registered, with the session `internet → 10.45.0.x`;
- **Logs:** pick `open5gs-amf` and follow it live;
- **Core:** the UE traffic at the UPF.

## What you did

You installed k3s, the Open5GS core (13 functions + MongoDB), a simulated gNB and UE, and the dashboard — all as
pods, generated from `config.env`. Next: [Dashboard tour](02-dashboard-tour.md).
