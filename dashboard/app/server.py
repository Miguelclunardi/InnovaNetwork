#!/usr/bin/env python3
# =============================================================================
#  dashboard/app/server.py — painel de logs e métricas do open5GK3S.
#
#  Só biblioteca padrão do Python (roda na imagem python:*-slim sem pip).
#  Fontes (todas só leitura):
#    - gNB (OCUDU): WebSocket de métricas (remote_control, {"cmd":"metrics_subscribe"})
#    - Kubernetes: pods e logs do namespace do core (ServiceAccount com get/list/watch)
#    - Open5GS: endpoints Prometheus (:9090/metrics) dos NFs, se ligados
#    - Log do gNB real: linhas enviadas por um agente (POST /api/ingest/gnb-log)
#  Guarda só os últimos HISTORY_SECONDS em memória (sem banco de dados).
# =============================================================================
import base64
import collections
import csv
import hmac
import io
import json
import os
import re
import socket
import ssl
import struct
import threading
import time
import urllib.parse
import urllib.request
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import configedit

# ----------------------------------------------------------------------------
#  Configuração (variáveis de ambiente)
# ----------------------------------------------------------------------------
SA_DIR = "/var/run/secrets/kubernetes.io/serviceaccount"


def _env(name, default=""):
    return os.environ.get(name, default).strip()


def _default_namespace():
    try:
        with open(os.path.join(SA_DIR, "namespace")) as f:
            return f.read().strip()
    except OSError:
        return "open5gs"


