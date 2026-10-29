/* Innova Center Dashboard — aba Histórico (métricas persistentes, experimentos e comparação).
   Usa as utilidades de app.js ($, esc, fmt, fmtRate, api, store, Charts, colorFor). */
"use strict";

const fmtDateTime = (t) => (t ? new Date(t * 1000).toLocaleString("pt-BR", { hour12: false }) : "–");
function fmtDur(s) {
  if (s == null) return "–";
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
  return h ? `${h} h ${String(m).padStart(2, "0")} min` : m ? `${m} min ${String(x).padStart(2, "0")} s` : `${x} s`;
}
const relFmt = (v) => { const s = Math.round(v); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
function timeFmt(span) {
  return span > 86400
    ? (v) => new Date(v * 1000).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false })
    : span > 3600 ? (v) => new Date(v * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", hour12: false })
      : (v) => new Date(v * 1000).toLocaleTimeString("pt-BR", { hour12: false });
}
async function postJSON(path, body, headers = {}) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: JSON.stringify(body) });
  let d = {};
  try { d = await r.json(); } catch { /* sem corpo */ }
  if (!r.ok) throw new Error(d.error || r.status + " " + r.statusText);
  return d;
}

// Junta várias séries (ex.: o mesmo IMSI com RNTIs diferentes) e alinha num eixo X comum
function lines(groups, field, scale = 1) {
  const xs = new Set();
  const maps = groups.map((g) => {
    const m = new Map();
    for (const d of g.data) {
      const v = d[field] || [];
      d.t.forEach((t, i) => { if (v[i] != null) { m.set(t, v[i] * scale); xs.add(t); } });
    }
    return m;
  });
  const x = [...xs].sort((a, b) => a - b);
  return [x, ...maps.map((m) => x.map((t) => (m.has(t) ? m.get(t) : null)))];
}
function ueLabel(meta, series) {
  if (meta && meta.name) return meta.name;
  if (meta && meta.imsi) return "IMSI …" + meta.imsi.slice(-4);
  return "RNTI " + series.split(":").pop();
}
function groupUes(seriesMap) {
  const g = new Map();
  for (const [s, e] of Object.entries(seriesMap)) {
    if (!s.startsWith("ue:")) continue;
    const key = (e.meta && e.meta.imsi) || s;
    if (!g.has(key)) g.set(key, { label: ueLabel(e.meta, s), meta: e.meta, data: [] });
    g.get(key).data.push(e.data);
  }
  return [...g.values()].sort((a, b) => a.label.localeCompare(b.label));
}

