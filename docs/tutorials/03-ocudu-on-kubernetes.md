# Tutorial 3 — OCUDU on Kubernetes

**Goal:** move the OCUDU gNB, which already works on the RAN machine, into the cluster as a pod, and control it
from the dashboard.
**Time:** ~1 h (the build takes ~15 min). **Needs:** core installed; RAN machine prepared
([requirements](../installation.md#ran-machine-part-3-only)); passwordless SSH from the core machine to the RAN
machine.

> Each step says **where** to run it. 🖥️ = core machine (in the repository folder). 📡 = RAN machine.
> Keep the output of the long steps with `2>&1 | tee file.log`.

## Step 0 — Check the starting point

📡 The native gNB works and is **stopped**; the OCUDU source is committed:

```bash
pgrep -ax gnb || echo "no gnb running"
git -C ~/ocudu status --short | head          # empty = everything committed
git -C ~/ocudu log --oneline -1               # this commit becomes the image tag
ls ~/ocudu/configs/*.yml
```

🖥️ The core is up and the RAN node answers over the fiber:

```bash
kubectl get nodes
ssh -o BatchMode=yes user@10.10.0.1 hostname
```

## Step 1 — Configure

🖥️ Review `ran/ocudu/ocudu.env` (node, IPs, OCUDU folder, CPUs, hugepages). Variable table:
[components/ocudu.md](../components/ocudu.md#3-configuration-ocuduenv).

## Step 2 — Copy the scripts to the node

🖥️
```bash
./ran/ocudu/install.sh copy
```

Expected: `~/innovanetwork-ran/` created on the node with `no-ran.sh` and `ocudu.env`.

## Step 3 — Build the image

📡
```bash
sudo ~/innovanetwork-ran/no-ran.sh image 2>&1 | tee ~/innovanetwork-ran/build.log
```

Expected, at the end: `[ok]` with the image `innovanetwork/ocudu-gnb:<commit>` and the confirmation that it has
`gnb`, `taskset` and `bash`. Check with `sudo docker images innovanetwork/ocudu-gnb`.

## Step 4 — Prepare the server

🖥️
```bash
sudo ./ran/ocudu/install.sh prepare
```

Expected: firewall opened (if there is UFW) and the token copied to `~/innovanetwork-ran/join.env` on the node
(valid for 2 h; it does not show on the screen).

## Step 5 — The node joins the cluster

📡
```bash
sudo ~/innovanetwork-ran/no-ran.sh join 2>&1 | tee ~/innovanetwork-ran/join.log
```

🖥️ Check:

```bash
kubectl get nodes -o wide
# NAME           STATUS   ROLES           INTERNAL-IP
# innovaserver   Ready    <none>          10.10.0.1
# torre2         Ready    control-plane   10.254.254.1
kubectl describe node innovaserver | grep -E "Taints|role=ran|hugepages-1Gi"
```

If the image was built after joining: 📡 `sudo ~/innovanetwork-ran/no-ran.sh import`.

## Step 6 — Create the Deployment

🖥️
```bash
./ran/ocudu/install.sh --dry-run
./ran/ocudu/install.sh
kubectl -n ocudu get deploy,cm        # ocudu-gnb 0/0 (stopped) + descriptor
```

## Step 7 — Start the gNB from the command line

Before: valid GNSS and a synchronized O-RU ([hardware](../hardware/e810-liteon.md#4-sync-wait-for-the-gnss)).

🖥️
```bash
./ran/ocudu/gnb.sh configs
./ran/ocudu/gnb.sh start gnb_split_open5gs
./ran/ocudu/gnb.sh log -f
```

Expected in the log:

```
ocudu-gnb: taskset -c 0-17 gnb -c /configs/gnb_split_open5gs.yml -c /configs/metricas.yml
N2: Connection to AMF on 10.10.0.10:38412 completed
==== gNB started ===
```

And in the dashboard → **RU**: `SYNCHRONIZED`, DU `Ready`, ~90 % of the packets on time.

## Step 8 — Hand the control over to the dashboard

🖥️ In `config.env`:

```bash
GNB_CTL_MODE="k8s"
GNB_CTL_SSH="user@10.10.0.1"
GNB_CTL_DIR="/home/user/ocudu"
```

```bash
sudo ./install.sh --dashboard-only
```

In the dashboard, **Control** tab, the card becomes **gNB (Kubernetes)** and shows the pod running with the
`.yml` and the PID. Try **↻ Restart**: the tab checks the pod, the DU connected on the O-RU and N2 on the AMF.

## Step 9 — Test the boot protection (optional)

📡 `sudo reboot`. When the node comes back:

- 🖥️ `kubectl get nodes` → the node is `Ready` again, by itself;
- dashboard → gNB card: **"stopped (node rebooted)"** — the gNB did not start by itself;
- after the GNSS (`s2`), `sudo systemctl restart ptp4l-gm phc2sys`, reboot the O-RU and **▶ Start** in the
  dashboard.

## What you did

The RAN node became part of the cluster, and the gNB became a pod with the same binary, command, configuration
and performance as the native service, now started and stopped by Kubernetes. Next:
[Phone on the network](04-phone-on-the-network.md).
