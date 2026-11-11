/* Innova Center Dashboard — RU tab (LiteOn FlexFi O-RU, read through the management port).
   Uses the utilities of app.js ($, esc, fmt, fmtRate, ago, api, Charts, cols) and hosts.js (fmtUptime). */
"use strict";

const RU_GOOD = new Set(["Ready", "SYNCHRONIZED"]);
const ruTag = (v) => `<span class="tag ${v == null ? "" : RU_GOOD.has(v) ? "ok" : "err"}">${esc(v ?? "?")}</span>`;
const ruLvl = (v) => (v == null ? "" : RU_GOOD.has(v) ? "ok" : "err");

// "3749700000" -> "3749.70 MHz"; "100000000" -> "100 MHz"
function ruMHz(v, dec = 0) {
  const n = Number(v);
  return isFinite(n) && n > 0 ? fmt(n / 1e6, dec) + " MHz" : v ?? "–";
}
// NR-ARFCN from the frequency (3–24.25 GHz range: 600000 + (F − 3000 MHz)/15 kHz)
function ruArfcn(hz) {
  const f = Number(hz) / 1e3;   // kHz
  if (!isFinite(f) || f <= 0) return null;
  if (f < 3e6) return Math.round(f / 5);
  if (f < 24250e3) return Math.round(600000 + (f - 3e6) / 15);
  return null;
}
const RU_SCS = { 0: "15 kHz", 1: "30 kHz", 2: "60 kHz", 3: "120 kHz" };
const RU_COMP = { 0: "16 bits (no compression)", 8: "8 bits BFP", 9: "9 bits BFP", 12: "12 bits BFP", 14: "14 bits BFP" };

