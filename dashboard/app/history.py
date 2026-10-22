# =============================================================================
#  dashboard/app/history.py — histórico persistente das métricas (DASHBOARD_PERSIST).
#
#  SQLite (biblioteca padrão) num diretório do host. Cada série (célula, UE, máquina,
#  CPU dos NFs, tráfego do UPF...) é guardada em blocos de ~60 s, com resolução cheia
#  (1 s no rádio), comprimidos com zlib: ~1 KB/s com 2–3 UEs.
#  Tabelas:
#    chunks(series, t0, t1, n, meta, data)   amostras {"t": [...], campo: [...]}
#    events(ts, src, level, msg)             eventos do core (registro, sessão, erros)
#    experiments(id, name, notes, t_start, t_end, config, setup)
#  Retenção por dias e por tamanho máximo do arquivo (apaga os blocos mais antigos).
# =============================================================================
import json
import math
import os
import sqlite3
import threading
import time
import zlib

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (series TEXT NOT NULL, t0 REAL NOT NULL, t1 REAL NOT NULL, n INTEGER NOT NULL,
                                   meta TEXT, data BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_t ON chunks (t0, t1);
CREATE INDEX IF NOT EXISTS chunks_s ON chunks (series, t0);
CREATE TABLE IF NOT EXISTS events (ts TEXT NOT NULL, t REAL NOT NULL, src TEXT, level TEXT, msg TEXT,
                                   UNIQUE (ts, src, msg));
CREATE INDEX IF NOT EXISTS events_t ON events (t);
CREATE TABLE IF NOT EXISTS experiments (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, notes TEXT,
                                        t_start REAL NOT NULL, t_end REAL, config TEXT, setup TEXT);
"""


def _iso_to_epoch(ts):
    try:
        from datetime import datetime
        return datetime.fromisoformat(ts.replace("Z", "+00:00")[:26] + ("+00:00" if ts.endswith("Z") else "")).timestamp()
    except (ValueError, AttributeError):
        return time.time()


def _pct(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p / 100.0
    f, c = math.floor(k), math.ceil(k)
    return sorted_vals[f] if f == c else sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


class History:
    def __init__(self, path, retention_days=180, max_mb=20000, chunk_seconds=60, meta_fn=None, log=print):
        self.path = path
        self.retention = retention_days * 86400 if retention_days > 0 else 0
        self.max_bytes = max_mb * 1024 * 1024 if max_mb > 0 else 0
        self.chunk_seconds = chunk_seconds
        self.meta_fn = meta_fn
        self.log = log
        self.lock = threading.Lock()      # buffers
        self.dblock = threading.Lock()    # conexão
        self.buf = {}
        self.error = None
        self.written = 0
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        new = not os.path.exists(path)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        if new:
            self.db.execute("PRAGMA auto_vacuum = INCREMENTAL")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA synchronous = NORMAL")
        self.db.executescript(SCHEMA)
        self.db.commit()
        # Experimento que ficou aberto quando o painel caiu continua aberto (é só um intervalo de tempo)

    # ------------------------------------------------------------------ gravação
    def add(self, series, t, values):
        vals = {k: v for k, v in values.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
                and math.isfinite(v)}
        if not vals:
            return
        with self.lock:
            self.buf.setdefault(series, []).append((t, vals))

    def event(self, ts, src, level, msg):
        try:
            with self.dblock:
                self.db.execute("INSERT OR IGNORE INTO events (ts, t, src, level, msg) VALUES (?,?,?,?,?)",
                                (ts, _iso_to_epoch(ts), src, level, msg[:500]))
        except sqlite3.Error as e:
            self.error = str(e)

    @staticmethod
    def _encode(rows):
        keys = []
        for _, v in rows:
            for k in v:
                if k not in keys:
                    keys.append(k)
        d = {"t": [round(t, 3) for t, _ in rows]}
        for k in keys:
            d[k] = [v.get(k) for _, v in rows]
        return zlib.compress(json.dumps(d, separators=(",", ":")).encode(), 6)

    def flush(self):
        with self.lock:
            buf, self.buf = self.buf, {}
        if not buf:
            return
        rows = []
        for series, samples in buf.items():
            meta = None
            if self.meta_fn:
                try:
                    meta = self.meta_fn(series)
                except Exception:  # noqa: BLE001
                    meta = None
            rows.append((series, samples[0][0], samples[-1][0], len(samples),
                         json.dumps(meta) if meta else None, self._encode(samples)))
        with self.dblock:
            self.db.executemany("INSERT INTO chunks (series, t0, t1, n, meta, data) VALUES (?,?,?,?,?,?)", rows)
            self.db.commit()
        self.written += len(rows)

    def size(self):
        try:
            return sum(os.path.getsize(self.path + s) for s in ("", "-wal") if os.path.exists(self.path + s))
        except OSError:
            return 0

    def cleanup(self):
        with self.dblock:
            if self.retention:
                self.db.execute("DELETE FROM chunks WHERE t1 < ?", (time.time() - self.retention,))
                self.db.execute("DELETE FROM events WHERE t < ?", (time.time() - self.retention,))
            self.db.commit()
            # Teto de tamanho: apaga os blocos mais antigos (10% de cada vez) até caber
            for _ in range(20):
                if not self.max_bytes or self.size() <= self.max_bytes:
                    break
                n = self.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
                if not n:
                    break
                self.db.execute("DELETE FROM chunks WHERE rowid IN (SELECT rowid FROM chunks ORDER BY t0 LIMIT ?)",
                                (max(1, n // 10),))
                self.db.commit()
                self.db.execute("PRAGMA incremental_vacuum")
                self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.db.execute("PRAGMA incremental_vacuum(1000)")
            self.db.commit()

    def run(self):
        last_clean = 0
        while True:
            time.sleep(self.chunk_seconds)
            try:
                self.flush()
                if time.time() - last_clean > 3600:
                    self.cleanup()
                    last_clean = time.time()
                self.error = None
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
                self.log("histórico: erro ao gravar:", e)

    # ------------------------------------------------------------------ leitura
    def _load(self, t0, t1, series=None, prefix=None):
        """{série: {"meta": ..., "rows": [(t, {campo: v})]}} do período, incluindo o que ainda está no buffer."""
        q = "SELECT series, meta, data FROM chunks WHERE t1 >= ? AND t0 <= ?"
        args = [t0, t1]
        if series:
            q += " AND series IN (%s)" % ",".join("?" * len(series))
            args += list(series)
        elif prefix:
            q += " AND (" + " OR ".join("series LIKE ?" for _ in prefix) + ")"
            args += [p + "%" for p in prefix]
        q += " ORDER BY t0"
        out = {}
        with self.dblock:
            res = self.db.execute(q, args).fetchall()
        for s, meta, data in res:
            d = json.loads(zlib.decompress(data))
            e = out.setdefault(s, {"meta": None, "rows": []})
            if meta:
                e["meta"] = json.loads(meta)
            keys = [k for k in d if k != "t"]
            for i, t in enumerate(d["t"]):
                if t0 <= t <= t1:
                    e["rows"].append((t, {k: d[k][i] for k in keys if d[k][i] is not None}))
        with self.lock:
            pending = {s: list(v) for s, v in self.buf.items()}
        for s, rows in pending.items():
            if (series and s not in series) or (prefix and not s.startswith(tuple(prefix))):
                continue
            e = out.setdefault(s, {"meta": None, "rows": []})
            if e["meta"] is None and self.meta_fn:
                try:
                    e["meta"] = self.meta_fn(s)
                except Exception:  # noqa: BLE001
                    pass
            e["rows"] += [(t, v) for t, v in rows if t0 <= t <= t1]
        return out

    def series_list(self, t0, t1):
        with self.dblock:
            res = self.db.execute("SELECT series, MIN(t0), MAX(t1), SUM(n), MAX(meta) FROM chunks "
                                  "WHERE t1 >= ? AND t0 <= ? GROUP BY series ORDER BY series", (t0, t1)).fetchall()
        return [{"series": s, "t0": a, "t1": b, "n": n, "meta": json.loads(m) if m else None} for s, a, b, n, m in res]

    def data(self, t0, t1, series=None, prefix=None, points=1200, rel=False):
        """Séries reamostradas em até `points` baldes: média e máximo de cada campo."""
        raw = self._load(t0, t1, series, prefix)
        span = max(t1 - t0, 1.0)
        step = max(1.0, span / points)
        out = {}
        for s, e in raw.items():
            if not e["rows"]:
                continue
            buckets = {}
            for t, v in e["rows"]:
                b = int((t - t0) // step)
                acc = buckets.setdefault(b, {})
                for k, x in v.items():
                    a = acc.get(k)
                    if a is None:
                        acc[k] = [x, 1, x]
                    else:
                        a[0] += x
                        a[1] += 1
                        if x > a[2]:
                            a[2] = x
            keys = sorted({k for acc in buckets.values() for k in acc})
            bs = sorted(buckets)
            d = {"t": [round((b * step) if rel else (t0 + b * step + step / 2), 3) for b in bs]}
            for k in keys:
                d[k] = [round(buckets[b][k][0] / buckets[b][k][1], 4) if k in buckets[b] else None for b in bs]
                d[k + "__max"] = [round(buckets[b][k][2], 4) if k in buckets[b] else None for b in bs]
            out[s] = {"meta": e["meta"], "data": d}
        return {"t0": t0, "t1": t1, "step": step, "series": out}

    def events(self, t0, t1, limit=500):
        with self.dblock:
            res = self.db.execute("SELECT t, src, level, msg FROM events WHERE t >= ? AND t <= ? ORDER BY t DESC LIMIT ?",
                                  (t0, t1, limit)).fetchall()
            cnt = self.db.execute("SELECT src, level, COUNT(*) FROM events WHERE t >= ? AND t <= ? GROUP BY src, level",
                                  (t0, t1)).fetchall()
        return {"events": [{"t": t, "src": s, "level": l, "msg": m} for t, s, l, m in res],
                "counts": [{"src": s, "level": l, "n": n} for s, l, n in cnt]}

    def summary(self, t0, t1):
        """KPIs do período para comparar setups (calculados com a resolução cheia)."""
        raw = self._load(t0, t1)

        def stats(vals, scale=1.0):
            v = sorted(x * scale for x in vals if x is not None)
            if not v:
                return None
            return {"avg": sum(v) / len(v), "p50": _pct(v, 50), "p95": _pct(v, 95), "max": v[-1], "min": v[0],
                    "n": len(v)}

        out = {"t0": t0, "t1": t1, "duration": t1 - t0, "cell": {}, "ues": [], "hosts": {}, "nfs": {}, "upf": {}}
        for s, e in raw.items():
            rows = e["rows"]
            col = lambda k: [v.get(k) for _, v in rows]  # noqa: E731
            if s.startswith("cell:"):
                out["cell"] = {k: stats(col(k), sc) for k, sc in
                               (("dl_brate", 1e-6), ("ul_brate", 1e-6), ("pdsch_prbs", 1), ("pusch_prbs", 1),
                                ("nof_ues", 1), ("avg_latency", 1), ("late_dl_harqs", 1), ("late_ul_harqs", 1))}
            elif s.startswith("ue:"):
                ok = lambda k: sum(x or 0 for x in col(k))  # noqa: E731
                dl_tb, ul_tb = ok("dl_nof_ok") + ok("dl_nof_nok"), ok("ul_nof_ok") + ok("ul_nof_nok")
                m = e["meta"] or {}
                out["ues"].append({
                    "series": s, "imsi": m.get("imsi"), "name": m.get("name"), "kind": m.get("kind"),
                    "seconds": len(rows),
                    "dl_brate": stats(col("dl_brate"), 1e-6), "ul_brate": stats(col("ul_brate"), 1e-6),
                    "dl_mcs": stats(col("dl_mcs")), "ul_mcs": stats(col("ul_mcs")), "cqi": stats(col("cqi")),
                    "dl_ri": stats(col("dl_ri")), "pusch_snr_db": stats(col("pusch_snr_db")),
                    "pusch_rsrp_db": stats(col("pusch_rsrp_db")),
                    "dl_bler": 100.0 * ok("dl_nof_nok") / dl_tb if dl_tb else None,
                    "ul_bler": 100.0 * ok("ul_nof_nok") / ul_tb if ul_tb else None,
                    "dl_tbs": dl_tb, "ul_tbs": ul_tb,
                })
            elif s.startswith("host:"):
                out["hosts"][s[5:]] = {k: stats(col(k)) for k in ("cpu", "mem", "temp", "load1")}
            elif s == "core:cpu":
                keys = {k for _, v in rows for k in v}
                out["nfs"] = {k: stats(col(k)) for k in sorted(keys)}
            elif s == "core:upf":
                keys = {k for _, v in rows for k in v}
                out["upf"] = {k: stats(col(k), 1e-6) for k in sorted(keys)}
            elif s == "ru":
                out["ru"] = {k: stats(col(k)) for k in ("power", "temp", "temp_cpu", "late_pct", "rx_total")}
                for k in ("sync", "rf", "du"):
                    st = stats(col("ok_" + k), 100.0)
                    out["ru"]["ok_" + k] = st["avg"] if st else None
            elif s == "energy":
                out["energy"] = {k: stats(col(k)) for k in ("power", "voltage", "current")}
        # UEs: junta as séries do mesmo IMSI (o RNTI muda a cada conexão)
        merged = {}
        for u in out["ues"]:
            merged.setdefault(u["imsi"] or u["series"], []).append(u)
        out["ue_by_imsi"] = {k: [x["series"] for x in v] for k, v in merged.items()}
        ev = self.events(t0, t1, 0)
        out["events"] = ev["counts"]
        return out

    # ------------------------------------------------------------------ experimentos
    def experiments(self):
        with self.dblock:
            res = self.db.execute("SELECT id, name, notes, t_start, t_end, setup FROM experiments ORDER BY t_start DESC").fetchall()
        return [{"id": i, "name": n, "notes": no, "t_start": a, "t_end": b, "setup": json.loads(s) if s else None}
                for i, n, no, a, b, s in res]

    def experiment(self, eid):
        with self.dblock:
            r = self.db.execute("SELECT id, name, notes, t_start, t_end, config, setup FROM experiments WHERE id = ?",
                                (eid,)).fetchone()
        if not r:
            return None
        return {"id": r[0], "name": r[1], "notes": r[2], "t_start": r[3], "t_end": r[4], "config": r[5],
                "setup": json.loads(r[6]) if r[6] else None}

    def running(self):
        with self.dblock:
            r = self.db.execute("SELECT id, name, t_start FROM experiments WHERE t_end IS NULL ORDER BY t_start DESC LIMIT 1").fetchone()
        return {"id": r[0], "name": r[1], "t_start": r[2]} if r else None

    def start(self, name, notes, config, setup):
        now = time.time()
        with self.dblock:
            self.db.execute("UPDATE experiments SET t_end = ? WHERE t_end IS NULL", (now,))
            cur = self.db.execute("INSERT INTO experiments (name, notes, t_start, config, setup) VALUES (?,?,?,?,?)",
                                  (name, notes, now, config, json.dumps(setup)))
            self.db.commit()
            return cur.lastrowid

    def stop(self):
        with self.dblock:
            self.db.execute("UPDATE experiments SET t_end = ? WHERE t_end IS NULL", (time.time(),))
            self.db.commit()

    def update(self, eid, name, notes):
        with self.dblock:
            self.db.execute("UPDATE experiments SET name = ?, notes = ? WHERE id = ?", (name, notes, eid))
            self.db.commit()

    def delete(self, eid):
        with self.dblock:
            self.db.execute("DELETE FROM experiments WHERE id = ?", (eid,))
            self.db.commit()

    def status(self):
        with self.dblock:
            a = self.db.execute("SELECT MIN(t0), MAX(t1), COUNT(*) FROM chunks").fetchone()
            ne = self.db.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]
        return {"enabled": True, "path": self.path, "size": self.size(), "oldest": a[0], "newest": a[1],
                "chunks": a[2], "experiments": ne, "retention_days": self.retention / 86400 if self.retention else 0,
                "max_bytes": self.max_bytes, "error": self.error, "running": self.running()}