NAMESPACE = _env("NAMESPACE") or _default_namespace()
PORT = int(_env("PORT", "8080"))
BIND = _env("BIND", "0.0.0.0")
HISTORY_SECONDS = int(_env("HISTORY_SECONDS", "900"))
GNB_METRICS_URL = _env("GNB_METRICS_URL")              # ex.: ws://10.10.0.1:8001 (vazio = desligado)
GNB_NAME = _env("GNB_NAME", "gNB")
NETWORK_NAME = _env("NETWORK_NAME")
CORE_METRICS = _env("CORE_METRICS", "false").lower() in ("1", "true", "yes", "sim", "on")
CORE_METRICS_PORT = int(_env("CORE_METRICS_PORT", "9090"))
CORE_POLL_SECONDS = float(_env("CORE_POLL_SECONDS", "5"))
OPEN5GS_RELEASE = _env("OPEN5GS_RELEASE", "open5gs")
VERSION = "1.0"
PASSWORD = _env("DASHBOARD_PASSWORD")                  # vazio = sem senha (usuário: admin)
INGEST_TOKEN = _env("INGEST_TOKEN")                    # vazio = ingestão de log do gNB desligada
# Aba Configuração (editar o config.env). Vazio = aba desligada.
ADMIN_PASSWORD = _env("ADMIN_PASSWORD")
CONFIG_PATH = _env("CONFIG_PATH")                      # config.env montado para escrita
PROJECT_DIR = _env("PROJECT_DIR")                      # projeto montado só leitura (validação)
CONFIG_BACKUP_DIR = _env("CONFIG_BACKUP_DIR")
K8S_API = _env("K8S_API")                              # só para desenvolvimento (ex.: kubectl proxy)
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))
# IMSIs dos UEs simulados (UERANSIM), separados por espaço — o resto é SIM real
SIM_IMSIS = set(_env("SIM_IMSIS").split())
# Apelidos: "IMSI=nome;IMSI=nome"
UE_NAMES = dict(kv.split("=", 1) for kv in _env("UE_NAMES").split(";") if "=" in kv)
# Máquinas: a do core é lida direto (HOST_ROOT = /proc e /sys do host montados); as outras chegam
# por um agente (POST /api/ingest/host). HOSTS = "nome|papel;nome|papel" (para listar mesmo sem dados)
HOST_ROOT = _env("HOST_ROOT")
HOST_FSROOT = _env("HOST_FSROOT")
LOCAL_HOST_NAME = _env("LOCAL_HOST_NAME")
LOCAL_HOST_ROLE = _env("LOCAL_HOST_ROLE", "Core 5G (k3s)")
HOSTS = [h.split("|", 1) for h in _env("HOSTS").split(";") if "|" in h]
# Interfaces de túnel do UPF -> DNN ("ogstun=internet;ogstun2=internet2")
UPF_DEVS = dict(kv.split("=", 1) for kv in _env("UPF_DEVS").split(";") if "=" in kv)
HOST_INTERVAL = float(_env("HOST_INTERVAL", "2"))
# Medidor de energia MiEnergy (página /Data com "chave": número). Mede a máquina ENERGY_METER_HOST.
ENERGY_METER_URL = _env("ENERGY_METER_URL")          # ex.: http://192.168.68.105/Data (vazio = desligado)
ENERGY_METER_HOST = _env("ENERGY_METER_HOST")        # nome da máquina na aba Máquinas
ENERGY_INTERVAL = float(_env("ENERGY_INTERVAL", "2"))
UE_INACTIVE_SECONDS = 30
BLER_WINDOW = 10   # s: BLER "agora" dos cartões/tabelas (1 s com poucos blocos oscila demais)
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ----------------------------------------------------------------------------
#  Cliente mínimo da API do Kubernetes
# ----------------------------------------------------------------------------
class K8s:
    def __init__(self):
        self.token = None
        self.ctx = None
        if K8S_API:
            self.base = K8S_API.rstrip("/")
        else:
            host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
            port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
            if ":" in host:
                host = "[%s]" % host
            self.base = "https://%s:%s" % (host, port)
            self.ctx = ssl.create_default_context(cafile=os.path.join(SA_DIR, "ca.crt"))

    def _token(self):
        if K8S_API:
            return None
        # O token projetado é renovado pelo kubelet: relê sempre
        with open(os.path.join(SA_DIR, "token")) as f:
            return f.read().strip()

    def open(self, path, params=None, timeout=15):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
        req = urllib.request.Request(url)
        tok = self._token()
        if tok:
            req.add_header("Authorization", "Bearer " + tok)
        return urllib.request.urlopen(req, timeout=timeout, context=self.ctx)

    def get_json(self, path, params=None):
        with self.open(path, params) as r:
            return json.load(r)

    def get_text(self, path, params=None, timeout=20):
        with self.open(path, params, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")


K8S = K8s()


# ----------------------------------------------------------------------------
#  Cliente WebSocket mínimo (RFC 6455, só o necessário: texto, ping/pong, close)
# ----------------------------------------------------------------------------
class WSClient:
    def __init__(self, url, timeout=10):
        u = urllib.parse.urlparse(url)
        if u.scheme not in ("ws", "wss"):
            raise ValueError("URL deve começar com ws:// ou wss://")
        port = u.port or (443 if u.scheme == "wss" else 80)
        sock = socket.create_connection((u.hostname, port), timeout=timeout)
        if u.scheme == "wss":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=u.hostname)
        self.sock = sock
        key = base64.b64encode(os.urandom(16)).decode()
        path = u.path or "/"
        sock.sendall((
            "GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, u.hostname, port, key)
        ).encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("conexão fechada no handshake")
            buf += chunk
        head, self.buf = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("handshake recusado: %r" % head[:80])
        sock.settimeout(30)  # sem mensagens por 30 s => reconecta

    def _recvn(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("conexão fechada")
            self.buf += chunk
        d, self.buf = self.buf[:n], self.buf[n:]
        return d

    def send(self, opcode, payload=b""):
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            head = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
        elif n < 65536:
            head = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
        else:
            head = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send_text(self, text):
        self.send(0x1, text.encode())

    def recv(self):
        """Devolve a próxima mensagem de texto (junta fragmentos; responde ping)."""
        parts = []
        while True:
            b1, b2 = self._recvn(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._recvn(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._recvn(8))[0]
            mask = self._recvn(4) if b2 & 0x80 else None
            data = self._recvn(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x9:
                self.send(0xA, data)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x8:
                raise ConnectionError("servidor fechou o WebSocket")
            parts.append(data)
            if fin:
                return b"".join(parts).decode("utf-8", "replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


# ----------------------------------------------------------------------------
#  Séries temporais em memória
# ----------------------------------------------------------------------------
class Series:
    """Amostras (t, {campo: valor}) dos últimos HISTORY_SECONDS."""

    def __init__(self):
        self.data = collections.deque()

    def add(self, t, values):
        self.data.append((t, values))
        limit = t - HISTORY_SECONDS
        while self.data and self.data[0][0] < limit:
            self.data.popleft()

    def last(self):
        return self.data[-1] if self.data else (None, {})

    def window(self, since):
        out = {"t": []}
        rows = [r for r in self.data if r[0] >= since]
        keys = []
        for _, v in rows:
            for k in v:
                if k not in out:
                    out[k] = []
                    keys.append(k)
        for t, v in rows:
            out["t"].append(round(t, 3))
            for k in keys:
                out[k].append(v.get(k))
        return out


# ----------------------------------------------------------------------------
#  Coletor do gNB (WebSocket de métricas do OCUDU)
# ----------------------------------------------------------------------------
UE_FIELDS = (
    "dl_brate", "ul_brate", "dl_mcs", "ul_mcs", "cqi", "dl_ri", "ul_ri",
    "dl_nof_ok", "dl_nof_nok", "ul_nof_ok", "ul_nof_nok",
    "pusch_snr_db", "pusch_rsrp_db", "pucch_snr_db", "ta_ns", "bsr", "dl_bs", "last_phr",
    "avg_crc_delay", "avg_pusch_harq_delay", "avg_pucch_harq_delay",
)


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _sum(v):
    return sum(x for x in v if _num(x) is not None) if isinstance(v, list) else _num(v)


class GnbCollector(threading.Thread):
    def __init__(self, url):
        super().__init__(daemon=True, name="gnb")
        self.url = url
        self.lock = threading.Lock()
        self.ues = {}          # (pci, rnti) -> {"series": Series, "first": t, "last": t}
        self.cell = {}         # pci -> Series
        self.du = Series()
        self.status = {"enabled": bool(url), "url": url, "connected": False,
                       "since": None, "last_msg": None, "error": None, "messages": 0, "reconnects": 0}

    def run(self):
        backoff = 1
        while True:
            ws = None
            try:
                ws = WSClient(self.url)
                ws.send_text(json.dumps({"cmd": "metrics_subscribe"}))
                with self.lock:
                    self.status.update(connected=True, since=time.time(), error=None)
                log("gNB: conectado em", self.url)
                backoff = 1
                while True:
                    self._handle(ws.recv())
            except Exception as e:  # noqa: BLE001 — qualquer falha => reconecta
                with self.lock:
                    if self.status["connected"]:
                        self.status["reconnects"] += 1
                    self.status.update(connected=False, error=str(e))
                log("gNB:", e)
            finally:
                if ws:
                    ws.close()
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)

    def _handle(self, text):
        try:
            msg = json.loads(text)
        except ValueError:
            return
        if "cmd" in msg:
            return
        t = time.time()
        with self.lock:
            self.status["last_msg"] = t
            self.status["messages"] += 1
            for c in msg.get("cells") or []:
                self._cell(t, c)
            du = msg.get("du")
            if isinstance(du, dict):
                vals = {}
                for d in ((du.get("du_high") or {}).get("mac") or {}).get("dl") or []:
                    vals["mac_dl_avg_latency_us"] = _num(d.get("average_latency_us"))
                    vals["mac_dl_max_latency_us"] = _num(d.get("max_latency_us"))
                    vals["mac_dl_cpu_percent"] = _num(d.get("cpu_usage_percent"))
                if vals:
                    self.du.add(t, vals)

    def _cell(self, t, c):
        cm = c.get("cell_metrics") or {}
        pci = cm.get("pci")
        ues = c.get("ue_list") or []
        tot_dl = tot_ul = 0.0
        for u in ues:
            key = (u.get("pci", pci), u.get("rnti"))
            v = {f: _num(u.get(f)) for f in UE_FIELDS}
            dok, dnok = v["dl_nof_ok"] or 0, v["dl_nof_nok"] or 0
            uok, unok = v["ul_nof_ok"] or 0, v["ul_nof_nok"] or 0
            v["dl_bler"] = 100.0 * dnok / (dok + dnok) if dok + dnok else None
            v["ul_bler"] = 100.0 * unok / (uok + unok) if uok + unok else None
            # Sem transmissões no período o gNB manda 0 em MCS/SNR: vira lacuna, não zero
            if not dok + dnok:
                v["dl_mcs"] = None
            if not uok + unok:
                v["ul_mcs"] = v["pusch_snr_db"] = v["pusch_rsrp_db"] = None
            tot_dl += v["dl_brate"] or 0
            tot_ul += v["ul_brate"] or 0
            e = self.ues.get(key)
            if e is None:
                e = self.ues[key] = {"series": Series(), "first": t}
            e["last"] = t
            e["series"].add(t, v)
        s = self.cell.setdefault(pci, Series())
        s.add(t, {
            "nof_ues": len(ues),
            "dl_brate": tot_dl, "ul_brate": tot_ul,
            "pdsch_prbs": _sum(cm.get("pdsch_prbs_used_per_tdd_slot_idx")),
            "pusch_prbs": _sum(cm.get("pusch_prbs_used_per_tdd_slot_idx")),
            "pucch_rb_usage": _num(cm.get("pucch_tot_rb_usage_avg")),
            "avg_latency": _num(cm.get("average_latency")),
            "max_latency": _num(cm.get("max_latency")),
            "late_dl_harqs": _num(cm.get("late_dl_harqs")),
            "late_ul_harqs": _num(cm.get("late_ul_harqs")),
            "failed_dl_pdcch": _num(cm.get("failed_dl_pdcch")),
            "failed_ul_pdcch": _num(cm.get("failed_ul_pdcch")),
            "failed_uci_allocs": _num(cm.get("nof_failed_uci_allocs")),
            "error_indication_count": _num(cm.get("error_indication_count")),
            "msg3_nof_ok": _num(cm.get("msg3_nof_ok")),
            "msg3_nof_nok": _num(cm.get("msg3_nof_nok")),
        })
        # Esquece UEs que sumiram há mais que a janela de histórico
        limit = t - HISTORY_SECONDS
        for k in [k for k, e in self.ues.items() if e["last"] < limit]:
            del self.ues[k]

    @staticmethod
    def _last_valid(series, now, horizon=20):
        """Última amostra, completando campos vazios com o último valor válido dos últimos `horizon` s."""
        out = {}
        acc = [0, 0, 0, 0]   # dl ok/nok, ul ok/nok nos últimos BLER_WINDOW s
        for t, v in reversed(series.data):
            if now - t > BLER_WINDOW:
                break
            acc[0] += v.get("dl_nof_ok") or 0
            acc[1] += v.get("dl_nof_nok") or 0
            acc[2] += v.get("ul_nof_ok") or 0
            acc[3] += v.get("ul_nof_nok") or 0
        for t, v in reversed(series.data):
            if now - t > horizon and out:
                break
            for k, x in v.items():
                if out.get(k) is None and x is not None:
                    out[k] = x
                out.setdefault(k, x)
        out["dl_bler_win"] = 100.0 * acc[1] / (acc[0] + acc[1]) if acc[0] + acc[1] else None
        out["ul_bler_win"] = 100.0 * acc[3] / (acc[2] + acc[3]) if acc[2] + acc[3] else None
        out["dl_tbs_win"], out["ul_tbs_win"] = acc[0] + acc[1], acc[2] + acc[3]
        return out

    def snapshot(self, window):
        now = time.time()
        since = now - window
        with self.lock:
            st = dict(self.status)
            ues = []
            for (pci, rnti), e in sorted(self.ues.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1] or 0)):
                last = self._last_valid(e["series"], now)
                ues.append({"id": "%s-%s" % (pci, rnti), "pci": pci, "rnti": rnti,
                            "active": now - e["last"] < UE_INACTIVE_SECONDS,
                            "first_seen": e["first"], "last_seen": e["last"], "last": last,
                            "series": e["series"].window(since)})
            cells = [{"pci": pci, "last": s.last()[1], "series": s.window(since)}
                     for pci, s in sorted(self.cell.items(), key=lambda kv: kv[0] or 0)]
            du = {"last": self.du.last()[1], "series": self.du.window(since)}
        return {"now": now, "status": st, "ues": ues, "cells": cells, "du": du}


# ----------------------------------------------------------------------------
#  Coletor do core (pods, eventos dos logs do AMF/SMF/UPF, métricas Prometheus)
# ----------------------------------------------------------------------------
RE_TS = re.compile(r"^(\S+) ")  # timestamp RFC3339 que o kubelet põe com timestamps=true
RE_GNB_ACC = re.compile(r"gNB-N2 accepted\[([^\]]+)\]")
RE_GNB_N = re.compile(r"Number of gNBs is now (\d+)")
RE_GNB_GONE = re.compile(r"gNB-N2\[([^\]]+)\] (connection refused|.*closed|.*removed)", re.I)
RE_REG_OK = re.compile(r"\[imsi-(\d+)\] Registration complete")
RE_DEREG = re.compile(r"\[imsi-(\d+)\].*(De-register|Deregistration|De-registered)", re.I)
RE_DNN_NOK = re.compile(r"\[imsi-(\d+)\] DNN Not Supported OR Not Subscribed")
RE_REJECT = re.compile(r"\[imsi-(\d+)\].*[Rr]eject")
RE_SESS_ADD = re.compile(r"UE SUPI\[imsi-(\d+)\] DNN\[([^\]]+)\] IPv4\[([^\]]*)\] IPv6\[([^\]]*)\]")
# Identificação do UE: AMF_UE_NGAP_ID -> IMSI (log do AMF). O SUCI em claro (esquema 0) já traz o MSIN.
RE_NGAP_IDS = re.compile(r"RAN_UE_NGAP_ID\[(\d+)\] AMF_UE_NGAP_ID\[(\d+)\]")
RE_IDENT = re.compile(r"\[(?:imsi-(\d{15})|suci-0-(\d{3})-(\d{2,3})-[^-\]]+-0-[^-\]]+-(\d+))[\]:]")
RE_SESS_DEL = re.compile(r"Removed Session: UE IMSI:\[imsi-(\d+)\] DNN:\[([^:\]]+)")


class LogFollower:
    """Lê o log de um pod em pedaços (sinceTime) e repassa linhas novas ao parser.
    Se o pod mudar (uid novo), relê desde o início e o parser zera o estado."""

    def __init__(self, component, container, parser):
        self.component = component
        self.container = container
        self.parser = parser
        self.uid = None
        self.pod = None
        self.last_ts = None
        self.seen_at_last_ts = set()

    def poll(self, pods):
        p = next((p for p in pods if p["component"] == self.component and p["phase"] == "Running"), None)
        if not p:
            return
        if p["uid"] != self.uid:
            self.uid, self.pod, self.last_ts = p["uid"], p["name"], None
            self.seen_at_last_ts = set()
            self.parser.reset(self.component)
        params = {"timestamps": "true", "container": self.container}
        if self.last_ts:
            params["sinceTime"] = self.last_ts
        else:
            params["tailLines"] = "200000"   # 1ª leitura: estado desde o início do pod (limite de segurança)
        try:
            text = K8S.get_text("/api/v1/namespaces/%s/pods/%s/log" % (NAMESPACE, self.pod), params, timeout=30)
        except Exception as e:  # noqa: BLE001
            log("log", self.component, e)
            return
        for raw in text.splitlines():
            m = RE_TS.match(raw)
            if not m:
                continue
            ts, line = m.group(1), ANSI.sub("", raw[m.end():])
            if self.last_ts and ts < self.last_ts:
                continue
            if ts == self.last_ts:
                if raw in self.seen_at_last_ts:
                    continue
            if ts != self.last_ts:
                self.last_ts, self.seen_at_last_ts = ts, set()
            self.seen_at_last_ts.add(raw)
            self.parser.line(self.component, ts, line)


class CoreState:
    """Estado derivado dos logs: gNBs (N2), UEs, sessões PDU e eventos relevantes."""

    def __init__(self):
        self.lock = threading.Lock()
        self.gnbs = {}         # ip -> {"accepted": ts}
        self.nof_gnbs = None
        self.ues = {}          # imsi -> {"event": str, "ts": str, "registered": bool}
        self.sessions = {}     # (imsi, dnn) -> {"ipv4": ..., "ipv6": ..., "ts": ...}
        self.events = collections.OrderedDict()   # chave normalizada -> evento (agrupa repetidos)
        self.counters = collections.Counter()
        self.amf_ids = collections.OrderedDict()   # AMF_UE_NGAP_ID -> IMSI
        self._n = 0
        self._ident = (None, -99)    # (imsi, nº da linha) da última identidade vista no log do AMF
        self._pend = (None, -99)     # (AMF_UE_NGAP_ID, nº da linha) ainda sem identidade

    def _map_amf(self, amf_id, imsi):
        self.amf_ids[amf_id] = imsi
        self.amf_ids.move_to_end(amf_id)
        while len(self.amf_ids) > 5000:
            self.amf_ids.popitem(last=False)

    def _ngap_ident(self, line):
        self._n += 1
        m = RE_IDENT.search(line)
        imsi = None
        if m:
            imsi = m.group(1) or (m.group(2) + m.group(3) + m.group(4))
            if len(imsi) != 15:
                imsi = None
        m2 = RE_NGAP_IDS.search(line)
        if m2:
            amf_id = int(m2.group(2))
            if self._ident[0] and self._n - self._ident[1] <= 3:
                self._map_amf(amf_id, self._ident[0])
                self._pend = (None, -99)
            else:
                self._pend = (amf_id, self._n)
        elif imsi:
            if self._pend[0] is not None and self._n - self._pend[1] <= 20:
                self._map_amf(self._pend[0], imsi)
                self._pend = (None, -99)
            self._ident = (imsi, self._n)

    def imsi_of(self, amf_id):
        with self.lock:
            return self.amf_ids.get(amf_id)

    def reset(self, component):
        with self.lock:
            if component == "amf":
                self.amf_ids.clear()
                self.gnbs.clear()
                self.nof_gnbs = None
                self.ues.clear()
            elif component == "smf":
                self.sessions.clear()
            for k in [k for k, e in self.events.items() if e["src"] == component]:
                del self.events[k]

    def _ue(self, imsi, ev, ts, registered=None):
        u = self.ues.setdefault(imsi, {"registered": False})
        u["event"], u["ts"] = ev, ts
        if registered is not None:
            u["registered"] = registered

    def line(self, comp, ts, line):
        with self.lock:
            lvl = None
            if "] ERROR:" in line or "] FATAL:" in line:
                lvl = "error"
            elif "] WARNING:" in line:
                lvl = "warning"
            if comp == "amf":
                self._ngap_ident(line)
                m = RE_GNB_ACC.search(line)
                if m:
                    self.gnbs[m.group(1)] = {"accepted": ts}
                    self._event(ts, comp, "info", "gNB conectou (N2) de %s" % m.group(1))
                m = RE_GNB_N.search(line)
                if m:
                    self.nof_gnbs = int(m.group(1))
                m = RE_GNB_GONE.search(line)
                if m:
                    self.gnbs.pop(m.group(1), None)
                    self._event(ts, comp, "warning", "gNB desconectou (N2): %s" % m.group(1))
                m = RE_REG_OK.search(line)
                if m:
                    self._ue(m.group(1), "registrado", ts, True)
                    self.counters["registrations"] += 1
                m = RE_DEREG.search(line)
                if m:
                    self._ue(m.group(1), "desregistrado", ts, False)
                    self._event(ts, comp, "info", "UE %s desregistrou" % m.group(1))
                m = RE_DNN_NOK.search(line)
                if m:
                    # Normalmente o UE pedindo uma DNN extra (ex.: ims) que não está na assinatura: inofensivo
                    self._ue(m.group(1), "pediu DNN fora da assinatura (ex.: ims) — recusada", ts)
                    self.counters["dnn_not_subscribed"] += 1
                elif lvl and RE_REJECT.search(line):
                    m = RE_REJECT.search(line)
                    self._ue(m.group(1), "rejeição", ts)
            elif comp == "smf":
                m = RE_SESS_ADD.search(line)
                if m:
                    self.sessions[(m.group(1), m.group(2))] = {"ipv4": m.group(3), "ipv6": m.group(4), "ts": ts}
                    self._event(ts, comp, "info", "sessão PDU: %s %s %s" % (m.group(1), m.group(2), m.group(3)))
                m = RE_SESS_DEL.search(line)
                if m:
                    self.sessions.pop((m.group(1), m.group(2)), None)
            elif comp == "upf":
                if "Cannot find PFCP-Node" in line:
                    self.counters["pfcp_cannot_find"] += 1
            if lvl:
                self.counters["%s_%s" % (comp, lvl)] += 1
                msg = line.split("] ", 1)[-1] if "] " in line else line
                msg = re.sub(r"^(ERROR|WARNING|FATAL): ", "", msg)
                self._event(ts, comp, lvl, msg[:300])

    def _event(self, ts, src, lvl, msg):
        # Mensagens iguais (a menos de números/IDs) viram uma linha com contador
        norm = msg if lvl == "info" else re.sub(r"\d+", "#", re.sub(r"\(\.\./[^)]*\)", "", msg))
        key = (src, lvl, norm)
        e = self.events.pop(key, None)
        if e:
            e["count"] += 1
            e["ts"], e["msg"] = ts, msg
        else:
            e = {"ts": ts, "first": ts, "src": src, "level": lvl, "msg": msg, "count": 1}
        self.events[key] = e
        while len(self.events) > 400:
            self.events.popitem(last=False)

    def snapshot(self):
        with self.lock:
            return {
                "nof_gnbs": self.nof_gnbs,
                "gnbs": [{"addr": k, **v} for k, v in sorted(self.gnbs.items())],
                "ues": [{"imsi": k, **v, "kind": "ueransim" if k in SIM_IMSIS else "real", "name": UE_NAMES.get(k, ""),
                         "sessions": [{"dnn": d, **s} for (i, d), s in sorted(self.sessions.items()) if i == k]}
                        for k, v in sorted(self.ues.items(), key=lambda kv: (kv[0] in SIM_IMSIS, kv[0]))],
                "sessions": [{"imsi": i, "dnn": d, **s} for (i, d), s in sorted(self.sessions.items())],
                "events": list(self.events.values())[-150:][::-1],
                "counters": dict(self.counters),
            }


def parse_prom(text):
    """Formato texto do Prometheus => {nome: [(labels, valor)]} (ignora HELP/TYPE)."""
    out = collections.defaultdict(list)
    types = {}
    for line in text.splitlines():
        if line.startswith("# TYPE "):
            parts = line.split()
            if len(parts) >= 4:
                types[parts[2]] = parts[3]
            continue
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+(\S+)", line)
        if not m:
            continue
        try:
            val = float(m.group(3))
        except ValueError:
            continue
        out[m.group(1)].append((m.group(2) or "", val))
    return out, types


class CoreCollector(threading.Thread):
    METRIC_NFS = ("amf", "smf", "upf", "pcf")

    def __init__(self):
        super().__init__(daemon=True, name="core")
        self.lock = threading.Lock()
        self.state = CoreState()
        self.pods = []
        self.pods_error = None
        self.followers = [LogFollower("amf", "open5gs-amf", self.state),
                          LogFollower("smf", "open5gs-smf", self.state),
                          LogFollower("upf", "open5gs-upf", self.state)]
        self.metrics = {}           # nf -> {"latest": {name: [(labels, v)]}, "types": {}, "error": str}
        self.metric_series = {}     # nf -> Series({nome: soma})
        self.metrics_ts = None

    def run(self):
        while True:
            t0 = time.time()
            try:
                self._poll_pods()
            except Exception as e:  # noqa: BLE001
                with self.lock:
                    self.pods_error = str(e)
                log("pods:", e)
            pods = self.pods
            for f in self.followers:
                try:
                    f.poll(pods)
                except Exception as e:  # noqa: BLE001
                    log("seguidor", f.component, e)
            if CORE_METRICS:
                self._scrape(pods)
            time.sleep(max(0.5, CORE_POLL_SECONDS - (time.time() - t0)))

    def _poll_pods(self):
        data = K8S.get_json("/api/v1/namespaces/%s/pods" % NAMESPACE)
        now = time.time()
        pods = []
        for it in data.get("items", []):
            md, st, spec = it["metadata"], it.get("status", {}), it.get("spec", {})
            labels = md.get("labels", {})
            comp = labels.get("app.kubernetes.io/name") or labels.get("app") or md["name"]
            cs = st.get("containerStatuses") or []
            ready = sum(1 for c in cs if c.get("ready"))
            restarts = sum(c.get("restartCount", 0) for c in cs)
            phase = st.get("phase", "?")
            if md.get("deletionTimestamp"):
                phase = "Terminating"
            reason = ""
            for c in cs:
                w = (c.get("state") or {}).get("waiting")
                if w:
                    reason = w.get("reason", "")
            net1 = ""
            try:
                for n in json.loads(md.get("annotations", {}).get("k8s.v1.cni.cncf.io/network-status", "[]")):
                    if n.get("interface") == "net1":
                        net1 = ",".join(n.get("ips", []))
            except ValueError:
                pass
            started = st.get("startTime")
            age = None
            if started:
                age = now - _parse_rfc3339(started)
            pods.append({
                "name": md["name"], "uid": md["uid"], "component": comp,
                "label": labels.get("app.kubernetes.io/component") or comp,
                "instance": labels.get("app.kubernetes.io/instance", ""),
                "phase": phase, "reason": reason, "ready": "%d/%d" % (ready, len(cs)),
                "all_ready": bool(cs) and ready == len(cs), "restarts": restarts,
                "age": age, "ip": st.get("podIP", ""), "net1": net1,
                "containers": [c["name"] for c in spec.get("containers", [])],
            })
        pods.sort(key=lambda p: p["name"])
        with self.lock:
            self.pods, self.pods_error = pods, None

    def _scrape(self, pods):
        now = time.time()
        for nf in self.METRIC_NFS:
            p = next((p for p in pods if p["component"] == nf and p["phase"] == "Running" and p["ip"]), None)
            entry = {"latest": {}, "types": {}, "error": None, "pod": p["name"] if p else None}
            if not p:
                entry["error"] = "pod não encontrado"
            else:
                try:
                    url = "http://%s:%d/metrics" % (p["ip"], CORE_METRICS_PORT)
                    with urllib.request.urlopen(url, timeout=4) as r:
                        latest, types = parse_prom(r.read().decode("utf-8", "replace"))
                    entry["latest"], entry["types"] = dict(latest), types
                    sums = {k: sum(v for _, v in vals) for k, vals in latest.items()
                            if not k.startswith(("process_", "go_", "promhttp_"))}
                    with self.lock:
                        self.metric_series.setdefault(nf, Series()).add(now, sums)
                except Exception as e:  # noqa: BLE001
                    entry["error"] = str(e)
            with self.lock:
                self.metrics[nf] = entry
        with self.lock:
            self.metrics_ts = now

    def snapshot(self):
        with self.lock:
            return {"pods": list(self.pods), "pods_error": self.pods_error, **self.state.snapshot()}

    def metrics_snapshot(self, window):
        since = time.time() - window
        with self.lock:
            out = {}
            for nf, e in self.metrics.items():
                s = self.metric_series.get(nf)
                out[nf] = {
                    "pod": e.get("pod"), "error": e.get("error"), "types": e.get("types", {}),
                    "latest": {k: [{"labels": l, "value": v} for l, v in vals]
                               for k, vals in sorted(e.get("latest", {}).items())
                               if not k.startswith(("process_", "go_", "promhttp_"))},
                    "series": s.window(since) if s else {"t": []},
                }
            return {"enabled": CORE_METRICS, "ts": self.metrics_ts, "nfs": out}


def _parse_rfc3339(s):
    import calendar
    s = s.rstrip("Z").split(".")[0]
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))


