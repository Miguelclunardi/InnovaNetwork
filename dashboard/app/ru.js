/* Innova Center Dashboard — aba RU (O-RU LiteOn FlexFi, lida pela porta de gestão).
   Usa as utilidades de app.js ($, esc, fmt, fmtRate, ago, api, Charts, cols) e de hosts.js (fmtUptime). */
"use strict";

const RU_GOOD = new Set(["Ready", "SYNCHRONIZED"]);
const ruTag = (v) => `<span class="tag ${v == null ? "" : RU_GOOD.has(v) ? "ok" : "err"}">${esc(v ?? "?")}</span>`;
const ruLvl = (v) => (v == null ? "" : RU_GOOD.has(v) ? "ok" : "err");

// "3749700000" -> "3749,70 MHz"; "100000000" -> "100 MHz"
function ruMHz(v, dec = 0) {
  const n = Number(v);
  return isFinite(n) && n > 0 ? fmt(n / 1e6, dec) + " MHz" : v ?? "–";
}
// NR-ARFCN a partir da frequência (faixa 3–24,25 GHz: 600000 + (F − 3000 MHz)/15 kHz)
function ruArfcn(hz) {
  const f = Number(hz) / 1e3;   // kHz
  if (!isFinite(f) || f <= 0) return null;
  if (f < 3e6) return Math.round(f / 5);
  if (f < 24250e3) return Math.round(600000 + (f - 3e6) / 15);
  return null;
}
const RU_SCS = { 0: "15 kHz", 1: "30 kHz", 2: "60 kHz", 3: "120 kHz" };
const RU_COMP = { 0: "16 bits (sem compressão)", 8: "8 bits BFP", 9: "9 bits BFP", 12: "12 bits BFP", 14: "14 bits BFP" };

