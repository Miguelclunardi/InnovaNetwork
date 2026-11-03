/* Innova Center Dashboard — Control tab (start/stop/restart the core, UERANSIM and the OCUDU gNB).
   Uses the administrator session of the Settings tab (Settings.token) and the utilities of app.js. */
"use strict";

const Control = {
  data: null,
  cfgSel: (() => { try { return localStorage.getItem("icd.ocudu.cfg") || ""; } catch { return ""; } })(),
  showAll: false,

  async refresh() {
    try {
      this.data = await api("api/control");
    } catch (e) { $("#ctl-error").textContent = e.message; $("#ctl-error").classList.remove("hidden"); return; }
    $("#ctl-error").classList.toggle("hidden", !this.data.error);
    $("#ctl-error").textContent = this.data.error ? "Kubernetes: " + this.data.error : "";
    const logged = !!Settings.token;
    $("#ctl-login").classList.toggle("hidden", logged);
    $("#ctl-logged").classList.toggle("hidden", !logged);
    const busy = this.data.job && this.data.job.state === "running";
    this.renderCores(busy, logged);
    this.renderGroup("core", "#ctl-core", busy, logged);
    this.renderGroup("ueransim", "#ctl-ueransim", busy, logged);
    this.renderOcudu(busy, logged);
    this.renderJob();
    $$("#tab-control [data-act]").forEach((b) => { b.disabled = !logged || busy; });
  },

  stateTag(c) {
    const cls = { running: "ok", stopped: "", starting: "warn", stopping: "warn" }[c.state] || "";
    const bad = c.pods.find((p) => p.reason && /BackOff|Error|Err/.test(p.reason));
    return `<span class="tag ${bad ? "err" : cls}">${esc(bad ? bad.reason : c.state)}</span>`;
  },

  renderGroup(group, sel, busy, logged) {
    const comps = (this.data.components || []).filter((c) => c.group === group);
    const run = comps.filter((c) => c.state === "running").length;
    $(sel + "-sub").textContent = comps.length ? `${run} of ${comps.length} running` : "no component in the namespace";
    $(sel).innerHTML = `<tr><th>Component</th><th>State</th><th class="num">Restarts</th><th class="num">Up for</th><th class="num">Actions</th></tr>` +
      comps.map((c) => {
        const p = c.pods[0];
        return `<tr title="${esc(c.deployment)}${p ? " · pod " + esc(p.name) : ""}"><td><b>${esc(c.label)}</b></td><td>${this.stateTag(c)}</td>
          <td class="num">${p ? (p.restarts ? `<span class="tag warn">${p.restarts}</span>` : 0) : "–"}</td>
          <td class="num">${p && p.since ? ago(p.since) : "–"}</td>
          <td class="num nowrap">
            <button class="btn small" data-act="start" data-target="${esc(c.key)}" title="Start">▶</button>
            <button class="btn small" data-act="restart" data-target="${esc(c.key)}" title="Restart (recreates the pod)">↻</button>
            <button class="btn small danger" data-act="stop" data-target="${esc(c.key)}" title="Stop">■</button></td></tr>`;
      }).join("");
  },

  // ---- active core (Open5GS / free5GC): switch in order, restarting the OCUDU gNB
  switchTo: null,
  renderCores(busy, logged) {
    const cores = (CONFIG.cores || []).filter((c) => c.installed);
    const card = $("#ctl-corecard");
    card.classList.toggle("hidden", cores.length < 2);
    if (cores.length < 2) return;
    const active = this.data.core || CONFIG.core;
    $("#ctl-core-seg").innerHTML = cores.map((c) => `<button class="btn ${c.name === active ? "on" : ""}" data-core="${esc(c.name)}"
      ${!logged || busy ? "disabled" : ""} title="${c.name === active ? "active core" : "switch to " + esc(c.label)}">${esc(c.label)}${c.running ? "" : " (stopped)"}</button>`).join("");
    const a = cores.find((c) => c.name === active) || {};
    $("#ctl-core-info").textContent = `${a.label}: AMF ${a.amf_ip || "?"} · UPF ${a.upf_ip || "?"} · namespace ${a.namespace}` +
      (a.running ? "" : " · stopped (start it with ▶ Start all)");
    const box = $("#ctl-switch");
    box.classList.toggle("hidden", !this.switchTo);
    if (!this.switchTo) return;
    const to = cores.find((c) => c.name === this.switchTo);
    if (!to) { this.switchTo = null; box.classList.add("hidden"); return; }
    const st = (this.data.ocudu && this.data.ocudu.status) || {};
    const cfgs = (st.configs || []).filter((c) => c.gnb);
    const match = cfgs.filter((c) => c.amf === to.amf_ip);
    $("#ctl-switch-text").innerHTML = `Switch the active core from <b>${esc(a.label)}</b> to <b>${esc(to.label)}</b>: stops ${esc(a.label)} and its
      UERANSIM, brings ${esc(to.label)} up in order (AMF ${esc(to.amf_ip)}) and checks each step.` +
      (st.active ? ` The OCUDU gNB is running with <code>${esc(st.active.config)}.yml</code>.` : "");
    const sel = $("#ctl-switch-cfg");
    if (document.activeElement !== sel) {
      const cur = sel.value && match.some((c) => c.name === sel.value) ? sel.value : (match[0] || {}).name;
      sel.innerHTML = match.length ? match.map((c) => `<option value="${esc(c.name)}" ${c.name === cur ? "selected" : ""}>${esc(c.name)}.yml — AMF ${esc(c.amf)}</option>`).join("")
        : `<option value="">no .yml points to AMF ${esc(to.amf_ip)}</option>`;
    }
    const gnbOk = !!this.data.ocudu && match.length > 0;
    const chk = $("#ctl-switch-gnb");
    chk.disabled = !gnbOk;
    if (!gnbOk) chk.checked = false;
    else if (!this._gnbTouched) chk.checked = !!st.active;
    sel.disabled = !gnbOk || !chk.checked;
    $("#ctl-switch-go").disabled = !logged || busy;
  },

  async doSwitch() {
    const to = this.switchTo;
    const gnb = $("#ctl-switch-gnb").checked;
    const config = gnb ? $("#ctl-switch-cfg").value : "";
    if (gnb && !config) return alert("Choose the gNB file (or untick restarting the gNB).");
    try {
      await Settings.call("POST", "api/control", { action: "switch", core: to, gnb, config });
      this.switchTo = null;
      this._gnbTouched = false;
    } catch (e) { alert(e.message); }
    this.refresh();
  },

  renderOcudu(busy, logged) {
    const box = $("#ctl-ocudu-card");
    const o = this.data.ocudu;
    box.classList.toggle("hidden", !o);
    if (!o) return;
    const s = o.status || {};
    $("#ctl-ocudu-sub").innerHTML = `${esc(o.target)} · ` + (o.online
      ? (s.error ? `<span class="tag err">no SSH</span> ${esc(s.error)}` : `updated ${ago(Date.now() / 1000 - o.age)} ago`)
      : '<span class="tag err">agent not reachable</span> (journalctl -u open5gs-k3s-gnb-ctl on the core machine)');
    const a = s.active, f = s.failed;
    const k8s = s.mode === "k8s", kw = (s.k8s || {}).waiting_boot;
    $("#ctl-ocudu-jlabel").textContent = k8s ? "Pod output (kubectl logs)" : "Service output (journal)";
    $("#ctl-ocudu-how").innerHTML = k8s
      ? "gNB on Kubernetes: the button starts the <code>ocudu-gnb</code> pod (namespace ocudu) on the radio node with the chosen <code>.yml</code>. After a node reboot the gNB does not start by itself: wait for the GPS, check PTP/RU and click Start."
      : "The machine must already be prepared (interface, DPDK VF, XDP, PTP): the button only runs <code>taskset … ./gnb -c configs/&lt;file&gt;.yml</code> as a service. Stop = Ctrl+C on the gNB.";
    const setup = s.unit_installed === false || s.polkit === false;
    $("#ctl-ocudu-setup").classList.toggle("hidden", !setup);
    const ptp = s.ptp || {};
    const nics = s.nics || {};
    const k = [
      { l: k8s ? "gNB (Kubernetes)" : "gNB", v: a ? (a.sub === "running" ? "running" : a.sub === "activating" ? "starting" : a.sub) : (s.manual || []).length ? "running outside the dashboard" : kw ? "stopped (node rebooted)" : "stopped",
        s: a ? `${a.config}.yml · PID ${a.pid || "–"}` : (s.manual || []).length ? `PID ${(s.manual || []).map((m) => m.pid).join(", ")} (stop it in the terminal)` : f ? `failed: ${f.sub || ""} (${f.config})` : kw ? "check GPS/RU and click Start" : "",
        c: a && a.sub === "running" ? "ok" : (s.manual || []).length || kw ? "warn" : f ? "err" : "" },
      { l: "Up since", v: a && a.since ? a.since.replace(/^\w+ /, "").replace(/ [A-Z-]+\d*$/, "") : "–", s: "" },
      (() => { const g = gpsInfo(s.gps, s.ptp); return { l: "GPS (ts2phc)", v: g.v, s: g.s, c: g.c }; })(),
      { l: "PTP (ptp4l / ts2phc / phc2sys)", v: ["ptp4l-gm", "ts2phc", "phc2sys"].map((x) => ptp[x] === "active" ? "✓" : "✗").join(" "),
        s: Object.values(ptp).every((x) => x === "active") ? "all active" : "a PTP service is stopped", c: Object.values(ptp).every((x) => x === "active") ? "ok" : "err" },
      { l: "Fronthaul (VF DPDK)", v: Object.entries(nics).filter(([, d]) => d).map(([n, d]) => d === "vfio-pci" ? "✓ vfio" : d).join(" ") || "–",
        s: Object.keys(nics).filter((n) => nics[n]).join(", "), c: Object.values(nics).includes("vfio-pci") ? "ok" : "warn" },
    ];
    $("#ctl-ocudu-kpis").innerHTML = k.map((x) => `<div class="kpi ${x.c || ""}"><div class="label">${esc(x.l)}</div>
      <div class="value small">${esc(x.v)}</div><div class="sub">${esc(x.s)}</div></div>`).join("");

    const cfgs = (s.configs || []).filter((c) => this.showAll || c.gnb);
    const cur = this.cfgSel || (a && a.config) || (cfgs.find((c) => c.amf === CONFIG.amf_ip) || {}).name || "";
    const sel = $("#ctl-ocudu-cfg");
    if (document.activeElement !== sel) {
      sel.innerHTML = cfgs.map((c) => `<option value="${esc(c.name)}" ${c.name === cur ? "selected" : ""}>${esc(c.name)}.yml${
        c.amf ? ` — AMF ${esc(c.amf)}${c.amf === CONFIG.amf_ip ? " (this core)" : ""}` : ""}${c.bw ? ` · ${c.bw} MHz` : ""}</option>`).join("");
    }
    const c = (s.configs || []).find((x) => x.name === sel.value) || {};
    $("#ctl-ocudu-cfginfo").innerHTML = c.name ? [
      c.amf ? (c.amf === CONFIG.amf_ip ? '<span class="tag ok">points to this core</span>' : `<span class="tag warn">AMF ${esc(c.amf)}: not this core</span>`) : "",
      c.arfcn ? `ARFCN ${c.arfcn}` : "", c.bw ? `${c.bw} MHz` : "", c.nic ? `fronthaul ${esc(c.nic)}` : "",
      c.mtime ? `changed on ${new Date(c.mtime * 1000).toLocaleString(I18N.locale)}` : "",
    ].filter(Boolean).join(" · ") : "";
    const j = (a || f || {}).journal || [];
    $("#ctl-ocudu-journal").textContent = j.length ? j.join("\n") : "(no service output)";
    $("#ctl-ocudu-manual").classList.toggle("hidden", !(s.manual || []).length);
    $("#ctl-ocudu-manual").innerHTML = (s.manual || []).length ? `There is a <b>gnb running outside the dashboard</b> (${(s.manual || []).map((m) => `PID ${m.pid}: <code>${esc(m.cmd)}</code>`).join("; ")}). The dashboard does not start another while it exists; stop it in the terminal (Ctrl+C).` : "";
  },

  renderJob() {
    const j = this.data.job;
    $("#ctl-job").classList.toggle("hidden", !j);
    if (j) {
      const st = { running: '<span class="tag warn">in progress</span>', ok: '<span class="tag ok">done</span>',
        warn: '<span class="tag warn">done with warnings</span>', error: '<span class="tag err">failed</span>' }[j.state];
      $("#ctl-job-title").innerHTML = `${esc(j.title)} ${st} <span class="muted">${hhmmss(j.t0 * 1000)}${j.t1 ? " – " + hhmmss(j.t1 * 1000) : ""}</span>`;
      const box = $("#ctl-job-log");
      const atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
      box.innerHTML = j.lines.map((l) => `<div class="ev ${l.level === "error" ? "error" : l.level === "warn" ? "warning" : "info"}">
        <span class="t">${hhmmss(l.t * 1000)}</span><span class="src">${l.level === "error" ? "error" : l.level === "warn" ? "warning" : ""}</span><span class="msg">${esc(l.msg)}</span><span class="cnt"></span></div>`).join("");
      if (atEnd) box.scrollTop = box.scrollHeight;
    }
    const r = this.data.recent || [];
    $("#ctl-recent").innerHTML = r.length ? r.map((x) => `<li>${hhmmss(x.t0 * 1000)} · ${esc(x.title)} — ${
      { ok: "done", warn: "with warnings", error: "failed", running: "in progress" }[x.state]}</li>`).join("") : '<li class="muted">none</li>';
  },

  async act(action, target, config) {
    const label = { start: "Start", stop: "Stop", restart: "Restart" }[action];
    const what = ({ all: "core + UERANSIM", core: "the whole core", ueransim: "UERANSIM", ocudu: "the OCUDU gNB" }[target] || target.toUpperCase()) +
      (target === "ocudu" ? "" : ` (${CONFIG.core_name || "core"})`);
    if ((action !== "start" || target === "ocudu") && !confirm(`${label} ${what}?` +
      (action !== "start" && ["core", "all", "amf", "upf", "smf", "ocudu"].includes(target) ? "\n\nAnyone using the network loses the connection." : ""))) return;
    try {
      await Settings.call("POST", "api/control", { action, target, config });
    } catch (e) { alert(e.message); }
    this.refresh();
  },
};

