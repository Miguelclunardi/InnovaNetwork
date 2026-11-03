# Reference hardware: Intel E810 + LiteOn FlexFi O-RU

The setup InnovaNetwork was validated on. Use it as a reference to build yours: what changes from one setup to
another lives in `ran/ocudu/ocudu.env` and in the gNB `.yml` files.

> Contribute your hardware profile: see [CONTRIBUTING.md](../../CONTRIBUTING.md).

## 1. Parts

| Part | Detail |
|---|---|
| **RAN machine** | x86_64, Ubuntu 24.04, low-latency kernel; CPUs 0–17 isolated for the gNB; 1 GiB hugepages |
| **Intel E810-C, 4 SFP ports** | port 1 (`ens4f0np0`): fronthaul to the O-RU (`vfio-pci` VF in DPDK) and PTP grandmaster · port 4 (`ens4f3np3`): fiber to the core machine, `10.10.0.1/24`, MTU 9000 |
| **GNSS** | time reference of the E810 (`ts2phc` reads the PPS/NMEA) |
| **LiteOn FlexFi FR1 O-RU** | n78, TDD, 4T4R, O-RAN split 7.2; management over SSH on `10.101.131.59` (RJ45 port) |
| **Core machine** | port `enp5s0f1` on the fiber (`10.10.0.2/24`); extra IP `10.101.131.10/24` on the O-RU management network |

## 2. Cell

The same in both cores (only the AMF changes between the `.yml` files):

| Parameter | Value |
|---|---|
| Band / ARFCN | n78 / `649980` |
| Bandwidth / SCS | 100 MHz / 30 kHz, TDD |
| Antennas | 4 DL × 4 UL |
| PLMN / TAC / PCI | `00101` / `1` / `1` |
| Slices | SST 1 SD `0x111111` · SST 2 SD `0x222222` (PRB split per slice) |
| Fronthaul | VLAN 564 (C and U-plane), BFP 9-bit compression |

## 3. Preparing the RAN machine

Host services (not part of InnovaNetwork) that start at boot:

| Service | What it does |
|---|---|
| `ocudu-setup` | fronthaul port with MTU 1500 (PTP only), VLAN offloads off, 1 SR-IOV VF in `vfio-pci` with `trust on` / `spoofchk off`, the PTP fix-up XDP program, `ip_forward` |
| `dpdk` | DPDK environment (hugepages) |
| `ts2phc` | E810 clock from the GNSS |
| `ptp4l-gm` | PTP grandmaster on the fronthaul port (the O-RU syncs through it) |
| `phc2sys` | system clock from the E810 |

Check: `systemctl status ocudu-setup ptp4l-gm ts2phc phc2sys` and `dpdk-devbind.py --status`.

## 4. Sync: wait for the GNSS

After a boot the GNSS can take **up to ~30 min** to give a valid time (`ts2phc` shows `source ts not valid`).
Until then the E810 clock, which is the PTP master of the O-RU, can be **tens of seconds wrong**. When the GNSS
comes back, `ts2phc` corrects it with a jump (observed: between −31 and −37 s). Consequences:

- an O-RU that synchronized to the wrong time **does not fix itself**: it shows `SYNCHRONIZED`, but only ~5 % of
  the fronthaul packets arrive on time (normal: ~90 %) and the uplink disappears (phones send PRACH, but Msg3 does
  not arrive);
- the system clock takes minutes to catch up.

**Sequence after a boot:**

```bash
journalctl -u ts2phc -f                          # 1. wait for "offset … s2"
sudo systemctl restart ptp4l-gm phc2sys          # 2. fixes the system clock and reloads the XDP (gNB stopped)
# 3. reboot the O-RU
# 4. start the gNB (dashboard or ./ran/ocudu/gnb.sh start)
```

InnovaNetwork already prevents the gNB from starting by itself after a boot
([boot protection](../components/ocudu.md#boot-protection)).

## 5. PTP fix-up XDP

The LiteOn O-RU sends Delay_Req with padding that `ptp4l` rejects ("bad message", tens per second). An XDP program
on the fronthaul port strips that padding.

- **Phones work without it** (the O-RU follows PTP through the Sync messages), but without measuring the delay.
- The XDP leaves the port when the O-RU link drops (O-RU rebooting) and when `ptp4l` resets the port after a
  "timed out while polling for tx timestamp" failure. Loading it with `ptp4l` running also causes that failure.
- Tweaks: `tx_timestamp_timeout 50` in `/etc/linuxptp/ptp4l.cfg` and an `ExecStartPre` in `ptp4l-gm` that loads the
  XDP before `ptp4l`. To reload it: `sudo systemctl restart ptp4l-gm phc2sys` with the gNB stopped.

## 6. `ocudu.env` values for this hardware

```bash
OCUDU_NODE_IP="10.10.0.1"; OCUDU_NODE_IFACE="ens4f3np3"   # port 4 (fiber), never the fronthaul port
OCUDU_CPUS="0-17"                                         # = isolated CPUs
OCUDU_HUGEPAGES_1G="2Gi"                                  # = --socket-mem 2048 of eal_args
OCUDU_IMAGE_MARCH="native"                                # image optimized for this CPU
```

## 7. Health indicators

| Where | Normal |
|---|---|
| dashboard → RU | `SYNCHRONIZED`, DU `Ready`, ~90–92 % of the packets on time, 0 late |
| dashboard → Machines | gNB DPDK CPUs at 100 % (polling loop) — expected |
| `journalctl -u phc2sys` | offset of a few ns, state `s2` |

## 8. Common problems

| Symptom | Likely cause / what to do |
|---|---|
| phones send PRACH but do not connect; many early/late packets | the O-RU synchronized before the GNSS: section 4 |
| O-RU without "DU connected" | PTP stopped (`ptp4l-gm`, `ts2phc`) or the VF is not in `vfio-pci` |
| "bad message" in `ptp4l` | XDP off the port: section 5 |
| huge `/tmp/gnb.log` | `info` level: rotate it or delete it with the gNB stopped |