const RuTab = {
  async refresh() {
    const d = await api("api/ru?window=" + $("#ru-window").value);
    if (!d.enabled) { $("#ru-sub").textContent = "aba RU desligada (RU_MGMT_IP vazio no config.env)"; return; }
    const l = d.last || {};
    const info = d.info || {};
    const c = info.config || {};
    $("#ru-title").textContent = d.name || "RU";
    $("#ru-sub").innerHTML = [
      info.model ? esc(info.model) : "", info.firmware ? "firmware " + esc(info.firmware) : "",
      d.addr ? "gestão " + esc(d.addr) : "",
      d.online ? `atualizado há ${ago(Date.now() / 1000 - d.age)}`
        : `<span class="tag err">sem dados</span>${d.error ? " " + esc(d.error) : ""}`,
    ].filter(Boolean).join(" · ");

    // estado (o que a RU mostra no "show oru-status")
    const st = [
      { l: "Sincronismo (PTP)", v: d.sync, s: l.sync && l.sync.state ? "trace: " + l.sync.state : "relógio vindo do grandmaster" },
      { l: "RF", v: d.rf, s: "cadeia de rádio" },
      { l: "DPD", v: d.dpd, s: "pré-distorção digital" },
      { l: "DU conectado", v: d.du, s: d.du === "Ready" ? "fronthaul com o OCUDU" : "gNB parado ou sem fronthaul" },
    ];
    $("#ru-state").innerHTML = st.map((x, i) => `<div class="kpi ${i === 3 && x.v && !RU_GOOD.has(x.v) ? "warn" : ruLvl(x.v)}"><div class="label">${esc(x.l)}</div>
      <div class="value small">${esc(x.v ?? "–")}</div><div class="sub">${esc(x.s)}</div></div>`).join("");

    const pm = l.pm || {};
    const P = (pm.POWER || {}).radio || {}, T = (pm.TEMPERATURE || {}).radio || {}, Tc = (pm.TEMPERATURE || {}).cpu || {};
    const tot = (pm.RX_TOTAL || {}).count, late = (pm.RX_LATE || {}).count, early = (pm.RX_EARLY || {}).count;
    const k = [
      { l: "Potência", v: P.avg != null ? fmt(P.avg, 1) + " W" : "–", s: P.min != null ? `${fmt(P.min, 1)}–${fmt(P.max, 1)} W na janela` : "" },
      { l: "Temperatura do rádio", v: T.avg != null ? fmt(T.avg, 0) + " °C" : "–", s: T.max != null ? `máx. ${fmt(T.max, 0)} °C` : "",
        c: lvl(T.max, 70, 80) },
      { l: "Temperatura da CPU", v: Tc.avg != null ? fmt(Tc.avg, 0) + " °C" : "–", s: "processador da RU", c: lvl(Tc.max, 75, 85) },
      { l: "Pacotes U-plane recebidos", v: tot != null ? fmt(tot, 0) : "–", s: "na última janela do PM" },
      { l: "Fora da janela", v: tot ? fmt(100 * ((late || 0) + (early || 0)) / tot, 3) + "%" : "–",
        s: `${fmt(early || 0, 0)} adiantados · ${fmt(late || 0, 0)} atrasados`, c: tot && (late || early) ? "warn" : "" },
      { l: "Ligada há", v: fmtUptime(l.uptime), s: l.load ? "carga " + l.load.map((x) => x.toFixed(2)).join(" / ") : "" },
    ];
    $("#ru-kpis").innerHTML = k.map((x) => `<div class="kpi ${x.c || ""}"><div class="label">${esc(x.l)}</div>
      <div class="value">${esc(x.v)}</div><div class="sub">${esc(x.s)}</div></div>`).join("");

    // gráficos
    const s = d.series || { t: [] };
    Charts.make("c-ru-pt", [{ label: "Potência W", fill: true }, { label: "Temp. rádio °C", color: "#6b7280", scale: "y2", dec: 0 },
      { label: "Temp. CPU °C", color: "#9ca3af", scale: "y2", dec: 0, dash: [4, 3] }], { y2: true });
    Charts.set("c-ru-pt", cols(s, ["power", "temp", "temp_cpu"]));
    Charts.make("c-ru-fh", [{ label: "Recebidos", fill: true, dec: 0 }, { label: "Adiantados", color: "#d97706", dec: 0 },
      { label: "Atrasados", color: "#dc2626", dec: 0 }, { label: "Enviados (TX)", color: "#6b7280", dec: 0, dash: [4, 3] }]);
    Charts.set("c-ru-fh", cols(s, ["rx_total", "rx_early", "rx_late", "tx_total"]));
    const ifs = Object.keys(l.eth || {});
    const mb = (v) => fmt(v, 3);
    Charts.make("c-ru-net", ifs.flatMap((n, i) => [{ label: n + " RX", color: colorFor(i * 2), fmt: mb }, { label: n + " TX", color: colorFor(i * 2 + 1), fmt: mb, dash: [4, 3] }]));
    Charts.set("c-ru-net", cols(s, ifs.flatMap((n) => ["rx:" + n, "tx:" + n])));

    // configuração de rádio
    const arfcn = ruArfcn(c["Center Frequency"]);
    const cfg = [
      ["Frequência central", c["Center Frequency"] ? ruMHz(c["Center Frequency"], 2) + (arfcn ? ` (NR-ARFCN ${arfcn})` : "") : "–"],
      ["Largura de banda", ruMHz(c["Band Width"])],
      ["Espaçamento de subportadora", RU_SCS[c["subcarrier spacing"]] || c["subcarrier spacing"] || "–"],
      ["Antenas", info.layers || "–"],
      ["Potência TX por antena", c["TX power"] ? c["TX power"] + " dBm" : "–"],
      ["Ganho RX", c["RX gain"] ? c["RX gain"] + " dB" : "–"],
      ["Compressão IQ (U-plane)", RU_COMP[c["Compression Bit"]] || c["Compression Bit"] || "–"],
      ["Fonte de sincronismo", c["sync source"] || "–"],
      ["DPD / compensação de fase", `${c["dpd mode"] || "?"} / ${c["phase compensation mode"] || "?"}`],
      ["VLAN do C/U-plane", c["Control and User Plane vlan"] || "–"],
      ["MAC do DU esperado", c["DU MAC Address"] ? c["DU MAC Address"].replace(/(..)(?!$)/g, "$1:") : "–"],
      ["Jumbo frame", c.jumboframe ? (Number(c.jumboframe) ? "ligado (MTU 9600)" : "desligado") : "–"],
    ];
    $("#ru-cfg").innerHTML = cfg.map(([a, b]) => `<tr><td>${esc(a)}</td><td class="num"><b>${esc(b)}</b></td></tr>`).join("");
    $("#ru-cfg-raw").innerHTML = `<tr><th>Parâmetro (show running-config)</th><th class="num">Valor</th></tr>` +
      Object.entries(c).map(([a, b]) => `<tr><td>${esc(a)}</td><td class="num">${esc(b)}</td></tr>`).join("");

    // interfaces
    $("#ru-eth").innerHTML = `<tr><th>Interface</th><th>Endereço</th><th>MAC</th><th class="num">Recebendo</th><th class="num">Enviando</th><th class="num">Erros/descartes</th></tr>` +
      ifs.map((n) => { const e = l.eth[n]; return `<tr><td><b>${esc(n)}</b> <span class="muted">${n === "eth0" ? "RJ45 (gestão)" : n === "eth1" ? "SFP+ (gestão sem VLAN)" : ""}</span></td>
        <td>${esc(e.ip || "–")}${e.mask ? `<span class="muted"> / ${esc(e.mask)}</span>` : ""}</td><td class="muted">${esc(e.mac || "")}</td>
        <td class="num">${e.rx_bps != null ? fmtRate(e.rx_bps) : "–"}</td><td class="num">${e.tx_bps != null ? fmtRate(e.tx_bps) : "–"}</td>
        <td class="num">${(e.rx_err || 0) + (e.tx_err || 0) ? `<span class="tag warn">${(e.rx_err || 0) + (e.tx_err || 0)}</span>` : 0}</td></tr>`; }).join("");

    // eventos (mudanças de estado vistas pelo painel)
    const ev = d.events || [];
    $("#ru-events").innerHTML = ev.length ? ev.map((e) => `<div class="ev ${esc(e.level)}">
      <span class="t">${hhmmss(e.ts)}</span><span class="src">ru</span><span class="msg">${esc(e.msg)}</span><span class="cnt"></span></div>`).join("")
      : `<div class="empty">Sem mudanças de estado desde que o painel iniciou.</div>`;
    $("#ru-system").textContent = info.system || "";
  },
};
$("#ru-window").addEventListener("change", () => RuTab.refresh());