document.addEventListener("click", (e) => {
  const c = e.target.closest("#ctl-core-seg [data-core]");
  if (c) {
    Control.switchTo = c.dataset.core === (Control.data.core || CONFIG.core) ? null : c.dataset.core;
    Control.refresh();
    return;
  }
  const b = e.target.closest("#tab-control [data-act]");
  if (!b) return;
  const t = b.dataset.target;
  Control.act(b.dataset.act, t, t === "ocudu" ? $("#ctl-ocudu-cfg").value : undefined);
});
$("#ctl-ocudu-cfg").addEventListener("change", (e) => {
  Control.cfgSel = e.target.value;
  try { localStorage.setItem("icd.ocudu.cfg", Control.cfgSel); } catch { /* no storage */ }
  Control.refresh();
});
$("#ctl-switch-go").addEventListener("click", () => Control.doSwitch());
$("#ctl-switch-cancel").addEventListener("click", () => { Control.switchTo = null; Control.refresh(); });
$("#ctl-switch-gnb").addEventListener("change", () => { Control._gnbTouched = true; Control.refresh(); });
$("#ctl-ocudu-all").addEventListener("change", (e) => { Control.showAll = e.target.checked; Control.refresh(); });
$("#ctl-logout").addEventListener("click", () => Settings.logout());
