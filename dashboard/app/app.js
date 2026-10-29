/* Innova Center Dashboard — InnovaNetwork (sem dependências além do uPlot) */
"use strict";

// ---------------------------------------------------------------------------
//  Utilidades
// ---------------------------------------------------------------------------
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const store = {
  get(k, d) { try { const v = localStorage.getItem("icd." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("icd." + k, JSON.stringify(v)); } catch { /* sem storage */ } },
};
const PALETTE = ["#1554c0", "#6b7280", "#0ea5e9", "#f59e0b", "#7c3aed", "#10b981", "#ef4444", "#94a3b8"];
const colorFor = (i) => PALETTE[i % PALETTE.length];
// Nome curto e função de cada pod (o nome completo do pod fica no tooltip)
const NF_INFO = {
  amf: ["AMF", "acesso e mobilidade (N2)"], smf: ["SMF", "sessões PDU"], upf: ["UPF", "plano de usuário (N3/N6)"],
  nrf: ["NRF", "registro de funções"], scp: ["SCP", "roteamento de sinalização"], ausf: ["AUSF", "autenticação"],
  udm: ["UDM", "dados de assinante"], udr: ["UDR", "repositório de dados"], pcf: ["PCF", "políticas"],
  bsf: ["BSF", "vínculo de sessões"], nssf: ["NSSF", "seleção de slice"], mongodb: ["MongoDB", "banco de assinantes"],
  webui: ["WebUI", "cadastro de assinantes"], populate: ["Populate", "cadastro inicial"],
  chf: ["CHF", "tarifação"], nef: ["NEF", "exposição de rede"],
  gnb: ["gNB simulado", "UERANSIM"], ues: ["UEs simulados", "UERANSIM"], dashboard: ["Painel", "este site"],
};
function nfInfo(p) {
  const k = (p.label || p.component || "").toLowerCase();
  if (k === "webui" && CONFIG.core_kind === "free5gc") return ["WebConsole", "cadastro de assinantes"];
  return NF_INFO[k] || [p.label || p.component || p.name, ""];
}
// Nome do core ativo nos textos (troca quando o core ativo muda)
function paintCore() {
  $$(".core-name").forEach((e) => (e.textContent = CONFIG.core_name || "Open5GS"));
  document.body.dataset.core = CONFIG.core || "open5gs";
}

// Identificação do UE no rádio: nome / IMSI / IP (o gNB só conhece o RNTI)
function ueTitle(u) {
  const id = u.ident || {};
  return id.name || (id.imsi ? "IMSI " + id.imsi : "RNTI " + u.rnti);
}
function ueShort(u) {
  const id = u.ident || {};
  return id.name || (id.imsi ? "…" + id.imsi.slice(-4) : "RNTI " + u.rnti);
}
function ueIps(u) {
  const s = (u.ident && u.ident.sessions) || [];
  return s.filter((x) => x.ipv4).map((x) => x.ipv4 + (s.length > 1 ? " (" + x.dnn + ")" : "")).join(", ");
}
function ueKindTag(u) {
  const id = u.ident || {};
  if (!id.imsi) return '<span class="tag" title="ainda sem o vínculo RNTI → IMSI (precisa do log do gNB; aparece quando o UE troca mensagens com o core)">não identificado</span>';
  return id.kind === "ueransim" ? '<span class="tag">UERANSIM</span>' : '<span class="tag real">SIM real</span>';
}
const UE_STALE_SECONDS = 120;   // RNTIs parados há mais que isso ficam escondidos por padrão

function fmtRate(bps) {
  if (bps == null || isNaN(bps)) return "–";
  if (bps >= 1e9) return (bps / 1e9).toFixed(2) + " Gbit/s";
  if (bps >= 1e6) return (bps / 1e6).toFixed(1) + " Mbit/s";
  if (bps >= 1e3) return (bps / 1e3).toFixed(0) + " kbit/s";
  return bps.toFixed(0) + " bit/s";
}
const fmt = (v, d = 1) => (v == null || isNaN(v) ? "–" : Number(v).toFixed(d));
function ago(t) {
  if (!t) return "–";
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 60) return Math.round(s) + " s";
  if (s < 3600) return Math.round(s / 60) + " min";
  if (s < 86400) return (s / 3600).toFixed(1) + " h";
  return (s / 86400).toFixed(1) + " d";
}
const isoToEpoch = (s) => (s ? Date.parse(s) / 1000 : null);
const hhmmss = (s) => (s ? new Date(s).toLocaleTimeString("pt-BR", { hour12: false }) : "–");

async function api(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) {
    let msg = r.status + " " + r.statusText;
    try { msg = (await r.json()).error || msg; } catch { /* corpo não-JSON */ }
    throw new Error(msg);
  }
  return r.json();
}
function banner(msg) {
  const b = $("#banner");
  if (msg) { b.textContent = msg; b.classList.remove("hidden"); } else b.classList.add("hidden");
}

// ---------------------------------------------------------------------------
//  Tema e abas
// ---------------------------------------------------------------------------
function applyTheme(t) {
  if (t) document.documentElement.setAttribute("data-theme", t);
  else document.documentElement.removeAttribute("data-theme");
  Charts.restyle();
}
$("#theme").addEventListener("click", () => {
  const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  store.set("theme", next);
  applyTheme(next);
});

let currentTab = "overview";
function showTab(name) {
  currentTab = name;
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + name));
  store.set("tab", name);
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  refreshNow();
  if (name === "logs") Logs.ensureSources();
  setTimeout(() => Charts.resizeAll(), 30);
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

