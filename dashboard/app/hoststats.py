#!/usr/bin/env python3
# =============================================================================
#  dashboard/app/hoststats.py — CPU, memória, temperaturas, rede, discos e
#  processos de uma máquina, lidos de /proc e /sys (só leitura, só stdlib).
#
#  Usado de dois jeitos:
#    - pelo painel (server.py), lendo a máquina do core montada em /host;
#    - por SSH numa máquina remota SEM instalar nada lá: o agente da máquina do
#      core manda este arquivo pela entrada padrão:
#        ssh host nice -n 19 python3 - --loop 2 < hoststats.py
#      e recebe uma linha JSON a cada 2 s.
# =============================================================================
import json
import os
import sys
import time

FS_TYPES = {"ext2", "ext3", "ext4", "xfs", "btrfs", "vfat", "zfs", "f2fs", "nfs", "nfs4"}
SKIP_IFACE = ("lo", "veth", "cali", "docker", "br-", "flannel", "cni", "tunl", "vxlan", "ovs-system", "kube-ipvs")


def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


class Collector:
    def __init__(self, root="/", fsroot=None):
        # root: onde estão proc/ e sys/ da máquina; fsroot: onde está o / dela (discos, /etc)
        self.root = root.rstrip("/") or ""
        self.fsroot = (root if fsroot is None else fsroot).rstrip("/") or ""
        self.proc = self.root + "/proc"
        self.sys = self.root + "/sys"
        self.prev = None
        self.static = self._static()

    # ----- informações fixas
    def _static(self):
        model, mhz = "", []
        for line in _read(self.proc + "/cpuinfo").splitlines():
            if line.startswith("model name") and not model:
                model = line.split(":", 1)[1].strip()
        osname = ""
        for line in _read(self.fsroot + "/etc/os-release").splitlines():
            if line.startswith("PRETTY_NAME="):
                osname = line.split("=", 1)[1].strip().strip('"')
        return {
            "hostname": _read(self.proc + "/sys/kernel/hostname").strip(),
            "cpu_model": model,
            "kernel": _read(self.proc + "/sys/kernel/osrelease").strip(),
            "os": osname,
            "isolated_cpus": _read(self.sys + "/devices/system/cpu/isolated").strip(),
        }

    # ----- leituras brutas
    def _cpu_times(self):
        out = {}
        for line in _read(self.proc + "/stat").splitlines():
            if not line.startswith("cpu"):
                break
            p = line.split()
            v = [int(x) for x in p[1:9]]
            idle = v[3] + v[4]
            out[p[0]] = (sum(v), idle)
        return out

    def _procs(self):
        out = {}
        try:
            pids = [d for d in os.listdir(self.proc) if d.isdigit()]
        except OSError:
            return out
        for pid in pids:
            s = _read("%s/%s/stat" % (self.proc, pid))
            if not s:
                continue
            r = s.rfind(")")
            name = s[s.find("(") + 1:r]
            f = s[r + 2:].split()
            try:
                out[pid] = (name, int(f[11]) + int(f[12]), int(f[21]) * 4096, int(f[36]) if len(f) > 36 else -1)
            except (IndexError, ValueError):
                continue
        return out

    def _net(self):
        out = {}
        text = _read(self.proc + "/1/net/dev") or _read(self.proc + "/net/dev")
        for line in text.splitlines()[2:]:
            name, _, rest = line.partition(":")
            name = name.strip()
            if not name or name.startswith(SKIP_IFACE):
                continue
            f = rest.split()
            out[name] = (int(f[0]), int(f[8]), int(f[2]) + int(f[3]) + int(f[10]) + int(f[11]))
        return out

    def _meminfo(self):
        m = {}
        for line in _read(self.proc + "/meminfo").splitlines():
            k, _, v = line.partition(":")
            try:
                m[k] = int(v.split()[0])
            except (IndexError, ValueError):
                pass
        return m

    def _temps(self):
        out = []
        base = self.sys + "/class/hwmon"
        try:
            hw = sorted(os.listdir(base))
        except OSError:
            return out
        for h in hw:
            d = os.path.join(base, h)
            name = _read(d + "/name").strip() or h
            try:
                files = sorted(os.listdir(d))
            except OSError:
                continue
            for fn in files:
                if fn.startswith("temp") and fn.endswith("_input"):
                    v = _read(os.path.join(d, fn)).strip()
                    if not v.lstrip("-").isdigit():
                        continue
                    label = _read(os.path.join(d, fn.replace("_input", "_label"))).strip() or fn[:-6]
                    t = int(v) / 1000.0
                    if -40 < t < 150:
                        out.append({"chip": name, "label": label, "c": round(t, 1)})
        return out[:64]

    def _disks(self):
        out, seen = [], set()
        for line in _read(self.proc + "/1/mounts").splitlines() or _read(self.proc + "/mounts").splitlines():
            p = line.split()
            if len(p) < 3 or p[2] not in FS_TYPES or p[0] in seen:
                continue
            seen.add(p[0])
            mp = p[1].replace("\\040", " ")
            try:
                st = os.statvfs(self.fsroot + mp)
            except OSError:
                continue
            total = st.f_blocks * st.f_frsize
            if total <= 0:
                continue
            used = (st.f_blocks - st.f_bfree) * st.f_frsize
            out.append({"mount": mp, "dev": p[0], "fs": p[2], "total": total, "used": used,
                        "pct": round(100.0 * used / total, 1)})
        return out[:16]

    # ----- amostra (com taxas desde a anterior)
    def sample(self):
        now = time.time()
        cpu, procs, net = self._cpu_times(), self._procs(), self._net()
        prev, self.prev = self.prev, (now, cpu, procs, net)
        mem = self._meminfo()
        load = _read(self.proc + "/loadavg").split()
        up = _read(self.proc + "/uptime").split()
        s = dict(self.static)
        s.update({
            "ts": now,
            "ncpu": len(cpu) - 1,
            "load": [float(x) for x in load[:3]] if len(load) >= 3 else None,
            "uptime": float(up[0]) if up else None,
            "mem_total": mem.get("MemTotal", 0) * 1024,
            "mem_available": mem.get("MemAvailable", 0) * 1024,
            "swap_total": mem.get("SwapTotal", 0) * 1024,
            "swap_free": mem.get("SwapFree", 0) * 1024,
            "hugepages_total": mem.get("HugePages_Total"),
            "hugepages_free": mem.get("HugePages_Free"),
            "hugepage_kb": mem.get("Hugepagesize"),
            "temps": self._temps(),
            "disks": self._disks(),
        })
        s["mem_used_pct"] = round(100.0 * (1 - s["mem_available"] / s["mem_total"]), 1) if s["mem_total"] else None
        if not prev:
            return s
        t0, cpu0, procs0, net0 = prev
        dt = max(now - t0, 1e-3)

        def usage(k):
            a, b = cpu.get(k), cpu0.get(k)
            if not a or not b or a[0] <= b[0]:
                return 0.0
            return round(100.0 * (1 - (a[1] - b[1]) / (a[0] - b[0])), 1)

        s["cpu"] = usage("cpu")
        s["cores"] = [usage("cpu%d" % i) for i in range(s["ncpu"])]
        hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        top = []
        for pid, (name, ticks, rss, cpun) in procs.items():
            p0 = procs0.get(pid)
            if p0 and p0[0] == name:
                pct = 100.0 * (ticks - p0[1]) / hz / dt
                if pct > 0.5 or rss > 512 * 1024 * 1024:
                    top.append({"pid": int(pid), "name": name, "cpu": round(pct, 1), "rss": rss, "on_cpu": cpun})
        top.sort(key=lambda x: -x["cpu"])
        s["procs"] = top[:15]
        s["nprocs"] = len(procs)
        s["net"] = []
        for name, (rx, tx, errs) in sorted(net.items()):
            n0 = net0.get(name)
            if n0:
                s["net"].append({"iface": name, "rx_bps": max(0, (rx - n0[0]) * 8 / dt),
                                 "tx_bps": max(0, (tx - n0[1]) * 8 / dt), "errs": errs})
        hot = [t["c"] for t in s["temps"] if t["chip"] in ("coretemp", "k10temp", "zenpower", "cpu_thermal")]
        s["temp_cpu"] = max(hot) if hot else (max((t["c"] for t in s["temps"]), default=None))
        return s


def main():
    interval = 2.0
    if "--loop" in sys.argv:
        i = sys.argv.index("--loop")
        interval = float(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 2.0
    root = os.environ.get("HOST_ROOT", "/")
    c = Collector(root)
    c.sample()
    while True:
        time.sleep(interval)
        print(json.dumps(c.sample(), separators=(",", ":")), flush=True)
        if "--loop" not in sys.argv:
            break


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