# ----------------------------------------------------------------------------
#  Máquinas (CPU, memória, temperaturas, rede, discos, processos)
# ----------------------------------------------------------------------------
class Hosts:
    def __init__(self):
        self.lock = threading.Lock()
        self.h = {}   # nome -> {"role", "source", "last", "ts", "error", "series"}
        for name, role in HOSTS:
            self._entry(name, role, "agente")

    def _entry(self, name, role, source):
        e = self.h.get(name)
        if e is None:
            e = self.h[name] = {"name": name, "role": role, "source": source, "last": None, "ts": None,
                                "error": None, "series": Series()}
        if role:
            e["role"] = role
        return e

    def push(self, name, role, source, sample=None, error=None):
        with self.lock:
            e = self._entry(name, role, source)
            if error:
                e["error"] = error
                return
            if not sample or "cpu" not in sample:
                return
            t = time.time()
            e.update(last=sample, ts=t, error=None)
            v = {"cpu": sample.get("cpu"), "mem": sample.get("mem_used_pct"), "temp": sample.get("temp_cpu"),
                 "load1": (sample.get("load") or [None])[0]}
            for n in sample.get("net") or []:
                v["rx:" + n["iface"]] = n["rx_bps"] / 1e6
                v["tx:" + n["iface"]] = n["tx_bps"] / 1e6
            e["series"].add(t, v)

    def summary(self):
        now = time.time()
        with self.lock:
            out = []
            for e in self.h.values():
                l = e["last"] or {}
                out.append({"name": e["name"], "role": e["role"], "source": e["source"], "error": e["error"],
                            "age": now - e["ts"] if e["ts"] else None,
                            "online": bool(e["ts"] and now - e["ts"] < 15),
                            **{k: l.get(k) for k in ("hostname", "cpu_model", "ncpu", "cpu", "mem_used_pct", "mem_total",
                                                      "temp_cpu", "load", "uptime", "isolated_cpus")}})
            return out

    def detail(self, name, window):
        with self.lock:
            e = self.h.get(name)
            if not e:
                return None
            return {"name": e["name"], "role": e["role"], "source": e["source"], "error": e["error"],
                    "age": time.time() - e["ts"] if e["ts"] else None, "last": e["last"],
                    "series": e["series"].window(time.time() - window)}


