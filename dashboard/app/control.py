# =============================================================================
#  dashboard/app/control.py — aba Controle: iniciar/parar/reiniciar o core,
#  o UERANSIM e o gNB OCUDU (este pelo agente gnb-ctl na máquina do core).
#
#  Core/UERANSIM: "parar" = escala 0 do Deployment; "iniciar" = escala 1 e espera
#  ficar pronto; "reiniciar" = apaga o pod (o Deployment recria) e reinicia os
#  dependentes (UPF -> SMF; AMF -> gNB simulado -> UEs). "Iniciar tudo" sobe em
#  ordem e confere cada etapa (interface da fibra no AMF/UPF, PFCP, NG Setup);
#  um pod que suba sem a interface da fibra (corrida com o Multus no boot) é
#  recriado sozinho.
# =============================================================================
import calendar
import collections
import re
import threading
import time
import urllib.error

MAX_RETRY = 2          # recriações de um pod que subiu com problema
READY_TIMEOUT = 300    # s (imagem já baixada: ~10-40 s)


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


class Controller:
    def __init__(self, k8s, namespace, open5gs_release, ueransim_release, amf_ip, upf_ip, event, gnb=None):
        self.k8s, self.ns = k8s, namespace
        self.o5, self.ur = open5gs_release, ueransim_release
        self.amf_ip, self.upf_ip = amf_ip, upf_ip
        self.event = event               # callback(level, msg) -> histórico/eventos
        self.gnb = gnb                   # GnbCtl (OCUDU) ou None
        self.lock = threading.Lock()
        self.job = None
        self.jobs = collections.deque(maxlen=10)
        self.seq = 0

    # ------------------------------------------------------------------ nomes
    def key(self, dep):
        if dep.startswith(self.o5 + "-"):
            return dep[len(self.o5) + 1:]
        if dep == self.ur:
            return "gnb-sim"
        if dep == self.ur + "-ues":
            return "ues-sim"
        return dep

    LABELS = {"mongodb": "MongoDB", "nrf": "NRF", "scp": "SCP", "ausf": "AUSF", "udm": "UDM", "udr": "UDR",
              "pcf": "PCF", "bsf": "BSF", "nssf": "NSSF", "smf": "SMF", "upf": "UPF", "amf": "AMF",
              "webui": "WebUI", "populate": "Assinantes (populate)", "gnb-sim": "gNB UERANSIM",
              "ues-sim": "UEs UERANSIM"}
    ORDER = [["mongodb"], ["nrf"], ["scp"], ["ausf", "udm", "udr", "pcf", "bsf", "nssf"], ["populate", "webui"],
             ["upf"], ["smf"], ["amf"], ["gnb-sim"], ["ues-sim"]]
    GROUP = {"gnb-sim": "ueransim", "ues-sim": "ueransim"}
    DEPENDENTS = {"upf": ["smf"], "amf": ["gnb-sim", "ues-sim"], "gnb-sim": ["ues-sim"]}

    def checks(self, key):
        """(regex de sucesso no log, regex de falha, segundos, obrigatório)."""
        if key == "upf":
            ok = r"gtp_server\(\) \[" + (re.escape(self.upf_ip) if self.upf_ip else "")
            return ok, r"No upf\.gtpu\.address|FATAL", 60, True
        if key == "amf":
            ok = r"ngap_server\(\) \[" + (re.escape(self.amf_ip) if self.amf_ip else "")
            return ok, r"No amf\.ngap\.address|FATAL", 60, True
        if key == "smf":
            return r"PFCP associated", r"FATAL", 90, True
        if key == "gnb-sim":
            return r"NG Setup procedure is successful", r"ngapIp' is missing|NG Setup procedure is failed", 60, True
        if key == "ues-sim":
            return r"PDU Session establishment is successful", None, 60, False
        return None

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

    # ------------------------------------------------------------------ visão
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
            state = ("parado" if want == 0 and not pods else "parando" if want == 0
                     else "rodando" if ps and all(x["ready"] for x in ps) else "iniciando")
            out.append({"key": k, "deployment": name, "label": self.LABELS.get(k, k),
                        "group": self.GROUP.get(k, "core"), "rank": rank.get(k, 99), "replicas": want,
                        "state": state, "pods": ps})
        out.sort(key=lambda c: (c["rank"], c["key"]))
        return out

    def view(self):
        with self.lock:
            job = self.job.view() if self.job else None
            hist = [j.view() for j in self.jobs if j is not self.job][:5]
        try:
            comps, err = self.components(), None
        except Exception as e:  # noqa: BLE001
            comps, err = [], str(e)
        return {"components": comps, "error": err, "job": job, "recent": hist,
                "ocudu": self.gnb.view() if self.gnb else None}

    # ------------------------------------------------------------------ ações
    def submit(self, body, user):
        target = str(body.get("target") or "")
        action = str(body.get("action") or "")
        if action not in ("start", "stop", "restart"):
            raise ValueError("ação inválida")
        with self.lock:
            if self.job and self.job.state == "running":
                raise RuntimeError("já há uma ação em andamento: " + self.job.title)
            self.seq += 1
            names = {"start": "Iniciar", "stop": "Parar", "restart": "Reiniciar"}
            if target == "ocudu":
                if not self.gnb:
                    raise ValueError("controle do gNB OCUDU desligado (GNB_CTL_SSH vazio)")
                cfg = str(body.get("config") or "")
                title = "%s gNB OCUDU%s" % (names[action], " (%s)" % cfg if cfg else "")
                fn = lambda j: self.gnb.run(j, action, cfg)  # noqa: E731
            elif target in ("core", "all", "ueransim"):
                what = {"core": "core inteiro", "all": "core + UERANSIM", "ueransim": "UERANSIM"}[target]
                title = "%s %s" % (names[action], what)
                fn = lambda j: self._run_group(j, action, target)  # noqa: E731
            else:
                title = "%s %s" % (names[action], self.LABELS.get(target, target))
                fn = lambda j: self._run_one(j, action, target)  # noqa: E731
            job = Job(self.seq, title, user)
            self.job = job
            self.jobs.appendleft(job)
        threading.Thread(target=self._wrap, args=(job, fn), daemon=True, name="controle").start()
        return job.view()

    def _wrap(self, job, fn):
        self.event("info", "controle: %s" % job.title)
        try:
            fn(job)
            w = getattr(job, "_worst", 0)
            job.state = "error" if w >= 2 else "warn" if w else "ok"
        except Exception as e:  # noqa: BLE001
            job.log("falhou: %s" % e, "error")
            job.state = "error"
        job.t1 = time.time()
        lvl = {"ok": "info", "warn": "warning", "error": "warning"}[job.state]
        self.event(lvl, "controle: %s — %s" % (job.title, {"ok": "concluído", "warn": "concluído com avisos",
                                                           "error": "falhou"}[job.state]))

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
            raise RuntimeError("nenhum componente encontrado no namespace %s" % self.ns)
        if action == "stop":
            # ordem inversa: rádio primeiro, banco por último
            have = self._by_key()
            for k in reversed(sel):
                job.log("parando %s" % self.LABELS.get(k, k))
                self._scale(have[k][0], 0)
            self._wait_gone(job, [have[k][0] for k in sel])
            return
        if action == "restart":
            job.log("reiniciar = parar tudo e iniciar em ordem")
            self._run_group(job, "stop", target)
        started = set()
        for group in self.ORDER + [[k for k in sel if all(k not in g for g in self.ORDER)]]:
            ks = [k for k in group if k in sel]
            if ks:
                started |= self._start_keys(job, ks, started)

    def _run_one(self, job, action, key):
        have = self._by_key()
        if key not in have:
            raise ValueError("componente desconhecido: %s" % key)
        name, dep = have[key]
        if action == "stop":
            job.log("parando %s" % self.LABELS.get(key, key))
            self._scale(name, 0)
            self._wait_gone(job, [name])
            deps = [k for k in self.DEPENDENTS.get(key, []) if k in have and have[k][1]["spec"].get("replicas", 1)]
            if deps:
                job.log("atenção: %s depende(m) de %s e vai(ão) precisar ser reiniciado(s) quando ele voltar"
                        % (", ".join(self.LABELS.get(k, k) for k in deps), self.LABELS.get(key, key)), "warn")
            return
        if action == "start" or dep["spec"].get("replicas", 1) == 0:
            self._start_keys(job, [key])
            return
        # reiniciar: recria o pod e depois os dependentes que estão rodando
        self._restart_keys(job, [key])
        for k in self.DEPENDENTS.get(key, []):
            if k in have and have[k][1]["spec"].get("replicas", 1) > 0:
                job.log("%s depende de %s: reiniciando também" % (self.LABELS.get(k, k), self.LABELS.get(key, key)))
                self._restart_keys(job, [k])

    # ------------------------------------------------------------------ passos
    def _start_keys(self, job, keys, started=frozenset()):
        """Sobe as chaves; devolve as que foram (re)iniciadas. Um componente já rodando cujo
        "fornecedor" acabou de ser (re)iniciado (ex.: SMF depois de um UPF novo) é reiniciado."""
        have = self._by_key()
        t0 = time.time()
        todo = []
        for k in keys:
            name, dep = have[k]
            label = self.LABELS.get(k, k)
            if dep["spec"].get("replicas", 1) >= 1:
                prov = [p for p, ds in self.DEPENDENTS.items() if k in ds and p in started]
                if self._all_ready(dep) and not prov:
                    job.log("%s já está rodando (mantido)" % label)
                    continue
                if prov:
                    job.log("%s já rodava, mas %s foi reiniciado: reiniciando também"
                            % (label, ", ".join(self.LABELS.get(p, p) for p in prov)))
                    for p in self._pods(dep):
                        self._delete_pod(p["metadata"]["name"])
                    todo.append(k)
                    continue
                # pedido para rodar mas sem ficar pronto (ex.: sem a interface da fibra): recria
                job.log("%s não está pronto; recriando o pod" % label, "warn")
                for p in self._pods(dep):
                    self._delete_pod(p["metadata"]["name"])
            else:
                job.log("iniciando %s" % label)
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
            job.log("reiniciando %s (pod recriado)" % self.LABELS.get(k, k))
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
        """Espera o pod novo ficar pronto e confere o log; recria se subiu com problema."""
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
                raise RuntimeError("%s não ficou pronto em %d s" % (label, READY_TIMEOUT))
            ready, restarts, reason = self._pod_state(pod)
            ck = self.checks(key)
            bad = None
            if restarts or not ready:
                text = self._log(pod, 60)
                bad = "pod caiu (%s)%s" % (reason or "reiniciou",
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
                            bad = "não apareceu no log em %d s: %s" % (secs, ok_re.replace("\\", ""))
                        else:
                            job.log("%s: ainda sem '%s' após %d s (siga no log)" % (label, ok_re, secs), "warn")
                        break
                    time.sleep(2)
            if not bad:
                job.log("%s pronto%s" % (label, " e conferido" if ck else ""))
                return
            if attempt == MAX_RETRY:
                raise RuntimeError("%s com problema: %s" % (label, bad))
            job.log("%s com problema (%s); recriando o pod" % (label, bad), "warn")
            t0 = time.time()
            self._delete_pod(pod["metadata"]["name"])

    def _wait_gone(self, job, names, timeout=120):
        have = {n: d for n, d in self._deps().items() if n in names}
        end = time.time() + timeout
        while time.time() < end:
            left = [n for n, d in have.items() if self._pods(d)]
            if not left:
                job.log("parado(s)")
                return
            time.sleep(2)
        job.log("ainda encerrando após %d s: %s" % (timeout, ", ".join(left)), "warn")


# =============================================================================
#  gNB OCUDU: o agente gnb-ctl (máquina do core) manda o estado a cada poucos
#  segundos e recebe de volta o próximo comando; o resultado vem no envio seguinte.
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
                raise RuntimeError("agente do gNB sem contato (journalctl -u open5gs-k3s-gnb-ctl na máquina do core)")
            self.seq += 1
            cid = "%d-%d" % (int(time.time()), self.seq)
            self.pending = {"id": cid, "action": action, "config": config}
            self.results[cid] = None
            job.log("comando enviado ao %s: %s %s" % (self.target, action, config or ""))
            end = time.time() + timeout
            while self.results[cid] is None and time.time() < end:
                self.cond.wait(1)
            res = self.results.pop(cid)
        if res is None:
            raise RuntimeError("o agente não respondeu em %d s" % timeout)
        for l in (res.get("output") or "").strip().splitlines()[-15:]:
            job.log("  " + l)
        if not res.get("ok"):
            raise RuntimeError("o comando falhou no %s" % self.target)

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
            raise ValueError("escolha o arquivo de configuração")
        if action == "start" and st.get("manual"):
            raise RuntimeError("há um gnb rodando fora do painel (PID %s): pare-o no terminal antes"
                               % ", ".join(str(m["pid"]) for m in st["manual"]))
        if action == "restart" and not st.get("active"):
            if not config:
                raise RuntimeError("nenhum gNB rodando pelo painel; use Iniciar")
            action = "start"
        n2_before = self.n2_ref() if self.n2_ref else None
        self._cmd(job, action, config)
        if action == "stop":
            if self._wait_status(lambda s: not s.get("active") and not s.get("gnb_pids"), 40):
                job.log("gNB parado")
            else:
                job.log("o processo gnb ainda aparece após 40 s", "warn")
            return
        st = self._wait_status(lambda s: (s.get("active") or {}).get("sub") == "running" or s.get("failed"), 30) or {}
        a = st.get("active") or {}
        if a.get("sub") != "running":
            f = st.get("failed") or a
            raise RuntimeError("o serviço não ficou rodando (%s/%s)%s" % (
                f.get("state"), f.get("sub"), ": " + " | ".join(f.get("journal", [])[-4:]) if f.get("journal") else ""))
        time.sleep(5)   # o gnb pode cair logo no início (DPDK/RU): confere de novo
        st = self._wait_status(lambda s: True, 5) or {}
        if st.get("failed") or (st.get("active") or {}).get("sub") != "running":
            f = st.get("failed") or st.get("active") or {}
            raise RuntimeError("o gNB caiu logo depois de iniciar: " + " | ".join(f.get("journal", [])[-4:]))
        job.log("gNB rodando com %s.yml (PID %s)" % (a.get("config"), a.get("pid")))
        # confirmações vindas de fora: RU (DU conectado) e AMF (N2)
        if self.ru_ref:
            end = time.time() + 90
            while time.time() < end:
                if (self.ru_ref.summary() or {}).get("du") == "Ready":
                    job.log("RU: DU conectado (fronthaul ok)")
                    break
                time.sleep(2)
            else:
                job.log("RU ainda sem DU conectado após 90 s (veja a aba RU e o log do gNB)", "warn")
        if self.n2_ref:
            end = time.time() + 60
            while time.time() < end:
                cur = self.n2_ref()
                if cur and cur != n2_before:
                    job.log("AMF: gNB conectado (N2)")
                    break
                time.sleep(2)
            else:
                job.log("o AMF ainda não viu o gNB (N2) após 60 s — o arquivo aponta para este core?", "warn")

    ru_ref = None   # RuState (confere "DU conectado")
    n2_ref = None   # função -> horário do último "gNB-N2 accepted" deste gNB no AMF (ou None)