const Hist = {
  status: null,
  exps: [],
  running: null,
  sel: new Set(),
  loaded: false,

  async refreshHeader() {
    if (!CONFIG.persist) return;
    try {
      const d = await api("api/history/experiments");
      this.exps = d.experiments;
      this.running = d.running;
    } catch { return; }
    const b = $("#rec");
    if (this.running) {
      b.className = "rec on";
      b.innerHTML = `■ Encerrar <b>${esc(this.running.name)}</b> <span>${fmtDur(Date.now() / 1000 - this.running.t_start)}</span>`;
      b.title = "Experimento gravando — clique para encerrar";
    } else {
      b.className = "rec";
      b.innerHTML = "● Gravar experimento";
      b.title = "Marca um período com nome e notas para comparar depois (aba Histórico)";
    }
  },

  async refresh() {
    await this.refreshHeader();
    if (!CONFIG.persist) {
      $("#hist-off").classList.remove("hidden");
      $("#hist-on").classList.add("hidden");
      return;
    }
    $("#hist-off").classList.add("hidden");
    $("#hist-on").classList.remove("hidden");
    const st = await api("api/history/status");
    this.status = st;
    $("#hist-status").innerHTML = `Gravando tudo em <code>${esc(st.path)}</code> · ${fmtBytes(st.size)}` +
      ` · desde ${fmtDateTime(st.oldest)} · retenção ${st.retention_days ? st.retention_days + " dias" : "sem limite"}` +
      (st.max_bytes ? ` · máx. ${fmtBytes(st.max_bytes)}` : "") + (st.error ? ` · <span class="tag err">${esc(st.error)}</span>` : "");
    this.renderExps();
    if (!this.loaded) { this.loaded = true; this.view(); }
  },

  renderExps() {
    // Recriar a tabela a cada 2 s perdia cliques nas caixas e botões: só recria quando algo muda;
    // senão atualiza só a duração do experimento que está gravando.
    const key = JSON.stringify([this.exps.map((e) => [e.id, e.name, e.notes, e.t_end, e.setup && e.setup.ues]), [...this.sel]]);
    if (key === this._expsKey) {
      for (const e of this.exps) {
        if (e.t_end) continue;
        const c = $(`#hist-exps [data-dur="${e.id}"]`);
        if (c) c.textContent = fmtDur(Date.now() / 1000 - e.t_start);
      }
      return;
    }
    this._expsKey = key;
    const rows = this.exps.map((e) => {
      const dur = (e.t_end || Date.now() / 1000) - e.t_start;
      const ues = ((e.setup && e.setup.ues) || []).map((u) => u.name || (u.imsi ? "…" + u.imsi.slice(-4) : "RNTI " + u.rnti)).join(", ");
      return `<tr class="${this.sel.has(e.id) ? "selrow" : ""}">
        <td><input type="checkbox" data-sel="${e.id}" ${this.sel.has(e.id) ? "checked" : ""}></td>
        <td><b>${esc(e.name)}</b>${e.t_end ? "" : ' <span class="tag warn">gravando</span>'}${ues ? `<br><span class="muted">UEs: ${esc(ues)}</span>` : ""}</td>
        <td>${fmtDateTime(e.t_start)}</td><td class="num" data-dur="${e.id}">${fmtDur(dur)}</td>
        <td class="notes">${esc(e.notes || "")}</td>
        <td class="actions"><button class="btn small" data-view="${e.id}">Ver</button>
          <button class="btn small" data-edit="${e.id}">Editar</button>
          <button class="btn small" data-cfg="${e.id}">Config</button>
          <button class="btn small" data-del="${e.id}">Apagar</button></td></tr>`;
    }).join("");
    $("#hist-exps").innerHTML = `<tr><th></th><th>Experimento</th><th>Início</th><th class="num">Duração</th><th>Notas</th><th></th></tr>` +
      (rows || `<tr><td colspan="6" class="empty">Nenhum experimento ainda. Use <b>● Gravar experimento</b> no topo da página.</td></tr>`);
    const n = this.sel.size;
    $("#hist-compare-btn").disabled = n < 2;
    $("#hist-compare-btn").textContent = n >= 2 ? `Comparar ${n} selecionados` : "Comparar (selecione 2 ou mais)";
  },

  period() {
    const p = $("#hist-preset").value;
    const now = Date.now() / 1000;
    if (p === "custom") {
      const a = Date.parse($("#hist-from").value) / 1000, b = Date.parse($("#hist-to").value) / 1000;
      return { t0: a || now - 3600, t1: b || now, title: "Período escolhido" };
    }
    if (p.startsWith("exp:")) {
      const e = this.exps.find((x) => x.id === +p.slice(4));
      if (e) return { t0: e.t_start, t1: e.t_end || now, title: "Experimento: " + e.name, exp: e };
    }
    return { t0: now - +p, t1: now, title: "Últimos " + $("#hist-preset").selectedOptions[0].textContent.toLowerCase() };
  },

  presets() {
    const sel = $("#hist-preset");
    const cur = sel.value;
    const fixed = [["3600", "1 hora"], ["21600", "6 horas"], ["86400", "24 horas"], ["604800", "7 dias"], ["2592000", "30 dias"]];
    sel.innerHTML = fixed.map(([v, l]) => `<option value="${v}">${l}</option>`).join("") +
      (this.exps.length ? `<optgroup label="Experimentos">${this.exps.map((e) => `<option value="exp:${e.id}">${esc(e.name)}</option>`).join("")}</optgroup>` : "") +
      `<option value="custom">Personalizado…</option>`;
    if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
    $("#hist-custom").classList.toggle("hidden", sel.value !== "custom");
  },

  // ---- visualizar um período
  async view() {
    this.presets();
    const p = this.period();
    $("#hist-compare").classList.add("hidden");
    $("#hist-view").classList.remove("hidden");
    $("#hist-view-title").textContent = `${p.title} · ${fmtDateTime(p.t0)} → ${fmtDateTime(p.t1)} (${fmtDur(p.t1 - p.t0)})`;
    $("#hist-csv").href = `api/history/csv?from=${p.t0}&to=${p.t1}`;
    const q = `from=${p.t0}&to=${p.t1}`;
    const seq = (this._vseq = (this._vseq || 0) + 1);
    $("#hist-view").classList.add("loading");
    let d, sm;
    try {
      [d, sm] = await Promise.all([api(`api/history/data?${q}&points=1200`), api(`api/history/summary?${q}`)]);
    } finally {
      if (seq === this._vseq) $("#hist-view").classList.remove("loading");
    }
    if (seq !== this._vseq) return;   // o usuário já pediu outro período
    this.kpis(sm, "#hist-kpis");
    this.ueTable(sm);
    this.charts(d, p.t1 - p.t0);
    // todos os gráficos mostram o período inteiro (um UE que apareceu só 1 min não "estica" o eixo)
    for (const id of ["hc-cell", "hc-prb", "hc-ue-dl", "hc-ue-bler", "hc-ue-mcs", "hc-ue-cqi", "hc-ue-snr", "hc-hosts", "hc-nf", "hc-upf"]) {
      const u = Charts.list[id];
      if (u) u.setScale("x", { min: p.t0, max: p.t1 });
    }
    $("#hist-events").innerHTML = (sm.events || []).length
      ? sm.events.map((e) => `<span class="tag ${e.level === "error" ? "err" : e.level === "warning" ? "warn" : ""}">${esc(e.src.toUpperCase())} ${esc(e.level)}: ${e.n}</span>`).join(" ")
      : '<span class="muted">nenhum evento do core no período</span>';
  },

  kpis(sm, el) {
    const c = sm.cell || {};
    const h = (sm.hosts || {});
    const gnbHost = Object.keys(h).find((n) => n !== (CONFIG.local_host || "")) || Object.keys(h)[0];
    const tot = (sm.ues || []).reduce((a, u) => [a[0] + (u.dl_tbs || 0), a[1] + (u.dl_bler != null ? u.dl_bler * (u.dl_tbs || 0) / 100 : 0)], [0, 0]);
    const k = [
      { l: "DL da célula (média / p95 / pico)", v: c.dl_brate ? `${fmt(c.dl_brate.avg)} / ${fmt(c.dl_brate.p95)} / ${fmt(c.dl_brate.max)}` : "–", s: "Mbit/s" },
      { l: "UL da célula (média / p95 / pico)", v: c.ul_brate ? `${fmt(c.ul_brate.avg)} / ${fmt(c.ul_brate.p95)} / ${fmt(c.ul_brate.max)}` : "–", s: "Mbit/s" },
      { l: "BLER DL (todos os UEs)", v: tot[0] ? fmt(100 * tot[1] / tot[0], 2) + "%" : "–", s: `${tot[0]} blocos` },
      { l: "UEs na célula (máx.)", v: c.nof_ues ? fmt(c.nof_ues.max, 0) : "–", s: `${new Set((sm.ues || []).map((u) => u.imsi || u.series)).size} distintos` },
      { l: "PRBs DL (média / pico)", v: c.pdsch_prbs ? `${fmt(c.pdsch_prbs.avg, 0)} / ${fmt(c.pdsch_prbs.max, 0)}` : "–", s: "soma por slot TDD" },
      ...Object.entries(h).map(([n, x]) => ({ l: `${n}: CPU / temp. máx.`, v: `${x.cpu ? fmt(x.cpu.avg, 0) + "%" : "–"} / ${x.temp ? fmt(x.temp.max, 0) + " °C" : "–"}`, s: "média de CPU · pico de temperatura" })),
    ];
    $(el).innerHTML = k.map((x) => `<div class="kpi"><div class="label">${esc(x.l)}</div><div class="value small">${esc(x.v)}</div><div class="sub">${esc(x.s)}</div></div>`).join("");
  },

  ueTable(sm) {
    // agrupa por IMSI
    const g = new Map();
    for (const u of sm.ues || []) {
      const k = u.imsi || u.series;
      if (!g.has(k)) g.set(k, []);
      g.get(k).push(u);
    }
    const rows = [...g.entries()].map(([k, us]) => {
      const w = (f, s) => { // média ponderada pelo tempo
        let a = 0, n = 0, mx = null;
        for (const u of us) if (u[f]) { a += u[f].avg * u[f].n; n += u[f].n; mx = Math.max(mx ?? -1e9, u[f][s || "max"]); }
        return n ? { avg: a / n, max: mx } : null;
      };
      const dl = w("dl_brate"), ul = w("ul_brate"), mcs = w("dl_mcs"), cqi = w("cqi"), snr = w("pusch_snr_db");
      const tb = us.reduce((a, u) => a + (u.dl_tbs || 0), 0);
      const nok = us.reduce((a, u) => a + (u.dl_bler != null ? u.dl_bler * (u.dl_tbs || 0) / 100 : 0), 0);
      const utb = us.reduce((a, u) => a + (u.ul_tbs || 0), 0);
      const unok = us.reduce((a, u) => a + (u.ul_bler != null ? u.ul_bler * (u.ul_tbs || 0) / 100 : 0), 0);
      const u0 = us[0];
      return `<tr><td><b>${esc(u0.name || (u0.imsi ? "IMSI " + u0.imsi : "não identificado"))}</b>${u0.name && u0.imsi ? `<br><span class="muted">${esc(u0.imsi)}</span>` : ""}</td>
        <td class="num">${fmtDur(us.reduce((a, u) => a + u.seconds, 0))}</td>
        <td class="num">${dl ? fmt(dl.avg) + " / " + fmt(dl.max) : "–"}</td><td class="num">${ul ? fmt(ul.avg) + " / " + fmt(ul.max) : "–"}</td>
        <td class="num">${mcs ? fmt(mcs.avg) : "–"}</td><td class="num">${cqi ? fmt(cqi.avg) : "–"}</td>
        <td class="num">${tb ? fmt(100 * nok / tb, 2) + "%" : "–"} / ${utb ? fmt(100 * unok / utb, 2) + "%" : "–"}</td>
        <td class="num">${snr ? fmt(snr.avg) + " dB" : "–"}</td></tr>`;
    }).join("");
    $("#hist-ues").innerHTML = `<tr><th>UE</th><th class="num">Tempo no rádio</th><th class="num">DL Mbit/s (média / pico)</th>
      <th class="num">UL Mbit/s (média / pico)</th><th class="num">MCS DL</th><th class="num">CQI</th><th class="num">BLER DL / UL</th><th class="num">SNR PUSCH</th></tr>` +
      (rows || `<tr><td colspan="8" class="empty">Nenhum UE no rádio neste período.</td></tr>`);
  },

  charts(d, span) {
    const S = d.series;
    const xf = timeFmt(span);
    const o = { xfmt: xf, spanGaps: false };
    const cell = Object.entries(S).find(([k]) => k.startsWith("cell:"));
    const cd = cell ? cell[1].data : { t: [] };
    const M = (v) => (v == null ? null : v / 1e6);
    Charts.make("hc-cell", [{ label: "DL média", fill: true, fmt: (v) => fmt(v, 1) }, { label: "DL pico", dash: [4, 3], fmt: (v) => fmt(v, 1) },
      { label: "UL média", color: "#6b7280", fill: true, fmt: (v) => fmt(v, 1) }], o);
    Charts.set("hc-cell", [cd.t, (cd.dl_brate || []).map(M), (cd.dl_brate__max || []).map(M), (cd.ul_brate || []).map(M)]);
    Charts.make("hc-prb", [{ label: "PDSCH (DL)", dec: 0 }, { label: "PUSCH (UL)", color: "#6b7280", dec: 0 }], o);
    Charts.set("hc-prb", [cd.t, cd.pdsch_prbs || [], cd.pusch_prbs || []]);
    const ues = groupUes(S);
    const ul = ues.map((g, i) => ({ label: g.label, color: colorFor(i) }));
    const mk = (id, f, sc = 1, extra = {}) => { Charts.make(id, ul.length ? ul : [{ label: "sem UEs" }], { ...o, ...extra }); Charts.set(id, ul.length ? lines(ues, f, sc) : [[], []]); };
    mk("hc-ue-dl", "dl_brate", 1e-6);
    mk("hc-ue-bler", "dl_bler", 1, { scales: { y: { range: [0, 100] } } });
    mk("hc-ue-mcs", "dl_mcs");
    mk("hc-ue-cqi", "cqi");
    mk("hc-ue-snr", "pusch_snr_db");
    const hosts = Object.entries(S).filter(([k]) => k.startsWith("host:"));
    const hs = [];
    hosts.forEach(([k], i) => { hs.push({ label: `CPU ${k.slice(5)} %`, color: colorFor(i * 2) }); hs.push({ label: `Temp. ${k.slice(5)} °C`, color: colorFor(i * 2 + 1), dash: [4, 3] }); });
    Charts.make("hc-hosts", hs.length ? hs : [{ label: "sem máquinas" }], o);
    Charts.set("hc-hosts", hs.length ? (() => {
      const xs = [...new Set(hosts.flatMap(([, e]) => e.data.t))].sort((a, b) => a - b);
      const cols = [xs];
      hosts.forEach(([, e]) => ["cpu", "temp"].forEach((f) => { const m = new Map(e.data.t.map((t, i) => [t, (e.data[f] || [])[i]])); cols.push(xs.map((t) => m.get(t) ?? null)); }));
      return cols;
    })() : [[], []]);
    const cpu = (S["core:cpu"] || {}).data || { t: [] };
    const nfs = Object.keys(cpu).filter((k) => k !== "t" && !k.endsWith("__max")).sort();
    Charts.make("hc-nf", nfs.length ? nfs.map((n, i) => ({ label: n.toUpperCase(), color: colorFor(i) })) : [{ label: "sem dados" }], o);
    Charts.set("hc-nf", nfs.length ? [cpu.t, ...nfs.map((n) => cpu[n])] : [[], []]);
    const upf = (S["core:upf"] || {}).data || { t: [] };
    const tuns = Object.keys(upf).filter((k) => /^(ogstun\d*|upfgtp)_tx$/.test(k)).map((k) => k.slice(0, -3)).sort();
    const us = [];
    const uc = [upf.t];
    tuns.forEach((t, i) => {
      us.push({ label: "DL " + t, color: colorFor(i * 2) }, { label: "UL " + t, color: colorFor(i * 2 + 1) });
      uc.push((upf[t + "_tx"] || []).map(M), (upf[t + "_rx"] || []).map(M));
    });
    Charts.make("hc-upf", us.length ? us : [{ label: "sem dados" }], o);
    Charts.set("hc-upf", us.length ? uc : [[], []]);
    if (CONFIG.ru) {
      const ru = (S.ru || {}).data || { t: [] };
      Charts.make("hc-ru", [{ label: "Potência W", fill: true }, { label: "Temp. rádio °C", color: "#6b7280", scale: "y2", dec: 0 }], { ...o, y2: true });
      Charts.set("hc-ru", [ru.t, ru.power || [], ru.temp || []]);
    }
  },

  // ---- comparar experimentos
  async compare() {
    const ids = [...this.sel];
    const exps = ids.map((id) => this.exps.find((e) => e.id === id)).filter(Boolean).sort((a, b) => a.t_start - b.t_start);
    if (exps.length < 2) return;
    $("#hist-view").classList.add("hidden");
    $("#hist-compare").classList.remove("hidden");
    const now = Date.now() / 1000;
    const res = await Promise.all(exps.map(async (e) => {
      const q = `from=${e.t_start}&to=${e.t_end || now}`;
      const [sm, d] = await Promise.all([api("api/history/summary?" + q), api(`api/history/data?${q}&points=600&rel=1&prefix=cell:,host:,ru`)]);
      return { e, sm, d };
    }));
    // tabela de KPIs lado a lado (melhor valor de cada linha em destaque)
    const cellStat = (r, f, s) => r.sm.cell && r.sm.cell[f] ? r.sm.cell[f][s] : null;
    const ueAgg = (r, f) => { let a = 0, n = 0; for (const u of r.sm.ues || []) if (u[f]) { a += u[f].avg * u[f].n; n += u[f].n; } return n ? a / n : null; };
    const bler = (r, dir) => { const tb = (r.sm.ues || []).reduce((a, u) => a + (u[dir + "_tbs"] || 0), 0); const nok = (r.sm.ues || []).reduce((a, u) => a + (u[dir + "_bler"] != null ? u[dir + "_bler"] * (u[dir + "_tbs"] || 0) / 100 : 0), 0); return tb ? 100 * nok / tb : null; };
    const hostNames = [...new Set(res.flatMap((r) => Object.keys(r.sm.hosts || {})))];
    const rows = [
      ["Duração", (r) => r.sm.duration, fmtDur, null],
      ["DL célula média (Mbit/s)", (r) => cellStat(r, "dl_brate", "avg"), (v) => fmt(v, 1), "max"],
      ["DL célula p95 (Mbit/s)", (r) => cellStat(r, "dl_brate", "p95"), (v) => fmt(v, 1), "max"],
      ["DL célula pico (Mbit/s)", (r) => cellStat(r, "dl_brate", "max"), (v) => fmt(v, 1), "max"],
      ["UL célula média (Mbit/s)", (r) => cellStat(r, "ul_brate", "avg"), (v) => fmt(v, 2), "max"],
      ["UL célula pico (Mbit/s)", (r) => cellStat(r, "ul_brate", "max"), (v) => fmt(v, 2), "max"],
      ["PRBs DL média", (r) => cellStat(r, "pdsch_prbs", "avg"), (v) => fmt(v, 0), null],
      ["BLER DL", (r) => bler(r, "dl"), (v) => fmt(v, 2) + "%", "min"],
      ["BLER UL", (r) => bler(r, "ul"), (v) => fmt(v, 2) + "%", "min"],
      ["MCS DL médio", (r) => ueAgg(r, "dl_mcs"), (v) => fmt(v, 1), "max"],
      ["MCS UL médio", (r) => ueAgg(r, "ul_mcs"), (v) => fmt(v, 1), "max"],
      ["CQI médio", (r) => ueAgg(r, "cqi"), (v) => fmt(v, 1), "max"],
      ["RI DL médio", (r) => ueAgg(r, "dl_ri"), (v) => fmt(v, 2), "max"],
      ["SNR PUSCH médio (dB)", (r) => ueAgg(r, "pusch_snr_db"), (v) => fmt(v, 1), "max"],
      ["Latência média do escalonador", (r) => cellStat(r, "avg_latency", "avg"), (v) => fmt(v, 0), "min"],
      ...hostNames.flatMap((h) => [
        [`${h}: CPU média`, (r) => r.sm.hosts[h] && r.sm.hosts[h].cpu ? r.sm.hosts[h].cpu.avg : null, (v) => fmt(v, 1) + "%", "min"],
        [`${h}: temperatura máx.`, (r) => r.sm.hosts[h] && r.sm.hosts[h].temp ? r.sm.hosts[h].temp.max : null, (v) => fmt(v, 0) + " °C", "min"],
      ]),
      ...(CONFIG.ru ? [
        ["RU: potência média (W)", (r) => r.sm.ru && r.sm.ru.power ? r.sm.ru.power.avg : null, (v) => fmt(v, 1), "min"],
        ["RU: temperatura máx.", (r) => r.sm.ru && r.sm.ru.temp ? r.sm.ru.temp.max : null, (v) => fmt(v, 0) + " °C", "min"],
        ["RU: pacotes fora da janela", (r) => r.sm.ru && r.sm.ru.late_pct ? r.sm.ru.late_pct.avg : null, (v) => fmt(v, 3) + "%", "min"],
        ["RU: tempo sincronizada", (r) => r.sm.ru ? r.sm.ru.ok_sync : null, (v) => fmt(v, 1) + "%", "max"],
        ["RU: tempo com DU conectado", (r) => r.sm.ru ? r.sm.ru.ok_du : null, (v) => fmt(v, 1) + "%", "max"],
      ] : []),
    ];
    $("#hist-cmp-table").innerHTML = `<tr><th>Métrica</th>${res.map((r) => `<th class="num">${esc(r.e.name)}<br><span class="muted">${fmtDateTime(r.e.t_start)}</span></th>`).join("")}</tr>` +
      rows.map(([l, f, fm, best]) => {
        const vals = res.map(f);
        const ok = vals.filter((v) => v != null);
        const b = best && ok.length > 1 ? (best === "max" ? Math.max(...ok) : Math.min(...ok)) : null;
        return `<tr><td>${esc(l)}</td>${vals.map((v) => `<td class="num ${v != null && v === b ? "best" : ""}">${v == null ? "–" : esc(fm(v))}</td>`).join("")}</tr>`;
      }).join("") +
      `<tr><td>Notas</td>${res.map((r) => `<td class="notes num">${esc(r.e.notes || "")}</td>`).join("")}</tr>`;
    // gráficos sobrepostos (tempo desde o início de cada experimento)
    const o = { xrel: true };
    const ser = res.map((r, i) => ({ label: r.e.name, color: colorFor(i), fmt: (v) => fmt(v, 1) }));
    const grp = (pick) => res.map((r) => ({ data: [pick(r.d.series)].filter(Boolean) }));
    const cellOf = (S) => { const c = Object.entries(S).find(([k]) => k.startsWith("cell:")); return c ? c[1].data : null; };
    const plot = (id, pick, f, sc) => { Charts.make(id, ser, o); Charts.set(id, lines(grp(pick), f, sc)); };
    plot("hcc-dl", cellOf, "dl_brate", 1e-6);
    plot("hcc-ul", cellOf, "ul_brate", 1e-6);
    plot("hcc-prb", cellOf, "pdsch_prbs", 1);
    const gh = hostNames.find((h) => h !== CONFIG.local_host) || hostNames[0];
    $("#hcc-host-title").textContent = gh ? `CPU de ${gh}` : "CPU";
    plot("hcc-cpu", (S) => (S["host:" + gh] || {}).data, "cpu", 1);
    if (CONFIG.ru) plot("hcc-ru", (S) => (S.ru || {}).data, "temp", 1);
    $("#hist-compare").scrollIntoView({ behavior: "smooth", block: "start" });
  },

  // ---- gravar
  async toggleRec() {
    if (this.running) {
      if (!confirm(`Encerrar o experimento "${this.running.name}"?`)) return;
      await postJSON("api/history/experiments", { action: "stop" });
      await this.refreshHeader();
      if (currentTab === "history") this.refresh();
      return;
    }
    $("#rec-name").value = "";
    $("#rec-notes").value = "";
    $("#rec-dialog").showModal();
  },
  async startRec() {
    const name = $("#rec-name").value.trim();
    if (!name) { $("#rec-name").focus(); return; }
    try {
      await postJSON("api/history/experiments", { action: "start", name, notes: $("#rec-notes").value });
      $("#rec-dialog").close();
      await this.refreshHeader();
      if (currentTab === "history") this.refresh();
    } catch (e) { alert(e.message); }
  },
};