# Campos do MiEnergy (monofásico) mostrados com nome; os demais aparecem na tabela crua
ENERGY_FIELDS = {"p_a": "power", "v_a": "voltage", "i_a": "current", "fp_a": "pf", "freq": "freq",
                 "frequencia": "freq", "energia_ativa_total": "energy_kwh"}
RE_ENERGY = re.compile(r'([a-zA-Z0-9_]+)["\':\s]+([-\d\.]+)')   # mesmo filtro do collector.py do MiEnergy


class EnergyMeter(threading.Thread):
    def __init__(self, url):
        super().__init__(daemon=True, name="energia")
        self.url = url
        self.lock = threading.Lock()
        self.series = Series()
        self.last = {}
        self.ts = None
        self.error = None
        self.first_energy = None

    def run(self):
        while True:
            t0 = time.time()
            try:
                with urllib.request.urlopen(self.url, timeout=5) as r:
                    text = r.read(256 * 1024).decode("utf-8", "replace")
                vals = {}
                for k, v in RE_ENERGY.findall(text):
                    try:
                        vals[k] = float(v)
                    except ValueError:
                        pass
                if not vals:
                    raise ValueError("resposta sem números: %r" % text[:120])
                now = time.time()
                main = {ENERGY_FIELDS[k]: v for k, v in vals.items() if k in ENERGY_FIELDS}
                with self.lock:
                    self.last, self.ts, self.error = vals, now, None
                    if self.first_energy is None and "energy_kwh" in main:
                        self.first_energy = (now, main["energy_kwh"])
                    self.series.add(now, main)
            except Exception as e:  # noqa: BLE001
                with self.lock:
                    self.error = str(e)
            time.sleep(max(0.2, ENERGY_INTERVAL - (time.time() - t0)))

    def summary(self):
        with self.lock:
            return self.summary_unlocked()

    def detail(self, window):
        with self.lock:
            out = self.summary_unlocked()
            out["fields"] = dict(sorted(self.last.items()))
            out["series"] = self.series.window(time.time() - window)
            if self.first_energy and "energy_kwh" in out:
                out["energy_since"] = self.first_energy[0]
                out["energy_delta_kwh"] = out["energy_kwh"] - self.first_energy[1]
            return out

    def summary_unlocked(self):
        main = {ENERGY_FIELDS[k]: v for k, v in self.last.items() if k in ENERGY_FIELDS}
        return {"online": bool(self.ts and time.time() - self.ts < 15), "error": self.error, "ts": self.ts,
                "url": self.url, **main}


