/* Innova Center Dashboard — Slices tab (sessions, UPF traffic and refused requests per network slice).
   Uses the utilities of app.js ($, esc, fmt, fmtRate, api, Charts, colorFor) and hosts.js (fmtBytes). */
"use strict";

const sliceName = (s) => `SST ${s.sst}${s.sd ? " · SD " + s.sd : ""}`;
const mbit = (arr) => (arr || []).map((v) => (v == null ? null : v * 1e-6));

const Slices = {
  async refresh() {
    const d = await api("api/slices?window=" + $("#sl-window").value);
    const sl = d.slices || [];
    const parts = [esc(d.core_label), `${sl.length} slice(s)`,
      d.source === "core" ? "read from the running core" : "from config.env (core configuration not readable: reinstall the dashboard)"];
    if (d.upf_shared) parts.push("this core uses one UPF device for every DNN: traffic per slice is not available");
    $("#sl-sub").innerHTML = parts.map((x) => `<span>${x}</span>`).join(" · ");
    $("#sl-sub").title = d.source_error || "";
    if (!sl.length) {
      $("#sl-kpis").innerHTML = '<div class="muted">No slices found in the core configuration.</div>';
      return;
    }

    // one card per slice: sessions and current UPF traffic (share of the total)
    const tot = sl.reduce((a, s) => a + (s.dl_bps || 0) + (s.ul_bps || 0), 0);
    $("#sl-kpis").innerHTML = sl.map((s, i) => {
      const share = tot ? (100 * ((s.dl_bps || 0) + (s.ul_bps || 0)) / tot) : null;
      const nses = `<span>${s.sessions}</span> <span>session(s)</span>`;
      const sub = d.upf_shared ? `${nses} · ${esc(s.cidr)}`
        : `↑ ${fmtRate(s.ul_bps)} · ${nses} · ${share == null ? "<span>no traffic</span>" : fmt(share, 0) + "% <span>of the traffic</span>"}`;
      return `<div class="kpi" style="border-top:3px solid ${colorFor(i)}">
        <div class="label">${esc(s.dnn)} · ${esc(sliceName(s))}</div>
        <div class="value">${d.upf_shared ? s.sessions : "↓ " + fmtRate(s.dl_bps)}</div>
        <div class="sub">${sub}</div>
        <div class="bar" style="margin-top:6px"><i style="width:${share == null ? 0 : share.toFixed(0)}%;background:${colorFor(i)}"></i></div>
        <div class="sub">${s.upf_iface ? "UPF " + esc(s.upf_iface) : ""}${s.dl_bytes != null ? " · total ↓ " + fmtBytes(s.dl_bytes) + " ↑ " + fmtBytes(s.ul_bytes) : ""}</div>
      </div>`;
    }).join("");

    // charts: one line per slice
    const t = (sl[0].series || {}).t || [];
    for (const dir of ["dl", "ul"]) {
      Charts.make("c-sl-" + dir, sl.map((s, i) => ({ label: s.dnn, color: colorFor(i), fill: i === 0 })));
      Charts.set("c-sl-" + dir, d.upf_shared ? [[], ...sl.map(() => [])] : [t, ...sl.map((s) => mbit(s.series[dir]))]);
    }

    // matrix UE x slice
    const ues = {};
    sl.forEach((s, i) => s.ues.forEach((u) => {
      const e = ues[u.imsi] || (ues[u.imsi] = { ...u, cells: {} });
      e.cells[i] = u;
    }));
    const list = Object.values(ues).sort((a, b) => (a.kind === b.kind ? a.imsi.localeCompare(b.imsi) : a.kind === "real" ? -1 : 1));
    const head = `<tr><th>UE</th><th>Type</th>${sl.map((s, i) => `<th style="border-bottom:2px solid ${colorFor(i)}">${esc(s.dnn)}<br><span class="muted">${esc(sliceName(s))}</span></th>`).join("")}<th class="num">Radio ↓ / ↑</th></tr>`;
    const rows = list.map((u) => {
      const n = Object.keys(u.cells).length;
      const name = u.name ? `${esc(u.name)} <span class="muted">…${esc(u.imsi.slice(-4))}</span>` : `IMSI ${esc(u.imsi)}`;
      const kind = u.kind === "ueransim" ? '<span class="tag">UERANSIM</span>' : '<span class="tag real">real SIM</span>';
      const cells = sl.map((s, i) => {
        const c = u.cells[i];
        if (!c) return '<td class="muted">–</td>';
        const warn = c.slice_mismatch ? ' <span class="tag warn" title="the AMF log shows another S-NSSAI for this DNN">other S-NSSAI</span>' : "";
        const dnn = s.dnns && s.dnns.length > 1 ? ` <span class="muted">${esc(c.dnn)}</span>` : "";
        return `<td><span class="tag ok">✓</span> ${esc(c.ipv4 || "")}${dnn}${warn}</td>`;
      }).join("");
      const radio = u.on_radio ? `${fmtRate(u.radio_dl)} / ${fmtRate(u.radio_ul)}${n > 1 ? ' <span class="tag" title="the radio rate is per UE: it is split between its slices">shared</span>' : ""}`
        : '<span class="muted">' + (u.kind === "ueransim" ? "simulated (no gNB radio)" : "not on the radio") + "</span>";
      return `<tr><td>${name}${n > 1 ? ` <span class="tag warn">${n} slices</span>` : ""}</td><td>${kind}</td>${cells}<td class="num">${radio}</td></tr>`;
    });
    $("#sl-matrix").innerHTML = head + (rows.join("") || `<tr><td colspan="${sl.length + 3}" class="muted">No PDU sessions.</td></tr>`);

    // refused requests: per configured slice, then other DNNs (e.g. phones asking for "ims")
    const ref = sl.filter((s) => s.rejected).map((s) => `<li><b>${s.rejected}</b> for ${esc(s.dnn)} (${esc(sliceName(s))})</li>`);
    for (const r of d.refused_other || []) {
      const s = sl.find((x) => x.key === r.slice);
      ref.push(`<li><b>${r.count}</b> for DNN <code>${esc(r.dnn)}</code>${s ? " on " + esc(sliceName(s)) : r.slice !== "?" ? " on slice " + esc(r.slice) : ""}` +
        (r.dnn === "ims" ? ' <span class="muted">— phones ask for IMS (voice); it has no pool in the SMF, so it is refused. Harmless.</span>' : "") + "</li>");
    }
    $("#sl-refused").innerHTML = ref.length ? `<ul class="plain">${ref.join("")}</ul><div class="muted" style="font-size:12px">Counted since the AMF pod started.</div>`
      : '<div class="muted">None since the AMF pod started.</div>';
  },
};
$("#sl-window").addEventListener("change", () => Slices.refresh());
