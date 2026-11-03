# Troubleshooting

Symptom → cause → fix. Organized by area.

- [1. Quick diagnosis](#1-quick-diagnosis)
- [2. Cluster access](#2-cluster-access-kubectl)
- [3. Core: problems already fixed in the code](#3-core-problems-already-fixed-in-the-code)
- [4. Core: other possible problems](#4-core-other-possible-problems)
- [5. Radio and OCUDU gNB](#5-radio-and-ocudu-gnb)
- [6. RAN node and OCUDU installation on Kubernetes](#6-ran-node-and-ocudu-installation-on-kubernetes)
- [7. Operation: core switch and installers](#7-operation-core-switch-and-installers)
- [8. Dashboard](#8-dashboard)
- [9. Useful logs](#9-useful-logs)

---

## 1. Quick diagnosis

```bash
kubectl get nodes -o wide                    # both machines Ready?
kubectl get pods -A | grep -v Running        # anything unusual?
./test.sh -v                                 # Open5GS core end to end (with logs on failure)
./ran/ocudu/gnb.sh status; ./ran/ocudu/gnb.sh log | tail -20
journalctl -u open5gs-k3s-heal -b            # what the boot unit did
```

| Symptom | First step |
|---|---|
| nothing answers after the boot | normal: only the dashboard comes up. Control tab → **Start all** |
| the dashboard does not open | `kubectl -n open5gs get pods -l app=dashboard`; `sudo ./install.sh --dashboard-only` |
| the phone does not see the network | gNB running? O-RU `SYNCHRONIZED` and DU `Ready`? (section 5) |
| the phone sees the network but does not register | SIM registered in the active core? same PLMN? AMF log |
| registers but does not browse | restart the UPF from the dashboard (it restarts the SMF too) |

## 2. Cluster access (`kubectl`)

### 2.1 `The connection to the server localhost:8080 was refused`

**Cause**: your user's `kubectl` has no kubeconfig. Without `~/.kube/config` (or with it empty) and without
`KUBECONFIG`, kubectl tries the default `localhost:8080`, where nothing listens. k3s is working — it exposes the
API at `https://127.0.0.1:6443` and writes the credentials to `/etc/rancher/k3s/k3s.yaml`, readable **only by
root** (mode 0600, on purpose: that file gives full control of the cluster).

**Fix**: `install.sh` already does this at the end for the user who called `sudo`. To redo it:

```bash
sudo ./install.sh --deploy-only        # redoes values/deploy and the user's kubeconfig
# or by hand:
mkdir -p ~/.kube
sudo cat /etc/rancher/k3s/k3s.yaml > ~/.kube/config
chmod 600 ~/.kube/config
kubectl get nodes
```

> If you already had a `~/.kube/config` with other clusters, `install.sh` **merges** it (context `open5gs-k3s`)
> and keeps your current context; switch with `kubectl config use-context open5gs-k3s`. The previous config is
> saved once in `~/.kube/config.bak-open5gs-k3s`.

### 2.2 Ways to access it

| How | When to use it |
|------|-------------|
| `kubectl …` (or `k …`) | Normal use, no sudo. Uses `~/.kube/config` (context `open5gs-k3s`). |
| `KUBECONFIG=~/.kube/open5gs-k3s.yaml kubectl …` | Standalone copy of this cluster only (useful if `~/.kube/config` points elsewhere). |
| `sudo k3s kubectl …` | Always works (root reads `/etc/rancher/k3s/k3s.yaml`). Good for emergencies. |
| `sudo kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml …` | Equivalent, with a separate kubectl. |

The project scripts choose by themselves: `/etc/rancher/k3s/k3s.yaml` when running as root, otherwise
`~/.kube/open5gs-k3s.yaml`.

### 2.3 Basic check commands

```bash
kubectl get nodes -o wide                          # node Ready?
kubectl -n open5gs get pods -o wide                # all 1/1 Running?
kubectl -n open5gs get svc                         # services (amf-ngap, upf-gtpu, webui…)
kubectl -n open5gs describe pod <pod>              # events: image pull, crash, probes
kubectl -n open5gs logs deploy/open5gs-amf -f      # live logs of an NF
kubectl -n open5gs logs deploy/open5gs-amf --previous   # logs of the previous run (after a crash)
kubectl -n open5gs get events --sort-by=.lastTimestamp | tail -20
kubectl -n open5gs exec -it deploy/ueransim-ues -- bash  # shell in the UE
sudo systemctl status k3s ; sudo journalctl -u k3s -f   # k3s service
./test.sh -v                                       # end-to-end validation with logs
```

## 3. Core: problems already fixed in the code

| # | Symptom | Cause | Fix (already in the project) |
|---|---------|-------|--------------------------|
| 1 | `deployments.apps "coredns" not found` right after installing k3s | k3s creates the system manifests asynchronously; the script checked before they existed. | `install.sh` waits for the deployments to exist before `rollout status`. |
| 2 | Pods in `ErrImagePull: pull QPS exceeded` on the 1st start | kubelet limit (5 pulls/s) with ~15 images at the same time. Transient. | `kubelet-arg: registry-qps=20, registry-burst=40` in the k3s config. |
| 3 | UDR/PCF/WebUI in `CrashLoopBackOff` in the first minutes | MongoDB still downloading/starting. | None — it fixes itself when Mongo comes up. |
| 4 | UE: `no cells in coverage`; `ping` between pods → *Packet filtered* | **firewalld** rejecting direct pod↔pod traffic (traffic through a Service worked, so the core looked OK). | `CONFIGURE_FIREWALLD=true`: `K3S_CLUSTER_CIDR` and `K3S_SERVICE_CIDR` in the `trusted` zone. |
| 5 | UE stuck in `MM-DEREGISTERED/LIMITED-SERVICE`, cell `ACCEPTABLE` | UERANSIM race: it selected the cell before SIB1 and does not re-evaluate. | `install.sh` waits for NG Setup and, if the UE does not register within 60 s, restarts the UE pod once. By hand: `kubectl -n open5gs rollout restart deploy/ueransim-ues`. |
| 6 | Registration rejected; AMF `HTTP response error [400]`; SCP `No SEPP` | NRF chart with `servingList` fixed to 999/70; with PLMN 001/01 the UE looked like another network (roaming). | `nrf.config.servingList` generated from `MCC`/`MNC`. |
| 7 | Registration rejected (`UE_IDENTITY_CANNOT_BE_DERIVED…`); SCP `No route to host` to an old IP | RollingUpdate: new NFs discovered old NFs and kept them in the cache (valid for 24 h). | `updateStrategy: Recreate` on every NF. By hand: restart the NFs together. |
| 8 | `failed to query scale subresource for StatefulSet/open5gs/ueransim` repeating in `journalctl -u k3s` | `ueransim-gnb` chart bug: the HPA (min=max=1) points to a `StatefulSet`, but the gNB is a `Deployment`. | Post-renderer `helm/postrender/drop-gnb-hpa.sh` removes the HPA. |
| 9 | `localhost:8080 was refused` in the user's terminal | No user kubeconfig (see §2.1). | `install.sh` sets up `~/.kube/config` for `$SUDO_USER` (idempotent merge). |
| 10 | Files named after loose words in the project folder | `cmd \| tee install.log word word…` — `tee` creates one file per argument. | `install.sh` writes its own log to `logs/install.log`; do not use `\| tee`. |
| 11 | k3s stuck in `activating`; `kubectl`: `apiserver not ready`/`connection refused` after unplugging the cable | `node-ip` bound to the physical IP; on Wi‑Fi the IP was different. | `NODE_IP_MODE=stable`: dummy interface `k3s0` with a fixed private IP, created by the `open5gs-k3s-netif` unit before k3s. |
| 12 | After a reboot or a k3s restart: UE registered with an IP, but `ping` fails; the UPF logs `Cannot find PFCP-Node … from [SMF IP]` | The pods come back in any order; the PFCP association (N4) between SMF and UPF and the UE sessions go out of sync. | `scripts/heal.sh` (UEs, then UPF → SMF → gNB → UEs), run at boot by the `open5gs-k3s-heal` unit (`AUTO_HEAL=true`) and by `install.sh`. |

### Known noise (not an error)

- `journalctl -u k3s`: `Error on socket receive … 127.0.0.1:10250 … use of closed network connection`
  — local kubelet connections being closed at the end of `kubectl logs/exec`. Harmless.
- AMF/SMF logs with `Failed to connect to open5gs-scp-sbi … Connection refused` in the first seconds after a
  restart — the NFs come up before the SCP and retry.

## 4. Core: other possible problems

| Symptom | Likely cause / fix |
|---------|--------------------------|
| `open5gs-mongodb` in `CrashLoopBackOff` with *Illegal instruction* | CPU/VM without **AVX** (MongoDB 8). On a VM use CPU `host-passthrough`, or set `MONGODB_IMAGE_*` to a 4.4 image. |
| Persistent `ImagePullBackOff` | No access to Docker Hub, or rate limit: `kubectl -n open5gs describe pod …`. |
| gNB without NG Setup | `lsmod \| grep sctp`; gNB PLMN/TAC/S-NSSAI different from the AMF. |
| UE `Registration reject` / authentication failure | IMSI/K/OPc not registered or different: `./scripts/subscribers.sh list`. |
| UE registers but has no PDU session | UE DNN/slice missing in the SMF or in the subscriber. See the SMF/UPF logs. |
| Ping to the gateway (10.45.0.1) OK, to the internet not | N6: host without a way out, DNS, or a firewall (Docker/UFW/firewalld) blocking forwarding. `sudo iptables -L FORWARD -n -v`. |
| Pods without network after installing Docker | Docker sets `FORWARD` to `DROP`. k3s creates rules for `10.42.0.0/16`; if needed: `sudo iptables -I FORWARD -s 10.42.0.0/16 -j ACCEPT; sudo iptables -I FORWARD -d 10.42.0.0/16 -j ACCEPT`. |
| Desktop loses network / unstable pods | NetworkManager managing `cni0`/`flannel.1`: check `/etc/NetworkManager/conf.d/90-open5gs-k3s-unmanaged.conf`. |
| k3s does not start after the host IP changed (DHCP, cable unplugged, switch to Wi‑Fi) and `journalctl -u k3s` shows `node IP … not found in the host's network interfaces` | Old installation with `node-ip` on the physical NIC. With `NODE_IP_MODE=stable` (default) run `sudo ./install.sh` once: the node moves to `k3s0`/10.254.254.1 and it does not happen again. Check with `ip -br a show k3s0` and `systemctl status open5gs-k3s-netif`. |
| `helm` timeout on the 1st installation | Slow download: increase `HELM_TIMEOUT` and run it again. |
| SMF: `No IP addresses available` / `All IP addresses in all subnets are occupied` | The UE pool of that DNN is exhausted (sessions not released). Restart the SMF and UPF from the dashboard (Control tab) or enlarge the pool in `SLICES`. |

## 5. Radio and OCUDU gNB

| Symptom | Cause | Fix |
|---|---|---|
| the gNB starts but does not show up on the AMF | the `.yml` points to the other core, or the AMF restarted after the gNB | choose the `.yml` of the active core; restart the gNB |
| the gNB loses the AMF ("Handling N2 disconnection") | core stopped or switched with the gNB running | use the dashboard core switch, which restarts the gNB |
| phones do PRACH but do not connect; RU with many early/late packets | the O-RU synchronized before the GNSS was valid | `restart ptp4l-gm phc2sys`, reboot the O-RU, restart the gNB ([hardware](hardware/e810-liteon.md#4-sync-wait-for-the-gnss)) |
| O-RU without "DU connected" | PTP stopped or VF not on `vfio-pci` | `systemctl status ptp4l-gm ts2phc`; `dpdk-devbind.py --status` |
| dashboard: "stopped (node rebooted)" | boot protection: the node rebooted after the last start request | wait for the GNSS, check PTP/O-RU and click **Start** |
| the pod refuses to start: "a gnb is already running on the host" | native `ocudu-gnb@` service or a gNB open in a terminal | stop the other gNB (both use the same O-RU and VF) |
| `gnb.sh start` refuses: "native service running" | same | `systemctl stop 'ocudu-gnb@*'` on the node |
| the phone registers and leaves ~1 s later (free5GC) | no IMS voice advertised / `ims` DNN missing | already configured in `free5gc.env`; check `F5_EXTRA_DNNS` |
| continuous "bad message" in `ptp4l` | XDP not on the fronthaul port | `sudo systemctl restart ptp4l-gm phc2sys` with the gNB stopped |

## 6. RAN node and OCUDU installation on Kubernetes

Problems found in the first installation, already handled in the scripts:

| Symptom | Cause | Fix |
|---|---|---|
| the build fails in `build_rohc.sh` with `curl: (35) Connection reset by peer` | the ROHC library site blocks the network | `OCUDU_IMAGE_ROHC=false` (default): image without ROHC, like the typical native build |
| the k3s agent does not start: `listen tcp 0.0.0.0:10250: bind: address already in use` | another Kubernetes on the node (e.g. MicroK8s) | `join` detects it and aborts; stop the other one (e.g. `sudo microk8s stop`) |
| agent looping: `Node authorization rejected` | certificates from an earlier failed attempt | `join` cleans them up; by hand: stop the agent, `rm -rf /var/lib/rancher/k3s/agent`, start it |
| pod: `EAL: … /dev/hugepages/rtemap_0 failed: Permission denied`, `cannot open /proc/self/pagemap` | the official image runs as user 1001; DPDK in this mode needs root | the pod runs with `runAsUser: 0` and `privileged` |
| pod: `Unable to create log file "/tmp/gnb.log": Permission denied` | old log owned by someone else; `fs.protected_regular=2` prevents reopening it | the pod removes the log if its owner is not root |
| pod: `EAL: Cannot init memory` with free hugepages | Kubernetes limits hugetlb to what the pod requests | `OCUDU_HUGEPAGES_1G` (the pod requests `hugepages-1Gi`) |
| `join` run on the wrong machine: `command not found` | node command run on the core machine | each installation step says which machine it runs on |
| the image does not show up on the node after `import` | incomplete import | run `import` again, keeping the output: `2>&1 \| tee import.log` |

Check the node: `kubectl describe node <node>` (label, taint, allocatable `hugepages-1Gi`) and
`kubectl get node <node> -o json | grep -o 'innovanetwork/ocudu-gnb:[0-9a-f]*'` (image present).

## 7. Operation: core switch and installers

| Symptom | Cause | Fix |
|---|---|---|
| both cores running at the same time | `install.sh --deploy-only` run with free5GC active (Helm sets the Open5GS replicas back to 1) | run `--deploy-only` with Open5GS active, or switch core right after |
| `--deploy-only` fails at "Subscribers" (`timed out waiting for the condition`) | run together with a core switch, which stopped the `populate` pod | do not run an installer and a switch together; run the install again |
| the cell disappears after switching core with the separate buttons | the gNB kept pointing to the old AMF | use the **Active core** card |
| the UE registers but does not browse after a reboot | SMF↔UPF PFCP out of sync | restart the UPF from the dashboard (it restarts the SMF), or `./scripts/heal.sh` |

## 8. Dashboard

| Symptom | Cause / fix |
|---|---|
| gNB card: "agent not reachable" | `journalctl -u open5gs-k3s-gnb-ctl` on the core machine (kubeconfig, SSH to the node) |
| "gNB no data" in the Radio tab | gNB stopped or without `remote_control`: `nc -vz 10.10.0.1 8001` |
| UEs only with "RNTI …" | gNB log disabled (`GNB_LOG_SSH`) or the UE has not exchanged messages with the core yet |
| RU tab without data | O-RU credentials missing (`/opt/open5gs-k3s/state/ru-credentials`) or management IP; `journalctl -u open5gs-k3s-ru` |
| Settings refuses to save | the file changed on the server; reload the page |
| the page does not open from another PC | firewall: the installer opens the dashboard port; `sudo ufw status` |
| texts in the wrong language | **EN/PT** button at the top, or open `…:30998/?lang=en` (or `?lang=pt`) |

More: [components/dashboard.md](components/dashboard.md#common-problems).

## 9. Useful logs

```bash
kubectl -n open5gs logs deploy/open5gs-amf | grep -iE 'gNB|Registration|reject'
kubectl -n open5gs logs deploy/open5gs-smf | grep -iE 'UE|session|PFCP'
kubectl -n open5gs logs deploy/open5gs-scp | grep -iE 'error|warn'
kubectl -n open5gs logs deploy/open5gs-upf
kubectl -n open5gs logs deploy/ueransim          # gNB
kubectl -n open5gs logs deploy/ueransim-ues      # UEs
kubectl -n open5gs exec deploy/ueransim-ues -- nr-cli imsi-001010000000001 --exec status
less logs/install.log                            # history of the install.sh runs
kubectl -n ocudu logs deploy/ocudu-gnb           # OCUDU gNB
journalctl -u open5gs-k3s-gnb-ctl -f             # gNB control agent
```