// ---- eventos
$("#rec").addEventListener("click", () => Hist.toggleRec());
$("#rec-start").addEventListener("click", (e) => { e.preventDefault(); Hist.startRec(); });
$("#rec-cancel").addEventListener("click", (e) => { e.preventDefault(); $("#rec-dialog").close(); });
$("#hist-preset").addEventListener("change", () => { $("#hist-custom").classList.toggle("hidden", $("#hist-preset").value !== "custom"); if ($("#hist-preset").value !== "custom") Hist.view(); });
$("#hist-go").addEventListener("click", () => Hist.view());
$("#hist-compare-btn").addEventListener("click", () => Hist.compare());
$("#hist-back").addEventListener("click", () => Hist.view());
$("#hist-exps").addEventListener("change", (e) => {
  const id = +e.target.dataset.sel;
  if (!id) return;
  if (e.target.checked) Hist.sel.add(id); else Hist.sel.delete(id);
  Hist.renderExps();
});
$("#hist-exps").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.view) { Hist.presets(); $("#hist-preset").value = "exp:" + b.dataset.view; Hist.view(); $("#hist-view").scrollIntoView({ behavior: "smooth" }); }
  if (b.dataset.edit) {
    const ex = Hist.exps.find((x) => x.id === +b.dataset.edit);
    const name = prompt("Nome do experimento:", ex.name);
    if (name == null) return;
    const notes = prompt("Notas (setup, o que mudou, observações):", ex.notes || "");
    if (notes == null) return;
    await postJSON("api/history/experiments", { action: "update", id: ex.id, name, notes });
    Hist.refresh();
  }
  if (b.dataset.cfg) {
    const ex = await api("api/history/experiment?id=" + b.dataset.cfg);
    $("#cfg-dialog-title").textContent = `Setup de "${ex.name}" (${fmtDateTime(ex.t_start)})`;
    $("#cfg-dialog-body").textContent = JSON.stringify(ex.setup, null, 2) + "\n\n# ---- config.env no início do experimento (chaves mascaradas)\n" + (ex.config || "(aba Configuração desligada: config.env não guardado)");
    $("#cfg-dialog").showModal();
  }
  if (b.dataset.del) {
    const ex = Hist.exps.find((x) => x.id === +b.dataset.del);
    if (!Settings.token) { Admin.open(); return; }   // login único (botão Admin do topo)
    if (!confirm(`Apagar o experimento "${ex.name}"? (só o marcador; as métricas do período continuam no histórico)`)) return;
    try { await postJSON("api/history/experiments", { action: "delete", id: ex.id }, { "X-Admin-Token": Settings.token }); Hist.sel.delete(ex.id); Hist.refresh(); }
    catch (err) { alert(err.message); }
  }
});
$("#cfg-dialog-close").addEventListener("click", () => $("#cfg-dialog").close());
setInterval(() => Hist.refreshHeader(), 5000);