// ---------------------------------------------------------------------------
//  Gráficos (uPlot)
// ---------------------------------------------------------------------------
const Charts = {
  list: {},
  make(id, series, opts = {}) {
    const el = document.getElementById(id);
    if (!el) return null;
    if (this.list[id]) {
      const cur = this.list[id];
      const same = cur.series.length === series.length + 1 &&
        series.every((s, i) => cur.series[i + 1].label === s.label);
      if (same) return cur;
      cur.destroy();
      delete this.list[id];
    }
    const grid = { stroke: css("--grid"), width: 1 };
    const axis = { stroke: css("--muted"), grid, ticks: { stroke: css("--grid") } };
    const u = new uPlot({
      width: Math.max(280, el.clientWidth),
      height: opts.height || 220,
      cursor: { drag: { x: true, y: false } },
      scales: { x: { time: !opts.xrel }, ...(opts.scales || {}) },
      legend: { live: true },
      axes: [
        { ...axis, values: (u, vals) => vals.map(Charts.xfmt(opts)) },
        { ...axis, size: 60, values: opts.yfmt ? (u, vals) => vals.map(opts.yfmt) : undefined },
        ...(opts.y2 ? [{ ...axis, side: 1, scale: "y2", size: 55, grid: { show: false } }] : []),
      ],
      series: [
        { label: opts.xrel ? "Tempo" : "Hora", value: (u, v) => (v == null ? "–" : Charts.xfmt(opts)(v)) },
        ...series.map((s, i) => ({
          label: s.label, stroke: s.color || colorFor(i), width: s.width || 1.6,
          scale: s.scale || "y", dash: s.dash, spanGaps: !!opts.spanGaps,
          points: { size: 4 },
          fill: s.fill ? (s.color || colorFor(i)) + "22" : undefined,
          value: (u, v) => (v == null ? "–" : (s.fmt ? s.fmt(v) : fmt(v, s.dec ?? 1))),
        })),
      ],
    }, [[], ...series.map(() => [])], el);
    u._opts = { series, opts };
    this.list[id] = u;
    return u;
  },
  xfmt(opts) {
    if (opts.xfmt) return opts.xfmt;
    if (opts.xrel) return (v) => { const s = Math.round(v); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
    return (v) => new Date(v * 1000).toLocaleTimeString("pt-BR", { hour12: false });
  },
  set(id, data) {
    const u = this.list[id];
    if (u) u.setData(data);
  },
  resizeAll() {
    for (const [id, u] of Object.entries(this.list)) {
      const el = document.getElementById(id);
      if (el && el.offsetParent) u.setSize({ width: Math.max(280, el.clientWidth), height: u.height });
    }
  },
  restyle() {
    // Recria os gráficos com as cores do tema atual
    for (const [id, u] of Object.entries(this.list)) {
      const { series, opts } = u._opts;
      const data = u.data;
      u.destroy();
      delete this.list[id];
      this.make(id, series, opts);
      this.set(id, data);
    }
  },
};
window.addEventListener("resize", () => { clearTimeout(Charts._t); Charts._t = setTimeout(() => Charts.resizeAll(), 120); });

// Alinha várias séries em baldes de 1 s (eixo X comum)
function align(seriesList, field, scale = 1) {
  const buckets = new Map();
  seriesList.forEach((s, idx) => {
    const t = s.t || [];
    const vals = s[field] || [];
    for (let i = 0; i < t.length; i++) {
      const k = Math.round(t[i]);
      if (!buckets.has(k)) buckets.set(k, new Array(seriesList.length).fill(null));
      const v = vals[i];
      buckets.get(k)[idx] = v == null ? null : v * scale;
    }
  });
  const xs = [...buckets.keys()].sort((a, b) => a - b);
  return [xs, ...seriesList.map((_, idx) => xs.map((x) => buckets.get(x)[idx]))];
}
function cols(s, fields, scale = {}) {
  return [s.t || [], ...fields.map((f) => (s[f] || []).map((v) => (v == null ? null : v * (scale[f] || 1))))];
}

// ---------------------------------------------------------------------------
//  Estado global e atualização periódica
// ---------------------------------------------------------------------------
let CONFIG = {};
let LAST_OVERVIEW = null;
let busy = false;

async function refreshNow() {
  if (busy) return;
  busy = true;
  try {
    if (currentTab === "overview") await Overview.refresh();
    else {
      await Overview.refresh(true);
      if (currentTab === "ran") await Ran.refresh();
      else if (currentTab === "core") await Core.refresh();
      else if (currentTab === "hosts") await Machines.refresh();
      else if (currentTab === "ru") await RuTab.refresh();
      else if (currentTab === "control") await Control.refresh();
      else if (currentTab === "settings") await Settings.refresh();
      else if (currentTab === "history") await Hist.refresh();
      else if (currentTab === "docs") await Docs.refresh();
      else if (currentTab === "logs" && Logs.src === null) Logs.renderSources();
    }
    banner(null);
  } catch (e) {
    banner("Falha ao falar com o painel: " + e.message);
  } finally {
    busy = false;
  }
}

function updatePills(ov) {
  const g = ov.gnb.status;
  const pg = $("#pill-gnb");
  if (!g.enabled) { pg.className = "pill"; pg.textContent = "gNB: desligado"; }
  else if (g.connected && g.last_msg && Date.now() / 1000 - g.last_msg < 10) {
    const n = ov.gnb.ues.filter((u) => u.active).length;
    pg.className = "pill ok"; pg.textContent = `gNB ok · ${n} UE${n === 1 ? "" : "s"}`;
  } else { pg.className = "pill err"; pg.textContent = "gNB sem dados"; pg.title = g.error || ""; }
  const c = ov.core;
  const pc = $("#pill-core");
  pc.textContent = `${ov.core_name || "core"} ${c.pods_ready}/${c.pods_total}`;
  pc.title = "Pods do core ativo (" + (ov.core_name || "") + ")";
  // o core ativo mudou (troca pela aba Controle ou por fora): recarrega a configuração e os textos
  if (ov.core_active && CONFIG.core && ov.core_active !== CONFIG.core) reloadConfig();
  pc.className = "pill " + (c.pods_error ? "err" : c.pods_ready === c.pods_total && c.pods_total ? "ok" : "warn");
  const r = ov.ru;
  const pr = $("#pill-ru");
  pr.classList.toggle("hidden", !r);
  if (r) {
    const good = (v) => v === "Ready" || v === "SYNCHRONIZED";
    const radio = good(r.sync) && good(r.rf) && good(r.dpd);
    pr.textContent = !r.online ? "RU sem dados" : !radio ? "RU com falha" : good(r.du) ? "RU ok · DU conectado" : "RU pronta · sem DU";
    pr.className = "pill " + (!r.online || !radio ? "err" : good(r.du) ? "ok" : "warn");
    pr.title = r.error || `sync ${r.sync} · RF ${r.rf} · DPD ${r.dpd} · DU ${r.du}`;
  }
}

// ---------------------------------------------------------------------------
//  Visão geral
// ---------------------------------------------------------------------------
const Overview = {
  async refresh(pillsOnly = false) {
    const ov = await api("api/overview");
    LAST_OVERVIEW = ov;
    updatePills(ov);
    if (pillsOnly) return;
    this.kpis(ov);
    this.ranUes(ov);
    this.coreUes(ov);
    this.pods(ov);
    this.events(ov);
  },
  kpis(ov) {
    const cell = ov.gnb.cell || {};
    const act = ov.gnb.ues.filter((u) => u.active);
    const c = ov.core;
    const regs = c.ues.filter((u) => u.registered).length;
    const k = [
      { l: "UEs no rádio", v: ov.gnb.status.enabled ? act.length : "–", s: ov.gnb.status.connected ? "gNB conectado" : "gNB sem dados", c: ov.gnb.status.connected ? "" : "err" },
      { l: "Downlink da célula", v: fmtRate(cell.dl_brate), s: "agora" },
      { l: "Uplink da célula", v: fmtRate(cell.ul_brate), s: "agora" },
      { l: "gNBs no AMF (N2)", v: c.nof_gnbs ?? "–", s: (c.gnbs || []).map((g) => g.addr).join(", ") || "–" },
      { l: "UEs registrados", v: regs, s: `${c.ues.filter((u) => u.registered && u.kind === "real").length} real(is) · ${c.ues.filter((u) => u.registered && u.kind === "ueransim").length} simulado(s) · ${c.sessions.length} sessões` },
      { l: "Pods do core", v: `${c.pods_ready}/${c.pods_total}`, s: `${c.restarts} reinício(s) no total`, c: c.pods_ready === c.pods_total ? "ok" : "warn" },
      CONFIG.core_kind === "free5gc"
        ? { l: "Sessões recusadas (SMF)", v: c.counters.dnn_not_subscribed || 0, s: "DNN/slice fora da configuração", c: c.counters.dnn_not_subscribed ? "warn" : "ok" }
        : { l: "Erros PFCP (UPF)", v: c.counters.pfcp_cannot_find || 0, s: "Cannot find PFCP-Node", c: c.counters.pfcp_cannot_find ? "err" : "ok" },
    ];
    $("#kpis").innerHTML = k.map((x) => `<div class="kpi ${x.c || ""}"><div class="label">${esc(x.l)}</div>
      <div class="value">${esc(x.v)}</div><div class="sub">${esc(x.s)}</div></div>`).join("");
  },
  ranUes(ov) {
    const now = Date.now() / 1000;
    const ues = ov.gnb.ues.filter((u) => u.active || now - u.last_seen <= UE_STALE_SECONDS);
    $("#ov-ran-sub").textContent = ov.gnb.status.enabled ? `(${CONFIG.gnb_name || "gNB"} · só UEs reais; o UERANSIM não passa pelo rádio)` : "(métricas do gNB desligadas)";
    if (!ues.length) { $("#ov-ran-ues").innerHTML = `<tr><td class="empty">Nenhum UE visto pelo gNB na última janela.</td></tr>`; return; }
    $("#ov-ran-ues").innerHTML = `<tr><th>UE</th><th>IP</th><th class="num">DL</th><th class="num">UL</th><th class="num">MCS DL/UL</th>
      <th class="num">CQI</th><th class="num">RI</th><th class="num">BLER DL/UL (10 s)</th><th class="num">SNR</th><th>Visto</th></tr>` +
      ues.map((u) => {
        const l = u.last || {};
        const bl = (v) => (v == null ? "–" : `<span class="tag ${v > 10 ? "err" : v > 3 ? "warn" : "ok"}">${fmt(v)}%</span>`);
        return `<tr class="${u.active ? "" : "dim"}"><td><b>${esc(ueTitle(u))}</b> ${ueKindTag(u)}<br><span class="muted">RNTI ${esc(u.rnti)} · pci ${esc(u.pci)}</span></td>
          <td>${esc(ueIps(u)) || '<span class="muted">–</span>'}</td>
          <td class="num">${fmtRate(l.dl_brate)}</td><td class="num">${fmtRate(l.ul_brate)}</td>
          <td class="num">${fmt(l.dl_mcs, 0)} / ${fmt(l.ul_mcs, 0)}</td><td class="num">${fmt(l.cqi, 0)}</td>
          <td class="num">${fmt(l.dl_ri, 1)}</td><td class="num" title="últimos 10 s: ${l.dl_tbs_win || 0} blocos DL, ${l.ul_tbs_win || 0} UL">${bl(l.dl_bler_win)} ${bl(l.ul_bler_win)}</td>
          <td class="num">${fmt(l.pusch_snr_db)} dB</td><td>${u.active ? "agora" : "há " + ago(u.last_seen)}</td></tr>`;
      }).join("");
  },
  coreUes(ov) {
    const ues = ov.core.ues;
    if (!ues.length) { $("#ov-core-ues").innerHTML = `<tr><td class="empty">Nenhum assinante visto nos logs do AMF.</td></tr>`; return; }
    $("#ov-core-ues").innerHTML = `<tr><th>IMSI</th><th>Tipo</th><th>Estado</th><th>Sessões (DNN → IP)</th><th>Último evento</th></tr>` +
      ues.map((u) => `<tr><td><b>${esc(u.imsi)}</b>${u.name ? `<br><span class="muted">${esc(u.name)}</span>` : ""}</td>
        <td>${u.kind === "ueransim" ? '<span class="tag">UERANSIM (simulado)</span>' : '<span class="tag real">SIM real</span>'}</td>
        <td>${u.registered ? '<span class="tag ok">registrado</span>' : '<span class="tag">fora</span>'}</td>
        <td>${u.sessions.length ? u.sessions.map((s) => `${esc(s.dnn)} → <b>${esc(s.ipv4 || s.ipv6)}</b>`).join("<br>") : '<span class="muted">nenhuma</span>'}</td>
        <td>${esc(u.event || "")} <span class="muted">${hhmmss(u.ts)}</span></td></tr>`).join("");
  },
  pods(ov) {
    $("#ov-pods").innerHTML = `<tr><th>Componente</th><th>Estado</th><th class="num">Prontos</th><th class="num">Reinícios</th><th>Idade</th><th>IP</th><th>Link RAN</th></tr>` +
      ov.pods.map((p) => {
        const st = p.phase === "Running" && p.all_ready ? "ok" : p.phase === "Running" ? "warn" : "err";
        const [nm, role] = nfInfo(p);
        return `<tr><td title="pod: ${esc(p.name)}"><b>${esc(nm)}</b> <span class="muted">${esc(role)}</span></td><td><span class="tag ${st}">${esc(p.reason || p.phase)}</span></td>
          <td class="num">${esc(p.ready)}</td><td class="num">${p.restarts ? `<span class="tag warn">${p.restarts}</span>` : 0}</td>
          <td>${p.age != null ? ago(Date.now() / 1000 - p.age) : "–"}</td><td>${esc(p.ip)}</td><td>${esc(p.net1 || "")}</td></tr>`;
      }).join("");
  },
  events(ov) {
    const ev = ov.core.events;
    $("#ov-events").innerHTML = ev.length ? ev.map((e) => `<div class="ev ${esc(e.level)}">
      <span class="t">${hhmmss(e.ts)}</span><span class="src">${esc(e.src)}</span>
      <span class="msg">${esc(e.msg)}</span><span class="cnt">${e.count > 1 ? "×" + e.count : ""}</span></div>`).join("")
      : `<div class="empty">Sem eventos.</div>`;
  },
};

// ---------------------------------------------------------------------------
//  Rádio (gNB)
// ---------------------------------------------------------------------------
const Ran = {
  paused: false,
  selected: store.get("ran.ue", null),
  async refresh() {
    if (this.paused) return;
    const win = +$("#ran-window").value;
    const seq = (this._seq = (this._seq || 0) + 1);
    const d = await api("api/ran?window=" + win);
    if (seq !== this._seq) return;   // chegou depois de uma resposta mais nova
    this.last = d;
    this.render(d);
  },
  render(d) {
    const st = d.status;
    $("#ran-status").textContent = !st.enabled ? "métricas do gNB desligadas (GNB_METRICS_URL vazio)"
      : st.connected ? `conectado a ${st.url} · ${st.messages} mensagens · última há ${ago(st.last_msg)}`
        : `sem conexão com ${st.url}: ${st.error || "aguardando"}`;
    const all = d.ues;
    const now = Date.now() / 1000;
    const stale = all.filter((u) => !u.active && now - u.last_seen > UE_STALE_SECONDS);
    const ues = this.showOld ? all : all.filter((u) => !stale.includes(u) || u.id === this.selected);
    ues.sort((a, b) => (b.active - a.active) || (b.last_seen - a.last_seen));
    const ob = $("#ran-old");
    ob.classList.toggle("hidden", !stale.length);
    ob.textContent = this.showOld ? `Esconder ${stale.length} antigos` : `Mostrar ${stale.length} antigos`;
    $("#ran-ident-note").classList.toggle("hidden", d.ident_source || !all.length);
    // seletor de UE
    const sel = $("#ran-ue");
    const ids = ues.map((u) => u.id);
    if (!ids.includes(this.selected)) this.selected = (ues.find((u) => u.active) || ues[0] || {}).id || null;
    const optsHtml = ues.map((u) => `<option value="${esc(u.id)}" ${u.id === this.selected ? "selected" : ""}>${esc(ueTitle(u))} · RNTI ${esc(u.rnti)}${u.active ? "" : " (inativo)"}</option>`).join("");
    // só recria a lista quando ela muda e não está aberta (recriar uma lista aberta fecha a lista)
    if (this._opts !== optsHtml && document.activeElement !== sel) { sel.innerHTML = optsHtml || "<option>sem UEs</option>"; this._opts = optsHtml; }
    // cartões dos UEs
    $("#ran-uecards").innerHTML = ues.map((u) => {
      const l = u.last || {};
      return `<div class="uecard ${u.id === this.selected ? "sel" : ""} ${u.active ? "" : "inactive"}" data-id="${esc(u.id)}">
        <div class="h"><span class="t" title="${esc((u.ident && u.ident.imsi) || "")}">${esc(ueTitle(u))}</span><span class="muted">${u.active ? "ativo" : "há " + ago(u.last_seen)}</span></div>
        <div class="id">${ueKindTag(u)} ${ueIps(u) ? `<span class="ip">${esc(ueIps(u))}</span>` : ""}
          <span class="muted">RNTI ${esc(u.rnti)}${u.ident && u.ident.name && u.ident.imsi ? " · …" + esc(u.ident.imsi.slice(-6)) : ""}</span></div>
        <div class="m"><div><span>DL</span> ${fmtRate(l.dl_brate)}</div><div><span>UL</span> ${fmtRate(l.ul_brate)}</div><div><span>CQI</span> ${fmt(l.cqi, 0)}</div>
        <div><span>MCS</span> ${fmt(l.dl_mcs, 0)}/${fmt(l.ul_mcs, 0)}</div><div title="últimos 10 s"><span>BLER</span> ${fmt(l.dl_bler_win)}/${fmt(l.ul_bler_win)}%</div><div><span>SNR</span> ${fmt(l.pusch_snr_db)}</div></div></div>`;
    }).join("") || `<div class="empty">Nenhum UE visto pelo gNB nesta janela.</div>`;

    const mbps = (v) => fmt(v, 1);
    // célula
    const cell = d.cells[0];
    Charts.make("c-cell-tput", [{ label: "DL", fill: true, fmt: mbps }, { label: "UL", color: "#6b7280", fill: true, fmt: mbps }]);
    Charts.set("c-cell-tput", cell ? cols(cell.series, ["dl_brate", "ul_brate"], { dl_brate: 1e-6, ul_brate: 1e-6 }) : [[], [], []]);
    Charts.make("c-cell-prb", [{ label: "PDSCH (DL)", dec: 0 }, { label: "PUSCH (UL)", color: "#6b7280", dec: 0 }]);
    Charts.set("c-cell-prb", cell ? cols(cell.series, ["pdsch_prbs", "pusch_prbs"]) : [[], [], []]);
    // por UE
    const ueSeries = ues.map((u, i) => ({ label: ueShort(u), color: colorFor(i), fmt: mbps }));
    Charts.make("c-ue-dl", ueSeries);
    Charts.set("c-ue-dl", align(ues.map((u) => u.series), "dl_brate", 1e-6));
    Charts.make("c-ue-ul", ueSeries);
    Charts.set("c-ue-ul", align(ues.map((u) => u.series), "ul_brate", 1e-6));
    // UE selecionado
    const u = ues.find((x) => x.id === this.selected);
    $("#ran-sel").textContent = u ? `${ueTitle(u)}${ueIps(u) ? " · " + ueIps(u) : ""} · RNTI ${u.rnti} · visto desde ${new Date(u.first_seen * 1000).toLocaleTimeString("pt-BR")}` : "";
    const s = u ? u.series : { t: [] };
    Charts.make("c-bler", [{ label: "BLER DL" }, { label: "BLER UL", color: "#6b7280" }], { spanGaps: true, scales: { y: { range: [0, 100] } } });
    Charts.set("c-bler", cols(s, ["dl_bler", "ul_bler"]));
    Charts.make("c-mcs", [{ label: "MCS DL", dec: 0 }, { label: "MCS UL", color: "#6b7280", dec: 0 }], { spanGaps: true, scales: { y: { range: [0, 28] } } });
    Charts.set("c-mcs", cols(s, ["dl_mcs", "ul_mcs"]));
    Charts.make("c-cqi", [{ label: "CQI", dec: 0 }, { label: "RI DL", color: "#0ea5e9", scale: "y2" }, { label: "RI UL", color: "#6b7280", scale: "y2" }],
      { y2: true, scales: { y: { range: [0, 15] }, y2: { range: [0, 4] } } });
    Charts.set("c-cqi", cols(s, ["cqi", "dl_ri", "ul_ri"]));
    Charts.make("c-snr", [{ label: "SNR PUSCH" }, { label: "RSRP PUSCH", color: "#6b7280", scale: "y2" }, { label: "SNR PUCCH", color: "#0ea5e9" }], { spanGaps: true, y2: true });
    Charts.set("c-snr", cols(s, ["pusch_snr_db", "pusch_rsrp_db", "pucch_snr_db"]));
    Charts.make("c-bs", [{ label: "BSR (UL)", dec: 0 }, { label: "Buffer DL", color: "#6b7280", dec: 0 }]);
    Charts.set("c-bs", cols(s, ["bsr", "dl_bs"]));
    Charts.make("c-ta", [{ label: "TA", dec: 0 }, { label: "PHR", color: "#6b7280", scale: "y2", dec: 0 }], { y2: true });
    Charts.set("c-ta", cols(s, ["ta_ns", "last_phr"]));
    // escalonador
    Charts.make("c-lat", [{ label: "média (célula)", dec: 0 }, { label: "máx (célula)", color: "#6b7280", dec: 0 }, { label: "MAC DL média", color: "#0ea5e9", dec: 1 }]);
    const cs = cell ? cell.series : { t: [] };
    const la = align([cs, cs, d.du.series], "avg_latency");
    la[2] = align([cs, cs, d.du.series], "max_latency")[2];
    la[3] = align([cs, cs, d.du.series], "mac_dl_avg_latency_us")[3];
    Charts.set("c-lat", la);
    Charts.make("c-fail", [{ label: "HARQ DL atrasado", dec: 0 }, { label: "HARQ UL atrasado", color: "#6b7280", dec: 0 },
      { label: "PDCCH DL falho", color: "#f59e0b", dec: 0 }, { label: "PDCCH UL falho", color: "#7c3aed", dec: 0 },
      { label: "UCI falho", color: "#ef4444", dec: 0 }]);
    Charts.set("c-fail", cell ? cols(cell.series, ["late_dl_harqs", "late_ul_harqs", "failed_dl_pdcch", "failed_ul_pdcch", "failed_uci_allocs"]) : [[], [], [], [], [], []]);
  },
  showOld: false,
  select(id) {
    if (!id) return;
    this.selected = id;
    store.set("ran.ue", id);
    $("#ran-ue").value = id;
    if (this.last) this.render(this.last);   // mostra na hora com os dados que já temos
    else this.refresh();
  },
};
$("#ran-ue").addEventListener("change", (e) => { Ran.select(e.target.value); e.target.blur(); });
// Cartões dos UEs: um ouvinte só, no contêiner, no "pointerdown". Os cartões são recriados a cada 2 s, e um
// "click" que começa num cartão e termina no cartão novo se perde.
$("#ran-uecards").addEventListener("pointerdown", (e) => {
  const c = e.target.closest(".uecard");
  if (c && e.button === 0) Ran.select(c.dataset.id);
});
$("#ran-window").addEventListener("change", () => { store.set("ran.window", $("#ran-window").value); Ran.refresh(); });
$("#ran-pause").addEventListener("click", (e) => {
  Ran.paused = !Ran.paused;
  e.target.textContent = Ran.paused ? "Continuar" : "Pausar";
  e.target.classList.toggle("on", Ran.paused);
  if (!Ran.paused) Ran.refresh();
});
$("#ran-csv").addEventListener("click", (e) => { e.currentTarget.href = "api/ran.csv?window=" + $("#ran-window").value; });

// ---------------------------------------------------------------------------
//  Logs
// ---------------------------------------------------------------------------
const MAX_LINES = 20000;
const Logs = {
  src: null,          // {kind: "pod"|"gnb", pod, container, label}
  lines: [],
  es: null,
  pending: [],
  filterRe: null,
  async ensureSources() {
    if (!LAST_OVERVIEW) await Overview.refresh(true);
    this.renderSources();
    if (!this.src) {
      const saved = store.get("logs.src", null);
      const pods = LAST_OVERVIEW.pods;
      if (saved && saved.kind === "pod") {
        // pod pode ter sido recriado (nome novo): procura pelo mesmo papel (label) e contêiner
        const p = pods.find((p) => p.name === saved.pod) ||
          pods.find((p) => p.label === saved.plabel && p.containers.includes(saved.container));
        if (p) {
          const nm = nfInfo(p)[0];
          return this.open({ kind: "pod", pod: p.name, container: saved.container, component: p.component, plabel: p.label,
            label: p.containers.length > 1 ? `${nm} · ${saved.container}` : nm });
        }
      } else if (saved && saved.kind === "gnb") return this.open(saved);
      const amf = pods.find((p) => p.component === "amf");
      if (amf) this.open({ kind: "pod", pod: amf.name, container: amf.containers[0], component: "amf", plabel: amf.label, label: "AMF" });
    }
  },
  renderSources() {
    const pods = (LAST_OVERVIEW && LAST_OVERVIEW.pods) || [];
    const core = pods.filter((p) => (p.group || "core") === "core");
    const groups = {};
    pods.filter((p) => (p.group || "core") !== "core").forEach((p) => (groups[p.instance || "outros"] ||= []).push(p));
    const item = (p, c) => {
      const nm = nfInfo(p)[0];
      const label = p.containers.length > 1 ? `${nm} · ${c}` : nm;
      const dot = p.phase === "Running" && p.all_ready ? "ok" : p.phase === "Running" ? "warn" : "err";
      const act = this.src && this.src.kind === "pod" && this.src.pod === p.name && this.src.container === c ? "active" : "";
      return `<button class="src ${act}" data-pod="${esc(p.name)}" data-c="${esc(c)}" data-comp="${esc(p.component)}" data-plabel="${esc(p.label)}" data-label="${esc(label)}" title="${esc(nfInfo(p)[1] ? nfInfo(p)[1] + " — " : "")}pod ${esc(p.name)}">
        <span>${esc(label)}</span><span class="dot ${dot}"></span></button>`;
    };
    const gnbAct = this.src && this.src.kind === "gnb" ? "active" : "";
    const g = LAST_OVERVIEW && LAST_OVERVIEW.gnb_log;
    const gdot = g && g.last_push && Date.now() / 1000 - g.last_push < 30 ? "ok" : "";
    $("#log-sources").innerHTML =
      `<div class="grp">RAN</div><button class="src ${gnbAct}" data-gnb="1"><span>${esc(CONFIG.gnb_name || "gNB")} (real)</span><span class="dot ${gdot}"></span></button>` +
      `<div class="grp">Core 5G (${esc(CONFIG.core_name || "Open5GS")})</div>` + core.flatMap((p) => p.containers.map((c) => item(p, c))).join("") +
      Object.entries(groups).map(([g, ps]) => `<div class="grp">${esc(g === "ueransim" ? "UERANSIM (simulador)" : g)}</div>` + ps.flatMap((p) => p.containers.map((c) => item(p, c))).join("")).join("");
    $$("#log-sources .src").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.gnb) this.open({ kind: "gnb", label: (CONFIG.gnb_name || "gNB") + " (real)" });
      else this.open({ kind: "pod", pod: b.dataset.pod, container: b.dataset.c, component: b.dataset.comp, plabel: b.dataset.plabel, label: b.dataset.label });
    }));
  },
  stop() {
    if (this.es) { this.es.close(); this.es = null; }
  },
  async open(src) {
    this.stop();
    this.src = src;
    store.set("logs.src", src);
    this.renderSources();
    $("#log-title").textContent = src.label;
    this.lines = [];
    this.render(true);
    const tail = $("#log-tail").value;
    const view = $("#log-view");
    if (src.kind === "gnb") {
      if (!CONFIG.gnb_log_ingest) {
        this.sys("O log do gNB real chega por um agente no servidor do gNB (dashboard/agent/gnb-log-agent.py).");
        this.sys("Ingestão desligada: defina DASHBOARD_INGEST_TOKEN no config.env e instale o agente (ver docs/componentes/painel.md).");
        return;
      }
      if ($("#log-follow").checked) return this.follow("api/gnb-log/stream?tail=" + tail);
      const d = await api("api/gnb-log?tail=" + tail);
      if (!d.lines.length) this.sys("Nenhuma linha recebida do agente ainda.");
      this.add(d.lines);
      return;
    }
    const q = `pod=${encodeURIComponent(src.pod)}&container=${encodeURIComponent(src.container)}&tail=${tail}&core=${encodeURIComponent(CONFIG.core || "")}`;
    if ($("#log-follow").checked) return this.follow("api/logs/stream?" + q);
    try {
      const d = await api("api/logs?" + q);
      this.add(d.lines);
    } catch (e) { this.sys("Erro: " + e.message); }
    view.scrollTop = view.scrollHeight;
  },
  follow(url) {
    const es = new EventSource(url);
    this.es = es;
    es.onmessage = (e) => { this.pending.push(e.data); this.schedule(); };
    es.addEventListener("status", (e) => this.sys(e.data));
    es.onerror = () => {
      if (this.es !== es) return;
      this.sys("conexão perdida; tentando de novo…");
    };
  },
  schedule() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = null;
      const p = this.pending; this.pending = [];
      this.add(p);
    });
  },
  sys(msg) { this.add(["\u0000" + msg]); },
  add(newLines) {
    if (!newLines.length) return;
    for (const l of newLines) this.lines.push(l);
    if (this.lines.length > MAX_LINES) this.lines.splice(0, this.lines.length - MAX_LINES);
    this.render(false, newLines);
  },
  levelOf(l) {
    if (/\b(ERROR|FATAL|CRIT)\b|\[E\]|error:/i.test(l)) return "e";
    if (/\bWARN(ING)?\b|\[W\]/i.test(l)) return "w";
    if (/\bDEBUG\b|\[D\]/.test(l)) return "d";
    return "i";
  },
  passes(l) {
    const lvl = $("#log-level").value;
    if (l.startsWith("\u0000")) return true;
    if (lvl) { const k = this.levelOf(l); if (lvl === "error" ? k !== "e" : k !== "e" && k !== "w") return false; }
    if (this.filterRe && !this.filterRe.test(l)) return false;
    return true;
  },
  fmtLine(l) {
    if (l.startsWith("\u0000")) return `<span class="sys">— ${esc(l.slice(1))}</span>`;
    let ts = "", rest = l;
    const m = /^(\d{4}-\d\d-\d\dT[\d:.]+Z) (.*)$/.exec(l);
    if (m) {
      rest = m[2];
      // Se a linha já tem horário próprio (Open5GS: "10/21 19:02:13.271:"), não repete o do Kubernetes
      // free5GC: "2026-10-22T20:25:09.5Z [INFO]..." (também já tem horário)
      if (/^\d{4}-\d\d-\d\dT[\d:.]+Z /.test(rest)) rest = rest.replace(/^\S+ /, "");
      if (!/^\d\d\/\d\d \d\d:\d\d:\d\d/.test(rest)) ts = new Date(m[1]).toLocaleTimeString("pt-BR", { hour12: false }) + "." + (m[1].split(".")[1] || "000").slice(0, 3) + " ";
    }
    let body = esc(rest);
    if (this.filterRe) {
      const re = new RegExp(this.filterRe.source, this.filterRe.flags.includes("g") ? this.filterRe.flags : this.filterRe.flags + "g");
      body = body.replace(re, (x) => `<mark>${x}</mark>`);
    }
    const k = this.levelOf(rest);
    return `<span class="ts">${esc(ts)}</span>${k === "i" ? body : `<span class="${k}">${body}</span>`}`;
  },
  render(full, newLines) {
    const view = $("#log-view");
    const atBottom = view.scrollHeight - view.scrollTop - view.clientHeight < 40;
    if (full || !newLines) {
      const shown = this.lines.filter((l) => this.passes(l));
      view.innerHTML = shown.slice(-MAX_LINES).map((l) => this.fmtLine(l)).join("\n");
      $("#log-count").textContent = `${shown.length} de ${this.lines.length} linhas`;
    } else {
      const shown = newLines.filter((l) => this.passes(l));
      if (shown.length) view.insertAdjacentHTML("beforeend", (view.innerHTML ? "\n" : "") + shown.map((l) => this.fmtLine(l)).join("\n"));
      // poda o DOM quando passa do limite
      if (view.childElementCount > MAX_LINES * 2.2) return this.render(true);
      const total = this.lines.filter((l) => this.passes(l)).length;
      $("#log-count").textContent = `${total} de ${this.lines.length} linhas`;
    }
    if (atBottom || full) view.scrollTop = view.scrollHeight;
  },
  setFilter(txt) {
    this.filterRe = null;
    if (txt) {
      const m = /^\/(.+)\/([a-z]*)$/.exec(txt);
      try { this.filterRe = m ? new RegExp(m[1], m[2].replace("g", "")) : new RegExp(txt.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i"); }
      catch { this.filterRe = null; }
    }
    this.render(true);
  },
  download() {
    const blob = new Blob([this.lines.filter((l) => !l.startsWith("\u0000")).join("\n") + "\n"], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    const name = (this.src ? (this.src.component || "gnb") + (this.src.container ? "-" + this.src.container : "") : "log");
    a.download = `${name}-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "")}.log`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  },
};
$("#log-filter").addEventListener("input", (e) => { clearTimeout(Logs._ft); Logs._ft = setTimeout(() => Logs.setFilter(e.target.value.trim()), 200); });
$("#log-level").addEventListener("change", () => Logs.render(true));
$("#log-wrap").addEventListener("change", (e) => { $("#log-view").classList.toggle("wrap", e.target.checked); store.set("logs.wrap", e.target.checked); });
$("#log-follow").addEventListener("change", () => Logs.src && Logs.open(Logs.src));
$("#log-tail").addEventListener("change", () => Logs.src && Logs.open(Logs.src));
$("#log-reload").addEventListener("click", () => Logs.src && Logs.open(Logs.src));
$("#log-download").addEventListener("click", () => Logs.download());

// ---------------------------------------------------------------------------
//  Core (processos e tráfego do core ativo; Prometheus só no Open5GS)
// ---------------------------------------------------------------------------
const Core = {
  view: "metrics",
  setView(v) {
    this.view = v;
    store.set("core.view", v);
    $$("#core-seg [data-view]").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
    $("#core-metrics").classList.toggle("hidden", v !== "metrics");
    $("#core-webui").classList.toggle("hidden", v !== "webui");
    const f = $("#webui-frame");
    if (v === "webui" && !f.getAttribute("src")) f.src = this.webuiUrl();
    if (v === "metrics") refreshNow();
  },
  webuiUrl() {
    return `${location.protocol}//${location.hostname}:${CONFIG.webui_port}/`;
  },
  async live() {
    const d = await api("api/core/live?window=" + $("#core-window").value);
    const lg = d.log || {};
    const c = lg.counters || {};
    const mb = (v) => fmt(v, 1);
    const ifs = d.ifaces || [];
    const sum = (pred, k) => ifs.filter(pred).reduce((a, x) => a + (x[k] || 0), 0);
    const n6 = (x) => /^(ogstun|upfgtp)/.test(x.iface);
    const nfs = d.nfs || [];
    const cpuTot = nfs.reduce((a, x) => a + x.cpu, 0);
    const memTot = nfs.reduce((a, x) => a + x.rss, 0);
    const errs = (c.amf_error || 0) + (c.smf_error || 0) + (c.upf_error || 0);
    const k = [
      { l: "gNBs conectados (N2)", v: lg.nof_gnbs ?? lg.gnbs?.length ?? "–", s: (lg.gnbs || []).map((g) => g.addr).join(", ") },
      { l: "UEs registrados", v: lg.ues_registered ?? "–", s: `${lg.ues_total ?? 0} assinantes vistos` },
      { l: "Sessões PDU", v: lg.sessions ?? "–", s: "abertas no SMF" },
      { l: "Downlink agora", v: fmtRate(sum(n6, "tx_bps")), s: "saindo do UPF para os UEs" },
      { l: "Uplink agora", v: fmtRate(sum(n6, "rx_bps")), s: "vindo dos UEs" },
      { l: "CPU do core", v: fmt(cpuTot, 0) + "%", s: `${nfs.length} processos · ${fmtBytes(memTot)} de RAM` },
      { l: "Erros nos logs", v: errs, s: "AMF/SMF/UPF desde que iniciaram", cls: errs ? "warn" : "ok" },
    ];
    $("#core-live-kpis").innerHTML = k.map((x) => `<div class="kpi ${x.cls || ""}"><div class="label">${esc(x.l)}</div>
      <div class="value">${esc(x.v)}</div><div class="sub">${esc(x.s || "")}</div></div>`).join("");
    $("#core-live-status").textContent = d.enabled === false ? "leitura do host desligada" : d.error ? "erro: " + d.error : "atualiza a cada 2 s · sem Prometheus, sem reiniciar o core";
    // N6 por DNN
    const tr = d.traffic || { t: [] };
    const tuns = Object.keys(tr).filter((x) => /^(ogstun|upfgtp)/.test(x) && x.endsWith("_tx")).map((x) => x.slice(0, -3)).sort();
    const dnn = (t) => (d.devs || {})[t] || t;
    const n6s = [];
    const n6cols = [tr.t];
    tuns.forEach((t, i) => {
      n6s.push({ label: `DL ${dnn(t)}`, color: colorFor(i * 2), fmt: mb });
      n6s.push({ label: `UL ${dnn(t)}`, color: colorFor(i * 2 + 1), fmt: mb });
      n6cols.push((tr[t + "_tx"] || []).map((v) => (v == null ? null : v / 1e6)));
      n6cols.push((tr[t + "_rx"] || []).map((v) => (v == null ? null : v / 1e6)));
    });
    Charts.make("c-upf-n6", n6s.length ? n6s : [{ label: "sem túneis" }]);
    Charts.set("c-upf-n6", n6s.length ? n6cols : [tr.t, tr.t.map(() => null)]);
    Charts.make("c-upf-n3", [{ label: "DL para o gNB", fill: true, fmt: mb }, { label: "UL do gNB", color: "#6b7280", fill: true, fmt: mb }]);
    Charts.set("c-upf-n3", [tr.t, (tr.net1_tx || []).map((v) => (v == null ? null : v / 1e6)), (tr.net1_rx || []).map((v) => (v == null ? null : v / 1e6))]);
    const cpu = d.cpu || { t: [] };
    const names = Object.keys(cpu).filter((x) => x !== "t").sort();
    Charts.make("c-nf-cpu", names.map((n, i) => ({ label: n.toUpperCase(), color: colorFor(i), dec: 1 })));
    Charts.set("c-nf-cpu", [cpu.t, ...names.map((n) => cpu[n])]);
    // tabelas
    const ce = (nf, l) => c[nf + "_" + l];
    $("#core-nfs").innerHTML = `<tr><th>Função</th><th class="num">CPU</th><th class="num">Memória</th><th class="num">Threads</th>
      <th class="num">PID</th><th class="num">Erros / avisos</th></tr>` + nfs.map((x) => {
        const info = NF_INFO[x.nf] || [x.nf.toUpperCase(), ""];
        const e = ce(x.nf, "error"), w = ce(x.nf, "warning");
        return `<tr><td><b>${esc(info[0])}</b> <span class="muted">${esc(info[1])}</span></td><td class="num">${fmt(x.cpu, 1)}%</td>
          <td class="num">${fmtBytes(x.rss)}</td><td class="num">${esc(x.threads)}</td><td class="num muted">${esc(x.pids.join(", "))}</td>
          <td class="num">${e == null && w == null ? '<span class="muted">–</span>'
            : `<span class="tag ${e ? "err" : "ok"}">${e || 0}</span> <span class="tag ${w ? "warn" : "ok"}">${w || 0}</span>`}</td></tr>`;
      }).join("");
    $("#core-ifaces").innerHTML = `<tr><th>Interface</th><th>Papel</th><th class="num">rx</th><th class="num">tx</th><th class="num">Total rx / tx</th></tr>` +
      ifs.map((x) => `<tr><td><code>${esc(x.iface)}</code></td><td class="muted">${esc(x.role)}</td>
        <td class="num">${fmtRate(x.rx_bps)}</td><td class="num">${fmtRate(x.tx_bps)}</td>
        <td class="num">${fmtBytes(x.rx_bytes)} / ${fmtBytes(x.tx_bytes)}</td></tr>`).join("");
  },
  async refresh() {
    if (this.view === "webui") return;   // a WebUI se atualiza sozinha; não recarregar o iframe
    await this.live();
    const d = await api("api/core/metrics?window=" + $("#core-window").value);
    $("#core-disabled").classList.toggle("hidden", d.enabled || CONFIG.core_kind !== "open5gs");
    $("#core-enabled").classList.toggle("hidden", !d.enabled);
    if (!d.enabled) return;
    const nfs = d.nfs;
    $("#core-status").textContent = "coleta a cada ~5 s · " + Object.entries(nfs).map(([k, v]) => `${k.toUpperCase()}: ${v.error ? "erro" : "ok"}`).join(" · ");
    const L = (nf, name) => {
      const m = nfs[nf] && nfs[nf].latest[name];
      return m ? m.reduce((a, x) => a + x.value, 0) : null;
    };
    const k = [
      { l: "gNBs (AMF)", v: L("amf", "gnb") },
      { l: "UEs no RAN (AMF)", v: L("amf", "ran_ue") },
      { l: "Sessões AMF", v: L("amf", "amf_session") },
      { l: "UEs ativos (SMF)", v: L("smf", "ues_active") },
      { l: "Sessões PDU (SMF)", v: L("smf", "fivegs_smffunction_sm_sessionnbr") },
      { l: "Sessões N4 (UPF)", v: L("upf", "fivegs_upffunction_upf_sessionnbr") },
    ];
    $("#core-kpis").innerHTML = k.map((x) => `<div class="kpi"><div class="label">${esc(x.l)}</div><div class="value">${x.v == null ? "–" : esc(x.v)}</div></div>`).join("");
    // Tráfego do UPF: taxa a partir dos contadores de volume do N3
    const s = (nfs.upf && nfs.upf.series) || { t: [] };
    const rate = (name) => {
      const v = s[name] || [];
      return s.t.map((t, i) => (i && v[i] != null && v[i - 1] != null && t > s.t[i - 1] ? Math.max(0, (v[i] - v[i - 1]) * 8 / (t - s.t[i - 1]) / 1e6) : null));
    };
    Charts.make("c-upf", [{ label: "Uplink (entra no UPF)" }, { label: "Downlink (sai do UPF)", color: "#6b7280" }]);
    Charts.set("c-upf", [s.t, rate("fivegs_ep_n3_gtp_indatavolumeqosleveln3upf"), rate("fivegs_ep_n3_gtp_outdatavolumeqosleveln3upf")]);
    const ss = (nf) => (nfs[nf] && nfs[nf].series) || { t: [] };
    Charts.make("c-core-counts", [{ label: "ran_ue (AMF)", dec: 0 }, { label: "sessões (SMF)", color: "#6b7280", dec: 0 }, { label: "sessões N4 (UPF)", color: "#0ea5e9", dec: 0 }]);
    const a = align([ss("amf"), ss("smf"), ss("upf")], "ran_ue");
    const b = align([ss("amf"), ss("smf"), ss("upf")], "fivegs_smffunction_sm_sessionnbr");
    const c = align([ss("amf"), ss("smf"), ss("upf")], "fivegs_upffunction_upf_sessionnbr");
    Charts.set("c-core-counts", [a[0], a[1], b[2], c[3]]);
    // tabela
    const f = ($("#core-filter").value || "").toLowerCase();
    const rows = [];
    for (const [nf, v] of Object.entries(nfs)) {
      if (v.error) rows.push(`<tr><td>${nf.toUpperCase()}</td><td colspan="3" class="muted">${esc(v.error)}</td></tr>`);
      for (const [name, vals] of Object.entries(v.latest)) {
        if (f && !(nf + " " + name).toLowerCase().includes(f)) continue;
        for (const x of vals) rows.push(`<tr><td>${nf.toUpperCase()}</td><td>${esc(name)}</td><td class="muted">${esc(x.labels)}</td><td class="num">${esc(x.value)}</td></tr>`);
      }
    }
    $("#core-table").innerHTML = `<tr><th>NF</th><th>Métrica</th><th>Rótulos</th><th class="num">Valor</th></tr>` + rows.join("");
  },
};
$("#core-window").addEventListener("change", () => Core.refresh());
$("#core-filter").addEventListener("input", () => Core.refresh());

// ---------------------------------------------------------------------------
//  Início
// ---------------------------------------------------------------------------
(async function init() {
  applyTheme(store.get("theme", null));
  $("#ran-window").value = store.get("ran.window", "300");
  if (store.get("logs.wrap", false)) { $("#log-wrap").checked = true; $("#log-view").classList.add("wrap"); }
  try {
    await reloadConfig(true);
  } catch (e) { banner("Falha ao carregar a configuração: " + e.message); }
  const start = (location.hash || "").slice(1) || store.get("tab", "overview");
  showTab(["overview", "ran", "logs", "core", "ru", "control", "hosts", "history", "docs", "settings"].includes(start) ? start : "overview");
  setInterval(refreshNow, 2000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshNow(); });
})();
// Configuração do painel; recarregada quando o core ativo muda (os textos e a WebUI acompanham)
async function reloadConfig(first = false) {
  if (reloadConfig._busy) return;
  reloadConfig._busy = true;
  try {
    const prev = CONFIG.core;
    CONFIG = await api("api/config");
    $("#tabbtn-settings").classList.toggle("hidden", !CONFIG.config_edit);
    $("#core-seg-webui").classList.toggle("hidden", !CONFIG.webui_port);
    $("#rec").classList.toggle("hidden", !CONFIG.persist);
    $("#tabbtn-ru").classList.toggle("hidden", !CONFIG.ru);
    $("#tabbtn-control").classList.toggle("hidden", !CONFIG.control);
    document.body.classList.toggle("no-ru", !CONFIG.ru);
    paintCore();
    if (first) {
      Hist.refreshHeader();
      if (CONFIG.webui_port && store.get("core.view", "metrics") === "webui") Core.setView("webui");
    } else if (prev && prev !== CONFIG.core) {
      // outro core: a WebUI/WebConsole e a fonte de log mudam
      $("#webui-frame").removeAttribute("src");
      if (!CONFIG.webui_port) Core.setView("metrics");
      else if (Core.view === "webui") $("#webui-frame").src = Core.webuiUrl();
      if (Logs.src && Logs.src.kind === "pod") { Logs.stop(); Logs.src = null; store.set("logs.src", null); if (currentTab === "logs") Logs.ensureSources(); }
    }
    $("#netname").textContent = CONFIG.network_name ? "· " + CONFIG.network_name : "";
    $("#footer").textContent = `Innova Center Dashboard v${CONFIG.version || "?"} · InnovaNetwork · core ativo: ${CONFIG.core_name} (namespace ${CONFIG.namespace}) · histórico em memória: ${Math.round(CONFIG.history_seconds / 60)} min · gNB: ${CONFIG.gnb_url || "desligado"}`;
  } finally { reloadConfig._busy = false; }
}
$("#ran-old").addEventListener("click", () => { Ran.showOld = !Ran.showOld; Ran.refresh(); });
$$("#core-seg [data-view]").forEach((b) => b.addEventListener("click", () => Core.setView(b.dataset.view)));
$("#webui-reload").addEventListener("click", () => { $("#webui-frame").src = Core.webuiUrl(); });