def local_host_loop(hosts):
    import hoststats
    c = hoststats.Collector(HOST_ROOT, HOST_FSROOT or None)
    name = LOCAL_HOST_NAME or c.static.get("hostname") or "core"
    c.sample()
    while True:
        time.sleep(HOST_INTERVAL)
        try:
            hosts.push(name, LOCAL_HOST_ROLE, "local", c.sample())
        except Exception as e:  # noqa: BLE001
            hosts.push(name, LOCAL_HOST_ROLE, "local", error=str(e))
            log("máquina local:", e)


# ----------------------------------------------------------------------------
#  Log do gNB real (recebido de um agente no host do gNB)
# ----------------------------------------------------------------------------
# Só linhas do CU (RRC/CU-CP/NGAP): nelas "ue=" é o índice do UE no CU-CP. No [SCHED]/[MAC] "ue=" é do DU.
# ----------------------------------------------------------------------------
#  Core sem Prometheus: CPU/memória de cada NF e tráfego do UPF lidos do /proc do host
#  (o pod monta /proc do host só leitura). Não exige reiniciar nada do core.
# ----------------------------------------------------------------------------
NF_PROCS = {"mongod": "mongodb"}   # demais: open5gs-<nf>d -> <nf>


class CoreProcs:
    def __init__(self, root):
        self.proc = root.rstrip("/") + "/proc"
        self.lock = threading.Lock()
        self.cpu = Series()        # {nf: %CPU}
        self.traffic = Series()    # {iface_rx/iface_tx: bit/s} do UPF
        self.nfs = {}
        self.ifaces = {}
        self.prev = None
        self.error = None
        self.hz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100

    @staticmethod
    def _nf(comm):
        if comm in NF_PROCS:
            return NF_PROCS[comm]
        if comm.startswith("open5gs-") and comm.endswith("d"):
            return comm[8:-1]
        return None

    def _read(self, path):
        with open(path) as f:
            return f.read()

    def sample(self):
        now = time.time()
        procs = {}
        for pid in os.listdir(self.proc):
            if not pid.isdigit():
                continue
            try:
                st = self._read("%s/%s/stat" % (self.proc, pid))
            except OSError:
                continue
            r = st.rfind(")")
            nf = self._nf(st[st.find("(") + 1:r])
            if not nf:
                continue
            f = st[r + 2:].split()
            try:
                procs[pid] = (nf, int(f[11]) + int(f[12]), int(f[21]) * 4096, int(f[17]), int(f[19]))
            except (IndexError, ValueError):
                continue
        net = {}
        upf = [pid for pid, p in procs.items() if p[0] == "upf"]
        if upf:
            try:
                for line in self._read("%s/%s/net/dev" % (self.proc, upf[0])).splitlines()[2:]:
                    name, _, rest = line.partition(":")
                    name, v = name.strip(), rest.split()
                    if name and name != "lo":
                        net[name] = (int(v[0]), int(v[8]))
            except (OSError, IndexError, ValueError):
                pass
        with self.lock:
            prev, self.prev = self.prev, (now, procs, net)
            if not prev:
                return
            t0, procs0, net0 = prev
            dt = max(now - t0, 1e-3)
            nfs = {}
            for pid, (nf, ticks, rss, threads, _) in procs.items():
                e = nfs.setdefault(nf, {"nf": nf, "pids": [], "cpu": 0.0, "rss": 0, "threads": 0})
                e["pids"].append(int(pid))
                e["rss"] += rss
                e["threads"] += threads
                p0 = procs0.get(pid)
                if p0 and p0[0] == nf:
                    e["cpu"] += 100.0 * (ticks - p0[1]) / self.hz / dt
            for e in nfs.values():
                e["cpu"] = round(e["cpu"], 1)
            self.nfs = nfs
            self.cpu.add(now, {nf: e["cpu"] for nf, e in nfs.items()})
            tr, ifs = {}, {}
            for name, (rx, tx) in net.items():
                a = net0.get(name)
                if a and rx >= a[0] and tx >= a[1]:
                    tr[name + "_rx"] = (rx - a[0]) * 8 / dt
                    tr[name + "_tx"] = (tx - a[1]) * 8 / dt
                ifs[name] = {"iface": name, "rx_bytes": rx, "tx_bytes": tx, "role": self.role(name),
                             "rx_bps": tr.get(name + "_rx"), "tx_bps": tr.get(name + "_tx")}
            self.ifaces = ifs
            self.traffic.add(now, tr)

    @staticmethod
    def role(name):
        if name in UPF_DEVS:
            return "N6 · DNN %s (rx = uplink, tx = downlink)" % UPF_DEVS[name]
        if name.startswith("ogstun"):
            return "N6 · túnel dos UEs (rx = uplink, tx = downlink)"
        if name == "net1":
            return "N3 · link com o gNB, GTP-U (rx = uplink, tx = downlink)"
        if name == "eth0":
            return "rede do pod (N4/PFCP e saída N6 com NAT)"
        return ""

    def run(self):
        while True:
            try:
                self.sample()
                self.error = None
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
            time.sleep(2)

    def snapshot(self, window):
        since = time.time() - window
        with self.lock:
            return {"enabled": True, "error": self.error, "nfs": sorted(self.nfs.values(), key=lambda e: e["nf"]),
                    "ifaces": sorted(self.ifaces.values(), key=lambda e: e["iface"]),
                    "cpu": self.cpu.window(since), "traffic": self.traffic.window(since), "devs": UPF_DEVS}