const RuTab = {
  async refresh() {
    const d = await api("api/ru?window=" + $("#ru-window").value);
    if (!d.enabled) { $("#ru-sub").textContent = "RU tab disabled (RU_MGMT_IP empty in config.env)"; return; }
    const l = d.last || {};
    const info = d.info || {};
    const c = info.config || {};
    $("#ru-title").textContent = d.name || "RU";
    $("#ru-sub").innerHTML = [
      info.model ? esc(info.model) : "", info.firmware ? "firmware " + esc(info.firmware) : "",
      d.addr ? "management " + esc(d.addr) : "",
      d.online ? `updated ${ago(Date.now() / 1000 - d.age)} ago`
        : `<span class="tag err">no data</span>${d.error ? " " + esc(d.error) : ""}`,
    ].filter(Boolean).join(" · ");

    // state (what the RU shows in "show oru-status")
    const st = [
      { l: "Sync (PTP)", v: d.sync, s: l.sync && l.sync.state ? "trace: " + l.sync.state : "clock from the grandmaster" },
      { l: "RF", v: d.rf, s: "radio chain" },
      { l: "DPD", v: d.dpd, s: "digital pre-distortion" },
      { l: "DU connected", v: d.du, s: d.du === "Ready" ? "fronthaul with OCUDU" : "gNB stopped or no fronthaul" },
    ];
    $("#ru-state").innerHTML = st.map((x, i) => `<div class="kpi ${i === 3 && x.v && !RU_GOOD.has(x.v) ? "warn" : ruLvl(x.v)}"><div class="label">${esc(x.l)}</div>
      <div class="value small">${esc(x.v ?? "–")}</div><div class="sub">${esc(x.s)}</div></div>`).join("");

    const pm = l.pm || {};
    const P = (pm.POWER || {}).radio || {}, T = (pm.TEMPERATURE || {}).radio || {}, Tc = (pm.TEMPERATURE || {}).cpu || {};
    const rfDbm = parseFloat(c["TX power"]), rfAnt = parseInt(info.layers, 10) || 4;
    const rfW = isFinite(rfDbm) ? rfAnt * Math.pow(10, rfDbm / 10) / 1000 : null;   // dBm per antenna -> W in total
    const tot = (pm.RX_TOTAL || {}).count, late = (pm.RX_LATE || {}).count, early = (pm.RX_EARLY || {}).count;
    const k = [
      // POWER (O-RAN PM counter) is the electrical power the RU draws; the radiated RF is far lower
      { l: "Power consumption", v: P.avg != null ? fmt(P.avg, 1) + " W" : "–", s: P.min != null ? `${fmt(P.min, 1)}–${fmt(P.max, 1)} W in the window` : "" },
      { l: "RF radiated", v: rfW != null ? fmt(rfW, 2) + " W" : "–", s: rfW != null ? `${fmt(rfDbm, 0)} dBm × ${rfAnt} antennas` : "" },
      { l: "Radio temperature", v: T.avg != null ? fmt(T.avg, 0) + " °C" : "–", s: T.max != null ? `max ${fmt(T.max, 0)} °C` : "",
        c: lvl(T.max, 70, 80) },
      { l: "CPU temperature", v: Tc.avg != null ? fmt(Tc.avg, 0) + " °C" : "–", s: "RU processor", c: lvl(Tc.max, 75, 85) },
      { l: "U-plane packets received", v: tot != null ? fmt(tot, 0) : "–", s: "in the last PM window" },
      { l: "Outside the window", v: tot ? fmt(100 * ((late || 0) + (early || 0)) / tot, 3) + "%" : "–",
        s: `${fmt(early || 0, 0)} early · ${fmt(late || 0, 0)} late`, c: tot && (late || early) ? "warn" : "" },
      { l: "Up for", v: fmtUptime(l.uptime), s: l.load ? "load " + l.load.map((x) => x.toFixed(2)).join(" / ") : "" },
    ];
    $("#ru-kpis").innerHTML = k.map((x) => `<div class="kpi ${x.c || ""}"><div class="label">${esc(x.l)}</div>
      <div class="value">${esc(x.v)}</div><div class="sub">${esc(x.s)}</div></div>`).join("");

    // charts
    const s = d.series || { t: [] };
    Charts.make("c-ru-pt", [{ label: "Power consumption W", fill: true }, { label: "Radio temp. °C", color: "#6b7280", scale: "y2", dec: 0 },
      { label: "Temp. CPU °C", color: "#9ca3af", scale: "y2", dec: 0, dash: [4, 3] }], { y2: true });
    Charts.set("c-ru-pt", cols(s, ["power", "temp", "temp_cpu"]));
    Charts.make("c-ru-fh", [{ label: "Received", fill: true, dec: 0 }, { label: "Early", color: "#d97706", dec: 0 },
      { label: "Late", color: "#dc2626", dec: 0 }, { label: "Sent (TX)", color: "#6b7280", dec: 0, dash: [4, 3] }]);
    Charts.set("c-ru-fh", cols(s, ["rx_total", "rx_early", "rx_late", "tx_total"]));
    const ifs = Object.keys(l.eth || {});
    const mb = (v) => fmt(v, 3);
    Charts.make("c-ru-net", ifs.flatMap((n, i) => [{ label: n + " RX", color: colorFor(i * 2), fmt: mb }, { label: n + " TX", color: colorFor(i * 2 + 1), fmt: mb, dash: [4, 3] }]));
    Charts.set("c-ru-net", cols(s, ifs.flatMap((n) => ["rx:" + n, "tx:" + n])));

    // radio configuration
    const arfcn = ruArfcn(c["Center Frequency"]);
    const cfg = [
      ["Center frequency", c["Center Frequency"] ? ruMHz(c["Center Frequency"], 2) + (arfcn ? ` (NR-ARFCN ${arfcn})` : "") : "–"],
      ["Bandwidth", ruMHz(c["Band Width"])],
      ["Subcarrier spacing", RU_SCS[c["subcarrier spacing"]] || c["subcarrier spacing"] || "–"],
      ["Antennas", info.layers || "–"],
      ["TX power per antenna", c["TX power"] ? c["TX power"] + " dBm" : "–"],
      ["RX gain", c["RX gain"] ? c["RX gain"] + " dB" : "–"],
      ["IQ compression (U-plane)", RU_COMP[c["Compression Bit"]] || c["Compression Bit"] || "–"],
      ["Sync source", c["sync source"] || "–"],
      ["DPD / phase compensation", `${c["dpd mode"] || "?"} / ${c["phase compensation mode"] || "?"}`],
      ["C/U-plane VLAN", c["Control and User Plane vlan"] || "–"],
      ["Expected DU MAC", c["DU MAC Address"] ? c["DU MAC Address"].replace(/(..)(?!$)/g, "$1:") : "–"],
      ["Jumbo frame", c.jumboframe ? (Number(c.jumboframe) ? "on (MTU 9600)" : "off") : "–"],
    ];
    $("#ru-cfg").innerHTML = cfg.map(([a, b]) => `<tr><td>${esc(a)}</td><td class="num"><b>${esc(b)}</b></td></tr>`).join("");
    $("#ru-cfg-raw").innerHTML = `<tr><th>Parameter (show running-config)</th><th class="num">Value</th></tr>` +
      Object.entries(c).map(([a, b]) => `<tr><td>${esc(a)}</td><td class="num">${esc(b)}</td></tr>`).join("");

    // interfaces
    $("#ru-eth").innerHTML = `<tr><th>Interface</th><th>Address</th><th>MAC</th><th class="num">Receiving</th><th class="num">Sending</th><th class="num">Errors/drops</th></tr>` +
      ifs.map((n) => { const e = l.eth[n]; return `<tr><td><b>${esc(n)}</b> <span class="muted">${n === "eth0" ? "RJ45 (management)" : n === "eth1" ? "SFP+ (management, no VLAN)" : ""}</span></td>
        <td>${esc(e.ip || "–")}${e.mask ? `<span class="muted"> / ${esc(e.mask)}</span>` : ""}</td><td class="muted">${esc(e.mac || "")}</td>
        <td class="num">${e.rx_bps != null ? fmtRate(e.rx_bps) : "–"}</td><td class="num">${e.tx_bps != null ? fmtRate(e.tx_bps) : "–"}</td>
        <td class="num">${(e.rx_err || 0) + (e.tx_err || 0) ? `<span class="tag warn">${(e.rx_err || 0) + (e.tx_err || 0)}</span>` : 0}</td></tr>`; }).join("");

    // events (state changes seen by the dashboard)
    const ev = d.events || [];
    $("#ru-events").innerHTML = ev.length ? ev.map((e) => `<div class="ev ${esc(e.level)}">
      <span class="t">${hhmmss(e.ts)}</span><span class="src">ru</span><span class="msg">${esc(e.msg)}</span><span class="cnt"></span></div>`).join("")
      : `<div class="empty">No state changes since the dashboard started.</div>`;
    $("#ru-system").textContent = info.system || "";
  },
};
$("#ru-window").addEventListener("change", () => RuTab.refresh());
