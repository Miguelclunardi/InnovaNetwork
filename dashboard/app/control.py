# =============================================================================
#  dashboard/app/control.py — Control tab: start/stop/restart the core,
#  UERANSIM and the OCUDU gNB (the latter through the gnb-ctl agent on the core machine).
#
#  InnovaNetwork: two cores (Open5GS and free5GC), each in its own namespace, one
#  active at a time. CoreOps knows how to operate ONE core (names, order, log checks);
#  Controller keeps the actions in progress and switches the active core.
#
#  Core/UERANSIM: "stop" = scale the Deployment to 0; "start" = scale to 1 and wait
#  until ready; "restart" = delete the pod (the Deployment recreates it) and restart the
#  dependents (UPF -> SMF; AMF -> simulated gNB -> UEs). "Start all" brings things up in
#  order and checks each step (fiber interface on the AMF/UPF, PFCP, NG Setup);
#  a pod that comes up without the fiber interface (race with Multus at boot) is
#  recreated by itself.
# =============================================================================
import calendar
import collections
import re
import threading
import time
import urllib.error

MAX_RETRY = 2          # recreations of a pod that came up with a problem
READY_TIMEOUT = 300    # s (image already pulled: ~10-40 s)


def _ts(s):
    """'2026-10-22T17:03:30Z' -> epoch."""
    try:
        return float(calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return 0.0


class Job:
    def __init__(self, jid, title, user):
        self.id, self.title, self.user = jid, title, user
        self.t0, self.t1 = time.time(), None
        self.state = "running"   # running | ok | warn | error
        self.lines = []

    def log(self, msg, level="info"):
        self.lines.append({"t": time.time(), "level": level, "msg": msg})
        if level in ("warn", "error") and self.state == "running":
            self._worst = max(getattr(self, "_worst", 0), 2 if level == "error" else 1)

    def view(self):
        return {"id": self.id, "title": self.title, "t0": self.t0, "t1": self.t1, "state": self.state,
                "lines": self.lines[-200:]}


UERANSIM_CHECKS = {
    "gnb-sim": (r"NG Setup procedure is successful", r"ngapIp' is missing|NG Setup procedure is failed", 60, True),
    "ues-sim": (r"PDU Session establishment is successful", None, 60, False),
}


class CoreOps:
    """Operations of ONE core in its namespace (Open5GS: Gradiant chart; free5GC: own manifests)."""

    LABELS = {"mongodb": "MongoDB", "nrf": "NRF", "scp": "SCP", "ausf": "AUSF", "udm": "UDM", "udr": "UDR",
              "pcf": "PCF", "bsf": "BSF", "nssf": "NSSF", "smf": "SMF", "upf": "UPF", "amf": "AMF",
              "webui": "WebUI", "populate": "Subscribers (populate)", "gnb-sim": "gNB UERANSIM",
              "ues-sim": "UEs UERANSIM", "chf": "CHF", "nef": "NEF"}
    ORDERS = {
        "open5gs": [["mongodb"], ["nrf"], ["scp"], ["ausf", "udm", "udr", "pcf", "bsf", "nssf"], ["populate", "webui"],
                    ["upf"], ["smf"], ["amf"], ["gnb-sim"], ["ues-sim"]],
        "free5gc": [["mongodb"], ["nrf"], ["udr"], ["udm", "ausf", "nssf", "pcf", "chf", "nef"], ["webui"],
                    ["upf"], ["smf"], ["amf"], ["gnb-sim"], ["ues-sim"]],
    }
    GROUP = {"gnb-sim": "ueransim", "ues-sim": "ueransim"}
    DEPENDENTS = {"upf": ["smf"], "amf": ["gnb-sim", "ues-sim"], "gnb-sim": ["ues-sim"]}

    def __init__(self, k8s, core, ueransim_release):
        """core: dict with name, label, kind (open5gs|free5gc), namespace, release, amf_ip, upf_ip."""
        self.k8s, self.core = k8s, core
        self.ns, self.kind = core["namespace"], core["kind"]
        self.o5, self.ur = core.get("release") or "", ueransim_release
        self.amf_ip, self.upf_ip = core.get("amf_ip") or "", core.get("upf_ip") or ""
        self.ORDER = self.ORDERS[self.kind]
        if self.kind == "free5gc":
            self.LABELS = dict(self.LABELS, webui="WebConsole")

    # ------------------------------------------------------------------ nomes
    def key(self, dep):
        if self.o5 and dep.startswith(self.o5 + "-"):
            return dep[len(self.o5) + 1:]
        if dep == self.ur:
            return "gnb-sim"
        if dep == self.ur + "-ues":
            return "ues-sim"
        return dep

    def checks(self, key):
        """(log success regex, failure regex, seconds, required)."""
        if key in UERANSIM_CHECKS:
            return UERANSIM_CHECKS[key]
        amf, upf = re.escape(self.amf_ip), re.escape(self.upf_ip)
        if self.kind == "free5gc":
            if key == "upf":
                return r"UPF started", r"Run Error|version mismatch|\[FATA\]", 60, True
            if key == "amf":
                return r"Listen on " + amf, r"Run Error|\[FATA\]", 60, True
            if key == "smf":
                return r"setup association", r"Run Error|\[FATA\]", 90, True
            return None
        if key == "upf":
            return r"gtp_server\(\) \[" + upf, r"No upf\.gtpu\.address|FATAL", 60, True
        if key == "amf":
            return r"ngap_server\(\) \[" + amf, r"No amf\.ngap\.address|FATAL", 60, True
        if key == "smf":
            return r"PFCP associated", r"FATAL", 90, True
        return None

    def installed(self):
        try:
            self.k8s.get_json("/apis/apps/v1/namespaces/%s/deployments" % self.ns)
            return True
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------ Kubernetes
    def _deps(self):
        d = self.k8s.get_json("/apis/apps/v1/namespaces/%s/deployments" % self.ns)
        return {i["metadata"]["name"]: i for i in d.get("items", []) if i["metadata"]["name"] != "dashboard"}

    def _pods(self, dep):
        sel = ",".join("%s=%s" % kv for kv in dep["spec"]["selector"].get("matchLabels", {}).items())
        d = self.k8s.get_json("/api/v1/namespaces/%s/pods" % self.ns, {"labelSelector": sel})
        return d.get("items", [])

    def _scale(self, name, n):
        self.k8s.request("PATCH", "/apis/apps/v1/namespaces/%s/deployments/%s/scale" % (self.ns, name),
                         {"spec": {"replicas": n}}, "application/merge-patch+json")

    def _delete_pod(self, name):
        try:
            self.k8s.request("DELETE", "/api/v1/namespaces/%s/pods/%s" % (self.ns, name))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise

    def _log(self, pod, tail=400):
        c = pod["spec"]["containers"][0]["name"]
        try:
            return self.k8s.get_text("/api/v1/namespaces/%s/pods/%s/log" % (self.ns, pod["metadata"]["name"]),
                                     {"container": c, "tailLines": tail})
        except urllib.error.HTTPError:
            return ""

    @staticmethod
    def _pod_state(p):
        st = p.get("status", {})
        cs = st.get("containerStatuses") or []
        ready = bool(cs) and all(c.get("ready") for c in cs)
        restarts = sum(c.get("restartCount", 0) for c in cs)
        reason = ""
        for c in cs:
            w = (c.get("state") or {}).get("waiting") or {}
            if w.get("reason"):
                reason = w["reason"]
        return ready, restarts, reason or st.get("phase", "")

    # ------------------------------------------------------------------ view
    def components(self):
        deps = self._deps()
        rank = {k: i for i, g in enumerate(self.ORDER) for k in g}
        out = []
        for name, d in deps.items():
            k = self.key(name)
            pods = [p for p in self._pods(d) if not p["metadata"].get("deletionTimestamp")]
            ps = []
            for p in pods:
                ready, restarts, reason = self._pod_state(p)
                ps.append({"name": p["metadata"]["name"], "ready": ready, "restarts": restarts, "reason": reason,
                           "since": _ts(p.get("status", {}).get("startTime"))})
            want = d["spec"].get("replicas", 1)
            state = ("stopped" if want == 0 and not pods else "stopping" if want == 0
                     else "running" if ps and all(x["ready"] for x in ps) else "starting")
            out.append({"key": k, "deployment": name, "label": self.LABELS.get(k, k),
                        "group": self.GROUP.get(k, "core"), "rank": rank.get(k, 99), "replicas": want,
                        "state": state, "pods": ps})
        out.sort(key=lambda c: (c["rank"], c["key"]))
        return out

    def running(self):
        """True if the AMF of this core is requested to run (replicas > 0)."""
        try:
            for name, d in self._deps().items():
                if self.key(name) == "amf":
                    return d["spec"].get("replicas", 1) > 0
        except Exception:  # noqa: BLE001
            pass
        return False

    def _by_key(self):
        return {self.key(n): (n, d) for n, d in self._deps().items()}

    def _targets(self, target):
        keys = [k for g in self.ORDER for k in g]
        have = self._by_key()
        extra = sorted(k for k in have if k not in keys)
        if target == "ueransim":
            sel = ["gnb-sim", "ues-sim"]
        elif target == "core":
            sel = [k for k in keys if self.GROUP.get(k, "core") == "core"] + extra
        else:
            sel = keys + extra
        return [k for k in sel if k in have]

    def _run_group(self, job, action, target):
        sel = self._targets(target)
        if not sel:
            raise RuntimeError("no component found in namespace %s (is %s installed?)" % (self.ns, self.core["label"]))
        if action == "stop":
            # reverse order: radio first, database last
            have = self._by_key()
            for k in reversed(sel):
                job.log("stopping %s" % self.LABELS.get(k, k))
                self._scale(have[k][0], 0)
            self._wait_gone(job, [have[k][0] for k in sel])
            return
        if action == "restart":
            job.log("restart = stop everything and start in order")
            self._run_group(job, "stop", target)
        started = set()
        for group in self.ORDER + [[k for k in sel if all(k not in g for g in self.ORDER)]]:
            ks = [k for k in group if k in sel]
            if ks:
                started |= self._start_keys(job, ks, started)

    def _run_one(self, job, action, key):
        have = self._by_key()
        if key not in have:
            raise ValueError("unknown component: %s" % key)
        name, dep = have[key]
        if action == "stop":
            job.log("stopping %s" % self.LABELS.get(key, key))
            self._scale(name, 0)
            self._wait_gone(job, [name])
            deps = [k for k in self.DEPENDENTS.get(key, []) if k in have and have[k][1]["spec"].get("replicas", 1)]
            if deps:
                job.log("warning: %s depend(s) on %s and will need a restart when it comes back"
                        % (", ".join(self.LABELS.get(k, k) for k in deps), self.LABELS.get(key, key)), "warn")
            return
        if action == "start" or dep["spec"].get("replicas", 1) == 0:
            self._start_keys(job, [key])
            return
        # restart: recreate the pod and then the running dependents
        self._restart_keys(job, [key])
        for k in self.DEPENDENTS.get(key, []):
            if k in have and have[k][1]["spec"].get("replicas", 1) > 0:
                job.log("%s depends on %s: restarting it too" % (self.LABELS.get(k, k), self.LABELS.get(key, key)))
                self._restart_keys(job, [k])

    # ------------------------------------------------------------------ passos
    def _start_keys(self, job, keys, started=frozenset()):
        """Brings the keys up; returns the ones (re)started. A component already running whose
        "supplier" was just (re)started (e.g. SMF after a new UPF) is restarted."""
        have = self._by_key()
        t0 = time.time()
        todo = []
        for k in keys:
            name, dep = have[k]
            label = self.LABELS.get(k, k)
            if dep["spec"].get("replicas", 1) >= 1:
                prov = [p for p, ds in self.DEPENDENTS.items() if k in ds and p in started]
                if self._all_ready(dep) and not prov:
                    job.log("%s is already running (kept)" % label)
                    continue
                if prov:
                    job.log("%s was running, but %s was restarted: restarting it too"
                            % (label, ", ".join(self.LABELS.get(p, p) for p in prov)))
                    for p in self._pods(dep):
                        self._delete_pod(p["metadata"]["name"])
                    todo.append(k)
                    continue
                # requested to run but not ready (e.g. without the fiber interface): recreate
                job.log("%s is not ready; recreating the pod" % label, "warn")
                for p in self._pods(dep):
                    self._delete_pod(p["metadata"]["name"])
            else:
                job.log("starting %s" % label)
                self._scale(name, 1)
            todo.append(k)
        for k in todo:
            name, dep = have[k]
            self._verify(job, k, name, dep, t0)
        return set(todo)

    def _restart_keys(self, job, keys):
        have = self._by_key()
        t0 = time.time()
        for k in keys:
            name, dep = have[k]
            job.log("restarting %s (pod recreated)" % self.LABELS.get(k, k))
            for p in self._pods(dep):
                self._delete_pod(p["metadata"]["name"])
        for k in keys:
            name, dep = have[k]
            self._verify(job, k, name, dep, t0)

    def _all_ready(self, dep):
        pods = [p for p in self._pods(dep) if not p["metadata"].get("deletionTimestamp")]
        return bool(pods) and all(self._pod_state(p)[0] for p in pods)

    def _fresh_pod(self, dep, t0):
        pods = [p for p in self._pods(dep) if not p["metadata"].get("deletionTimestamp")
                and _ts(p["metadata"].get("creationTimestamp")) >= t0 - 2]
        return pods[0] if pods else None

    def _verify(self, job, key, name, dep, t0):
        """Waits for the new pod to be ready and checks the log; recreates it if it came up with a problem."""
        label = self.LABELS.get(key, key)
        for attempt in range(MAX_RETRY + 1):
            pod = None
            end = time.time() + READY_TIMEOUT
            while time.time() < end:
                pod = self._fresh_pod(dep, t0)
                if pod:
                    ready, restarts, reason = self._pod_state(pod)
                    if ready or restarts or reason in ("CrashLoopBackOff", "Error", "ImagePullBackOff", "ErrImagePull"):
                        break
                time.sleep(2)
            else:
                raise RuntimeError("%s was not ready after %d s" % (label, READY_TIMEOUT))
            ready, restarts, reason = self._pod_state(pod)
            ck = self.checks(key)
            bad = None
            if restarts or not ready:
                text = self._log(pod, 60)
                bad = "pod went down (%s)%s" % (reason or "restarted",
                                           (": " + text.strip().splitlines()[-1][:160]) if text.strip() else "")
            elif ck:
                ok_re, bad_re, secs, required = ck
                end = time.time() + secs
                while True:
                    text = re.sub(r"\x1b\[[0-9;]*m", "", self._log(pod))
                    if re.search(ok_re, text):
                        break
                    m = re.search(".*(%s).*" % bad_re, text, re.M) if bad_re else None
                    if m:
                        bad = m.group(0).strip()[:200]
                        break
                    if time.time() > end:
                        if required:
                            bad = "not seen in the log after %d s: %s" % (secs, ok_re.replace("\\", ""))
                        else:
                            job.log("%s: still no '%s' after %d s (follow the log)" % (label, ok_re, secs), "warn")
                        break
                    time.sleep(2)
            if not bad:
                job.log("%s ready%s" % (label, " and checked" if ck else ""))
                return
            if attempt == MAX_RETRY:
                raise RuntimeError("%s has a problem: %s" % (label, bad))
            job.log("%s has a problem (%s); recreating the pod" % (label, bad), "warn")
            t0 = time.time()
            self._delete_pod(pod["metadata"]["name"])

    def _wait_gone(self, job, names, timeout=120):
        have = {n: d for n, d in self._deps().items() if n in names}
        end = time.time() + timeout
        while time.time() < end:
            left = [n for n, d in have.items() if self._pods(d)]
            if not left:
                job.log("stopped")
                return
            time.sleep(2)
        job.log("still terminating after %d s: %s" % (timeout, ", ".join(left)), "warn")


class Controller:
    """Control tab actions (one at a time) on the active core, its UERANSIM, the OCUDU gNB and the core switch."""

    def __init__(self, cores, active_fn, set_active_fn, event, gnb=None):
        self.cores = cores               # name -> CoreOps (order: the first one is the default)
        self.active_fn = active_fn       # () -> nome do core ativo
        self.set_active = set_active_fn  # (name) -> stores the preference
        self.event = event               # callback(level, msg) -> history/events
        self.gnb = gnb                   # GnbCtl (OCUDU) or None
        self.lock = threading.Lock()
        self.job = None
        self.jobs = collections.deque(maxlen=10)
        self.seq = 0

    def ops(self, name=None):
        name = name or self.active_fn()
        if name not in self.cores:
            raise ValueError("unknown core: %s" % name)
        return self.cores[name]

    def view(self):
        with self.lock:
            job = self.job.view() if self.job else None
            hist = [j.view() for j in self.jobs if j is not self.job][:5]
        active = self.active_fn()
        try:
            comps, err = self.ops(active).components(), None
        except Exception as e:  # noqa: BLE001
            comps, err = [], str(e)
        return {"core": active, "components": comps, "error": err, "job": job, "recent": hist,
                "ocudu": self.gnb.view() if self.gnb else None}

    # ------------------------------------------------------------------ actions
    def submit(self, body, user):
        target = str(body.get("target") or "")
        action = str(body.get("action") or "")
        if action not in ("start", "stop", "restart", "switch"):
            raise ValueError("invalid action")
        with self.lock:
            if self.job and self.job.state == "running":
                raise RuntimeError("an action is already in progress: " + self.job.title)
            names = {"start": "Start", "stop": "Stop", "restart": "Restart"}
            if action == "switch":
                to = str(body.get("core") or "")
                if to not in self.cores:
                    raise ValueError("unknown core: %s" % to)
                cfg = str(body.get("config") or "") if body.get("gnb") else ""
                if body.get("gnb") and not self.gnb:
                    raise ValueError("OCUDU gNB control disabled")
                title = "Switch the active core to %s" % self.cores[to].core["label"]
                fn = lambda j: self._switch(j, to, cfg)  # noqa: E731
            elif target == "ocudu":
                if not self.gnb:
                    raise ValueError("OCUDU gNB control disabled (GNB_CTL_SSH empty)")
                cfg = str(body.get("config") or "")
                title = "%s gNB OCUDU%s" % (names[action], " (%s)" % cfg if cfg else "")
                fn = lambda j: self.gnb.run(j, action, cfg)  # noqa: E731
            else:
                ops = self.ops(str(body.get("core") or "") or None)
                core = ops.core["label"]
                if target in ("core", "all", "ueransim"):
                    what = {"core": "whole core", "all": "core + UERANSIM", "ueransim": "UERANSIM"}[target]
                    title = "%s %s (%s)" % (names[action], what, core)
                    fn = lambda j: ops._run_group(j, action, target)  # noqa: E731
                else:
                    title = "%s %s (%s)" % (names[action], ops.LABELS.get(target, target), core)
                    fn = lambda j: ops._run_one(j, action, target)  # noqa: E731
            self.seq += 1
            job = Job(self.seq, title, user)
            self.job = job
            self.jobs.appendleft(job)
        threading.Thread(target=self._wrap, args=(job, fn), daemon=True, name="controle").start()
        return job.view()

    def _wrap(self, job, fn):
        self.event("info", "control: %s" % job.title)
        try:
            fn(job)
            w = getattr(job, "_worst", 0)
            job.state = "error" if w >= 2 else "warn" if w else "ok"
        except Exception as e:  # noqa: BLE001
            job.log("failed: %s" % e, "error")
            job.state = "error"
        job.t1 = time.time()
        lvl = {"ok": "info", "warn": "warning", "error": "warning"}[job.state]
        self.event(lvl, "control: %s — %s" % (job.title, {"ok": "done", "warn": "done with warnings",
                                                           "error": "failed"}[job.state]))

    def _switch(self, job, to, gnb_cfg):
        """Stops the OCUDU gNB (if asked), stops the other cores, starts the new one in order and starts the gNB again."""
        new = self.cores[to]
        if not new.installed():
            raise RuntimeError("%s is not installed (namespace %s)" % (new.core["label"], new.ns))
        olds = [o for n, o in self.cores.items() if n != to and o.installed()]
        job.log("active core: %s → %s" % (", ".join(o.core["label"] for o in olds if o.running()) or "none",
                                         new.core["label"]))
        if gnb_cfg:
            st = self.gnb.status or {}
            if st.get("active"):
                job.log("stopping the OCUDU gNB (%s.yml) before the switch" % (st["active"].get("config") or "?"))
                self.gnb.run(job, "stop", "")
        for o in olds:
            if o.running() or any(c["replicas"] for c in o.components()):
                job.log("stopping %s (core + UERANSIM)" % o.core["label"])
                o._run_group(job, "stop", "all")
        self.set_active(to)
        job.log("starting %s in order" % new.core["label"])
        new._run_group(job, "start", "all")
        if gnb_cfg:
            job.log("starting the OCUDU gNB with %s.yml" % gnb_cfg)
            self.gnb.run(job, "start", gnb_cfg)
        job.log("ready: active core = %s" % new.core["label"])


# =============================================================================
#  OCUDU gNB: the gnb-ctl agent (core machine) sends the state every few
#  seconds and gets back the next command; the result comes in the following post.
# =============================================================================
class GnbCtl:
    def __init__(self, target):
        self.target = target
        self.lock = threading.Lock()
        self.status = None
        self.ts = None
        self.pending = None     # {"id", "action", "config"}
        self.results = {}       # id -> {"ok", "output"}
        self.cond = threading.Condition(self.lock)
        self.seq = 0

    def push(self, status, result):
        with self.lock:
            if status is not None:
                self.status, self.ts = status, time.time()
            if result and result.get("id") in self.results:
                self.results[result["id"]] = result
            cmd = self.pending
            self.pending = None
            self.cond.notify_all()
            return cmd

    def view(self):
        with self.lock:
            return {"target": self.target, "online": bool(self.ts and time.time() - self.ts < 20),
                    "age": time.time() - self.ts if self.ts else None, "status": self.status}

    def _cmd(self, job, action, config, timeout=90):
        with self.lock:
            if not (self.ts and time.time() - self.ts < 20):
                raise RuntimeError("gNB agent not reachable (journalctl -u open5gs-k3s-gnb-ctl on the core machine)")
            self.seq += 1
            cid = "%d-%d" % (int(time.time()), self.seq)
            self.pending = {"id": cid, "action": action, "config": config}
            self.results[cid] = None
            job.log("command sent to %s: %s %s" % (self.target, action, config or ""))
            end = time.time() + timeout
            while self.results[cid] is None and time.time() < end:
                self.cond.wait(1)
            res = self.results.pop(cid)
        if res is None:
            raise RuntimeError("the agent did not answer within %d s" % timeout)
        for l in (res.get("output") or "").strip().splitlines()[-15:]:
            job.log("  " + l)
        if not res.get("ok"):
            raise RuntimeError("the command failed on %s" % self.target)

    def _wait_status(self, cond, secs):
        end = time.time() + secs
        while time.time() < end:
            with self.lock:
                st = self.status or {}
            if cond(st):
                return st
            time.sleep(1)
        return None

    def run(self, job, action, config):
        st = (self.status or {})
        if action == "start" and not config:
            raise ValueError("choose the configuration file")
        if action == "start" and st.get("manual"):
            raise RuntimeError("a gnb is running outside the dashboard (PID %s): stop it in the terminal first"
                               % ", ".join(str(m["pid"]) for m in st["manual"]))
        if action == "restart" and not st.get("active"):
            if not config:
                raise RuntimeError("no gNB running from the dashboard; use Start")
            action = "start"
        n2_before = self.n2_ref() if self.n2_ref else None
        self._cmd(job, action, config)
        if action == "stop":
            if self._wait_status(lambda s: not s.get("active") and not s.get("gnb_pids"), 40):
                job.log("gNB stopped")
            else:
                job.log("the gnb process is still there after 40 s", "warn")
            return
        st = self._wait_status(lambda s: (s.get("active") or {}).get("sub") == "running" or s.get("failed"), 30) or {}
        a = st.get("active") or {}
        if a.get("sub") != "running":
            f = st.get("failed") or a
            raise RuntimeError("the service did not stay running (%s/%s)%s" % (
                f.get("state"), f.get("sub"), ": " + " | ".join(f.get("journal", [])[-4:]) if f.get("journal") else ""))
        time.sleep(5)   # the gnb may die right at the start (DPDK/RU): check again
        st = self._wait_status(lambda s: True, 5) or {}
        if st.get("failed") or (st.get("active") or {}).get("sub") != "running":
            f = st.get("failed") or st.get("active") or {}
            raise RuntimeError("the gNB went down right after starting: " + " | ".join(f.get("journal", [])[-4:]))
        job.log("gNB running with %s.yml (PID %s)" % (a.get("config"), a.get("pid")))
        # confirmations from outside: RU (DU connected) and AMF (N2)
        if self.ru_ref:
            end = time.time() + 90
            while time.time() < end:
                if (self.ru_ref.summary() or {}).get("du") == "Ready":
                    job.log("RU: DU connected (fronthaul ok)")
                    break
                time.sleep(2)
            else:
                job.log("RU still has no DU after 90 s (see the RU tab and the gNB log)", "warn")
        if self.n2_ref:
            end = time.time() + 60
            while time.time() < end:
                cur = self.n2_ref()
                if cur and cur != n2_before:
                    job.log("AMF: gNB connected (N2)")
                    break
                time.sleep(2)
            else:
                job.log("the AMF has not seen the gNB (N2) after 60 s: does the file point to this core?", "warn")

    ru_ref = None   # RuState (checks "DU connected")
    n2_ref = None   # function -> time of the last "gNB-N2 accepted" of this gNB in the AMF (or None)