RE_LOG_CRNTI = re.compile(r"\[(?:RRC|CU-CP) *\] \[\w\] ue=(\d+) c-rnti=0x([0-9a-fA-F]+)")
RE_LOG_AMFUE = re.compile(r"\[NGAP *\] \[\w\] (?:[TR]x PDU )?ue=(\d+) ran_ue=\d+ amf_ue=(\d+)")


def ue_identity(rnti):
    """RNTI do gNB -> IMSI, nome, tipo e IPs (log do gNB + log do AMF + sessões do SMF)."""
    try:
        rnti = int(rnti)
    except (TypeError, ValueError):
        return {}
    amf_id = GNBLOG.amf_id_of(rnti)
    if amf_id is None:
        return {}
    imsi = CORE.state.imsi_of(amf_id)
    if not imsi:
        return {"amf_ue_id": amf_id}
    with CORE.state.lock:
        ips = [{"dnn": d, "ipv4": s.get("ipv4")} for (i, d), s in sorted(CORE.state.sessions.items()) if i == imsi]
    return {"amf_ue_id": amf_id, "imsi": imsi, "name": UE_NAMES.get(imsi, ""),
            "kind": "ueransim" if imsi in SIM_IMSIS else "real", "sessions": ips}


class GnbLog:
    def __init__(self, maxlen=20000):
        self.lines = collections.deque(maxlen=maxlen)
        self.seq = 0
        self.cond = threading.Condition()
        self.last_push = None
        self.source = None
        self.rnti_cu = {}     # RNTI (int) -> índice do UE no CU-CP
        self.cu_amf = {}      # índice do UE no CU-CP -> AMF_UE_NGAP_ID

    def _ident(self, ln):
        m = RE_LOG_CRNTI.search(ln)
        if m:
            self.rnti_cu[int(m.group(2), 16)] = int(m.group(1))
        m = RE_LOG_AMFUE.search(ln)
        if m:
            self.cu_amf[int(m.group(1))] = int(m.group(2))
        if len(self.rnti_cu) > 5000:
            self.rnti_cu = dict(list(self.rnti_cu.items())[-2000:])
            self.cu_amf = dict(list(self.cu_amf.items())[-2000:])

    def amf_id_of(self, rnti):
        with self.cond:
            cu = self.rnti_cu.get(rnti)
            return self.cu_amf.get(cu) if cu is not None else None

    def ident_only(self, lines):
        """Linhas antigas só para montar o vínculo RNTI -> UE (não entram na tela de log)."""
        with self.cond:
            for ln in lines:
                self._ident(ln)

    def push(self, lines, source):
        with self.cond:
            for ln in lines:
                self.seq += 1
                self.lines.append((self.seq, ln))
                if "c-rnti=" in ln or "amf_ue=" in ln:
                    self._ident(ln)
            self.last_push = time.time()
            self.source = source
            self.cond.notify_all()

    def tail(self, n):
        with self.cond:
            return list(self.lines)[-n:]

    def after(self, seq, timeout):
        with self.cond:
            if not (self.lines and self.lines[-1][0] > seq):
                self.cond.wait(timeout)
            return [(s, l) for s, l in self.lines if s > seq]


# ----------------------------------------------------------------------------
#  HTTP
# ----------------------------------------------------------------------------
GNB = GnbCollector(GNB_METRICS_URL)
CORE = CoreCollector()
GNBLOG = GnbLog()
ENERGY = EnergyMeter(ENERGY_METER_URL) if ENERGY_METER_URL else None
COREPROCS = CoreProcs(HOST_ROOT) if HOST_ROOT else None
HOSTS_STATE = Hosts()
STARTED = time.time()

CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
                 ".ico": "image/x-icon"}
# ----------------------------------------------------------------------------- aba Configuração
class Admin:
    """Sessões do administrador (senha própria, token em memória, 8 h)."""
    TTL = 8 * 3600

    def __init__(self):
        self.lock = threading.Lock()
        self.sessions = {}
        self.fail_until = 0.0

    def login(self, password):
        with self.lock:
            if time.time() < self.fail_until:
                return None
            if not ADMIN_PASSWORD or not hmac.compare_digest(str(password), ADMIN_PASSWORD):
                self.fail_until = time.time() + 2   # freia tentativa de adivinhar a senha
                return None
            tok = secrets.token_urlsafe(32)
            self.sessions[tok] = time.time() + self.TTL
            return tok

    def check(self, tok):
        with self.lock:
            now = time.time()
            for k in [k for k, v in self.sessions.items() if v < now]:
                del self.sessions[k]
            return bool(tok) and any(hmac.compare_digest(tok, k) for k in self.sessions)

    def logout(self, tok):
        with self.lock:
            self.sessions.pop(tok, None)


ADMIN = Admin()
CONFIG = (configedit.ConfigStore(CONFIG_PATH, os.path.join(PROJECT_DIR, "config.env"), PROJECT_DIR, CONFIG_BACKUP_DIR)
          if ADMIN_PASSWORD and CONFIG_PATH and PROJECT_DIR and CONFIG_BACKUP_DIR else None)
CONFIG_LOCK = threading.Lock()
MASK = "••••••••"


def settings_view(reveal):
    text, h = CONFIG.read()
    secs = configedit.parse(text)
    for s in secs:
        for v in s["vars"]:
            v.pop("line", None), v.pop("end", None)
            if v["secret"] and not reveal:
                if "value" in v:
                    v["value"] = MASK if v["value"] else ""
                if "items" in v:
                    v["items"] = [x.split(":")[0] + ":" + MASK if ":" in x else MASK for x in v["items"]]
                v["notes_in_array"] = []
    return {"sections": secs, "hash": h, "revealed": bool(reveal), "backups": CONFIG.backups(),
            "writable": os.access(CONFIG_PATH, os.W_OK)}


def settings_plan(body):
    """Texto novo + diff + impacto + validação para um pedido de alteração."""
    text, h = CONFIG.read()
    if body.get("restore"):
        new = CONFIG.backup_text(body["restore"])
    else:
        changes = body.get("changes")
        if isinstance(changes, dict) and any(
                (isinstance(v, str) and MASK in v) or (isinstance(v, list) and any(MASK in str(x) for x in v))
                for v in changes.values()):
            raise configedit.ConfigError("há campos secretos ainda mascarados: clique em 'mostrar segredos' antes de editá-los")
        new = configedit.apply_changes(text, changes)
    names = configedit.changed_vars(text, new)
    return text, h, new, {"diff": configedit.diff(text, new), "changed": names, "impact": configedit.impact(names),
                          "validation": configedit.validate(PROJECT_DIR, new) if names else {"ok": True, "output": ""}}


STATIC_FILES = {"settings.js", "index.html", "app.js", "hosts.js", "style.css", "uPlot.iife.min.js", "uPlot.min.css", "favicon.svg"}


def _q(qs, name, default=None, cast=str):
    v = qs.get(name, [default])[0]
    if v in (None, ""):
        return default
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


class Handler(BaseHTTPRequestHandler):
    server_version = "open5gk3s-dashboard/" + VERSION
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # silencioso (só erros)
        pass

    # ---- utilidades
    def _auth_ok(self):
        if not PASSWORD:
            return True
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(h[6:]).decode().partition(":")
                return hmac.compare_digest(pw, PASSWORD)
            except (ValueError, UnicodeDecodeError):
                return False
        return False

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, separators=(",", ":"))
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _sse_start(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _sse(self, data, event=None):
        msg = ""
        if event:
            msg += "event: %s\n" % event
        for part in str(data).split("\n"):
            msg += "data: %s\n" % part
        self.wfile.write((msg + "\n").encode())
        self.wfile.flush()

    # ---- rotas
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        path = u.path
        if path == "/api/health":
            return self._send(200, {"ok": True, "uptime": time.time() - STARTED})
        if not self._auth_ok():
            return self._send(401, {"error": "autenticação necessária"},
                              extra={"WWW-Authenticate": 'Basic realm="open5GK3S"'})
        try:
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.lstrip("/") in STATIC_FILES:
                return self._static(path.lstrip("/"))
            if path == "/api/config":
                return self._send(200, {"namespace": NAMESPACE, "gnb_name": GNB_NAME, "network_name": NETWORK_NAME, "gnb_url": GNB_METRICS_URL,
                                        "history_seconds": HISTORY_SECONDS, "core_metrics": CORE_METRICS,
                                        "gnb_log_ingest": bool(INGEST_TOKEN), "release": OPEN5GS_RELEASE,
                                        "config_edit": bool(CONFIG), "version": VERSION})
            if path == "/api/settings":
                if not self._admin():
                    return None
                return self._send(200, settings_view(_q(qs, "reveal", "") == "1"))
            if path == "/api/settings/backup":
                if not self._admin():
                    return None
                text, _ = CONFIG.read()
                return self._send(200, {"diff": configedit.diff(text, CONFIG.backup_text(_q(qs, "name", "")))})
            if path == "/api/overview":
                return self._send(200, self._overview())
            if path == "/api/ran":
                snap = GNB.snapshot(min(_q(qs, "window", 300, int), HISTORY_SECONDS))
                for u in snap["ues"]:
                    u["ident"] = ue_identity(u["rnti"])
                snap["ident_source"] = bool(GNBLOG.last_push)
                snap["ident_stats"] = {"rnti": len(GNBLOG.rnti_cu), "cu_amf": len(GNBLOG.cu_amf),
                                       "amf_imsi": len(CORE.state.amf_ids)}
                return self._send(200, snap)
            if path == "/api/ran.csv":
                return self._ran_csv(min(_q(qs, "window", HISTORY_SECONDS, int), HISTORY_SECONDS))
            if path == "/api/core":
                return self._send(200, CORE.snapshot())
            if path == "/api/core/live":
                win = min(_q(qs, "window", 300, int), HISTORY_SECONDS)
                d = COREPROCS.snapshot(win) if COREPROCS else {"enabled": False}
                core = CORE.snapshot()
                d["log"] = {"nof_gnbs": core["nof_gnbs"], "gnbs": core["gnbs"], "counters": core["counters"],
                            "ues_registered": sum(1 for u in core["ues"] if u.get("registered")),
                            "ues_total": len(core["ues"]), "sessions": len(core["sessions"])}
                d["prometheus"] = CORE_METRICS
                return self._send(200, d)
            if path == "/api/core/metrics":
                return self._send(200, CORE.metrics_snapshot(min(_q(qs, "window", 300, int), HISTORY_SECONDS)))
            if path == "/api/logs":
                return self._logs(qs)
            if path == "/api/logs/stream":
                return self._logs_stream(qs)
            if path == "/api/gnb-log":
                n = min(_q(qs, "tail", 500, int), 20000)
                lines = GNBLOG.tail(n)
                return self._send(200, {"last_push": GNBLOG.last_push, "source": GNBLOG.source,
                                        "seq": lines[-1][0] if lines else 0, "lines": [l for _, l in lines]})
            if path == "/api/gnb-log/stream":
                return self._gnblog_stream(qs)
            if path == "/api/hosts":
                hs = HOSTS_STATE.summary()
                if ENERGY:
                    for h in hs:
                        if h["name"] == ENERGY_METER_HOST:
                            h["energy"] = ENERGY.summary()
                return self._send(200, {"hosts": hs})
            if path.startswith("/api/hosts/"):
                win = min(_q(qs, "window", 300, int), HISTORY_SECONDS)
                d = HOSTS_STATE.detail(urllib.parse.unquote(path[len("/api/hosts/"):]), win)
                if d and ENERGY and d["name"] == ENERGY_METER_HOST:
                    d["energy"] = ENERGY.detail(win)
                return self._send(200, d) if d else self._send(404, {"error": "máquina desconhecida"})
            return self._send(404, {"error": "não encontrado"})
        except (BrokenPipeError, ConnectionResetError):
            return None
        except urllib.error.HTTPError as e:
            return self._send(e.code, {"error": e.read().decode("utf-8", "replace")[:500]})
        except Exception as e:  # noqa: BLE001
            log("erro", path, repr(e))
            return self._send(500, {"error": str(e)})

    def _admin(self):
        """Exige a sessão de administrador (cabeçalho X-Admin-Token). Responde 401/404 se faltar."""
        if not CONFIG:
            self._send(404, {"error": "edição do config.env desligada (sem senha de administrador)"})
            return False
        if not ADMIN.check(self.headers.get("X-Admin-Token", "")):
            self._send(401, {"error": "entre com a senha de administrador", "admin": True})
            return False
        return True

    def _json_body(self, limit=1024 * 1024):
        n = int(self.headers.get("Content-Length", "0") or 0)
        if n > limit:
            raise configedit.ConfigError("pedido grande demais")
        d = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        if not isinstance(d, dict):
            raise configedit.ConfigError("JSON inválido")
        return d

    def _settings_post(self, path):
        if not self._auth_ok():
            return self._send(401, {"error": "autenticação necessária"},
                              extra={"WWW-Authenticate": 'Basic realm="open5GK3S"'})
        try:
            body = self._json_body()
        except (ValueError, configedit.ConfigError) as e:
            return self._send(400, {"error": str(e)})
        if path == "/api/admin/login":
            if not CONFIG:
                return self._send(404, {"error": "edição do config.env desligada"})
            tok = ADMIN.login(body.get("password", ""))
            if not tok:
                log("config: senha de administrador errada de", self.client_address[0])
                return self._send(403, {"error": "senha incorreta (aguarde 2 s para tentar de novo)"})
            log("config: login de administrador de", self.client_address[0])
            return self._send(200, {"token": tok, "ttl": Admin.TTL})
        if path == "/api/admin/logout":
            ADMIN.logout(self.headers.get("X-Admin-Token", ""))
            return self._send(200, {"ok": True})
        if not self._admin():
            return None
        try:
            with CONFIG_LOCK:
                text, h, new, plan = settings_plan(body)
                if path == "/api/settings/preview":
                    return self._send(200, plan)
                if not plan["changed"]:
                    return self._send(400, {"error": "nada mudou", **plan})
                if plan["validation"]["ok"] is False:
                    return self._send(422, {"error": "a validação do install recusou o arquivo novo", **plan})
                backup = CONFIG.write(new, body.get("hash", ""))
            log("config: %s gravado por %s: %s (backup %s)" % (
                CONFIG_PATH, self.client_address[0], ", ".join(plan["changed"]), backup))
            return self._send(200, {"ok": True, "backup": backup, **plan})
        except configedit.ConfigError as e:
            return self._send(409 if "mudou" in str(e) or "substituído" in str(e) else 400, {"error": str(e)})
        except OSError as e:
            return self._send(500, {"error": "não foi possível gravar o config.env: %s" % e})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/api/admin/login", "/api/admin/logout", "/api/settings/preview", "/api/settings/save"):
            return self._settings_post(u.path)
        if u.path not in ("/api/ingest/gnb-log", "/api/ingest/host"):
            return self._send(404, {"error": "não encontrado"})
        if not INGEST_TOKEN:
            return self._send(403, {"error": "ingestão desligada (INGEST_TOKEN vazio)"})
        tok = self.headers.get("X-Ingest-Token", "")
        if not hmac.compare_digest(tok, INGEST_TOKEN):
            return self._send(403, {"error": "token inválido"})
        n = int(self.headers.get("Content-Length", "0") or 0)
        if n > 8 * 1024 * 1024:
            return self._send(413, {"error": "lote grande demais"})
        body = self.rfile.read(n).decode("utf-8", "replace")
        if u.path == "/api/ingest/host":
            try:
                d = json.loads(body)
                name = str(d["name"])[:64]
            except (ValueError, KeyError, TypeError):
                return self._send(400, {"error": "JSON inválido"})
            HOSTS_STATE.push(name, str(d.get("role") or "")[:80], "agente", d.get("sample"), d.get("error"))
            return self._send(200, {"ok": True})
        lines = [ANSI.sub("", l) for l in body.splitlines() if l.strip()]
        if self.headers.get("X-Ident-Only") == "1":
            GNBLOG.ident_only(lines)
            return self._send(200, {"ok": True, "lines": len(lines)})
        GNBLOG.push(lines, self.headers.get("X-Source", self.client_address[0]))
        return self._send(200, {"ok": True, "lines": len(lines), "ident": len(GNBLOG.rnti_cu)})

    def _static(self, name):
        p = os.path.join(STATIC_DIR, name)
        if name not in STATIC_FILES or not os.path.isfile(p):
            return self._send(404, {"error": "não encontrado"})
        with open(p, "rb") as f:
            data = f.read()
        ext = os.path.splitext(name)[1]
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _overview(self):
        ran = GNB.snapshot(60)
        core = CORE.snapshot()
        cell_last = ran["cells"][0]["last"] if ran["cells"] else {}
        pods = core["pods"]
        return {
            "now": time.time(),
            "gnb": {"status": ran["status"], "cell": cell_last,
                    "ues": [dict({k: u[k] for k in ("id", "pci", "rnti", "active", "last", "first_seen", "last_seen")},
                                 ident=ue_identity(u["rnti"])) for u in ran["ues"]]},
            "core": {"pods_total": len(pods), "pods_ready": sum(1 for p in pods if p["all_ready"]),
                     "restarts": sum(p["restarts"] for p in pods), "pods_error": core["pods_error"],
                     "nof_gnbs": core["nof_gnbs"], "gnbs": core["gnbs"],
                     "ues": core["ues"], "sessions": core["sessions"], "counters": core["counters"],
                     "events": core["events"][:60]},
            "pods": pods,
            "gnb_log": {"enabled": bool(INGEST_TOKEN), "last_push": GNBLOG.last_push, "source": GNBLOG.source},
        }

    def _ran_csv(self, window):
        snap = GNB.snapshot(window)
        out = io.StringIO()
        w = csv.writer(out)
        fields = ("dl_brate", "ul_brate", "dl_mcs", "ul_mcs", "cqi", "dl_ri", "ul_ri", "dl_bler", "ul_bler",
                  "pusch_snr_db", "pusch_rsrp_db", "ta_ns", "bsr", "last_phr")
        w.writerow(("timestamp_utc", "pci", "rnti") + fields)
        for u in snap["ues"]:
            s = u["series"]
            for i, t in enumerate(s["t"]):
                w.writerow((time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % int((t % 1) * 1000),
                            u["pci"], u["rnti"]) + tuple(s.get(f, [None] * len(s["t"]))[i] for f in fields))
        name = "ran-%s.csv" % time.strftime("%Y%m%d-%H%M%S")
        return self._send(200, out.getvalue(), "text/csv; charset=utf-8",
                          {"Content-Disposition": 'attachment; filename="%s"' % name})

    def _pod_container(self, qs):
        pod = _q(qs, "pod", "")
        container = _q(qs, "container", "")
        if not re.match(r"^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$", pod or ""):
            raise ValueError("pod inválido")
        if container and not re.match(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", container):
            raise ValueError("container inválido")
        return pod, container

    def _logs(self, qs):
        try:
            pod, container = self._pod_container(qs)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        params = {"timestamps": "true", "tailLines": str(min(_q(qs, "tail", 500, int), 20000)),
                  "container": container, "previous": "true" if _q(qs, "previous") == "1" else ""}
        text = K8S.get_text("/api/v1/namespaces/%s/pods/%s/log" % (NAMESPACE, pod), params, timeout=30)
        return self._send(200, {"lines": [ANSI.sub("", l) for l in text.splitlines()]})

    def _logs_stream(self, qs):
        try:
            pod, container = self._pod_container(qs)
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        params = {"timestamps": "true", "follow": "true", "container": container,
                  "tailLines": str(min(_q(qs, "tail", 300, int), 5000))}
        resp = K8S.open("/api/v1/namespaces/%s/pods/%s/log" % (NAMESPACE, pod), params, timeout=None)
        self._sse_start()
        try:
            self._sse("conectado", "status")
            for raw in resp:
                self._sse(ANSI.sub("", raw.decode("utf-8", "replace").rstrip("\n")))
            self._sse("o log terminou (pod reiniciou ou foi removido)", "status")
        finally:
            resp.close()

    def _gnblog_stream(self, qs):
        self._sse_start()
        seq = 0
        for s, l in GNBLOG.tail(min(_q(qs, "tail", 300, int), 5000)):
            self._sse(l)
            seq = s
        while True:
            new = GNBLOG.after(seq, 15)
            if not new:
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
                continue
            for s, l in new:
                self._sse(l)
                seq = s


def main():
    log("painel: namespace=%s gNB=%s métricas do core=%s porta=%s" % (
        NAMESPACE, GNB_METRICS_URL or "(desligado)", CORE_METRICS, PORT))
    if GNB_METRICS_URL:
        GNB.start()
    CORE.start()
    if ENERGY:
        if ENERGY_METER_HOST and ENERGY_METER_HOST not in HOSTS_STATE.h:
            HOSTS_STATE._entry(ENERGY_METER_HOST, "", "medidor")
        ENERGY.start()
    if COREPROCS:
        threading.Thread(target=COREPROCS.run, daemon=True, name="coreprocs").start()
    if HOST_ROOT:
        threading.Thread(target=local_host_loop, args=(HOSTS_STATE,), daemon=True, name="host").start()
    srv = ThreadingHTTPServer((BIND, PORT), Handler)
    srv.daemon_threads = True
    srv.serve_forever()


if __name__ == "__main__":
    main()
