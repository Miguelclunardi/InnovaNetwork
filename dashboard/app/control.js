/* Innova Center Dashboard — aba Controle (iniciar/parar/reiniciar core, UERANSIM e gNB OCUDU).
   Usa a sessão de administrador da aba Configuração (Settings.token) e as utilidades de app.js. */
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
    this.renderGroup("core", "#ctl-core", busy, logged);
    this.renderGroup("ueransim", "#ctl-ueransim", busy, logged);
    this.renderOcudu(busy, logged);
    this.renderJob();
    $$("#tab-control [data-act]").forEach((b) => { b.disabled = !logged || busy; });
  },

  stateTag(c) {
    const cls = { rodando: "ok", parado: "", iniciando: "warn", parando: "warn" }[c.state] || "";
    const bad = c.pods.find((p) => p.reason && /BackOff|Error|Err/.test(p.reason));
    return `<span class="tag ${bad ? "err" : cls}">${esc(bad ? bad.reason : c.state)}</span>`;
  },

  renderGroup(group, sel, busy, logged) {
    const comps = (this.data.components || []).filter((c) => c.group === group);
    const run = comps.filter((c) => c.state === "rodando").length;
    $(sel + "-sub").textContent = comps.length ? `${run} de ${comps.length} rodando` : "nenhum componente no namespace";
    $(sel).innerHTML = `<tr><th>Componente</th><th>Estado</th><th class="num">Reinícios</th><th class="num">Ligado há</th><th class="num">Ações</th></tr>` +
      comps.map((c) => {
        const p = c.pods[0];
        return `<tr title="${esc(c.deployment)}${p ? " · pod " + esc(p.name) : ""}"><td><b>${esc(c.label)}</b></td><td>${this.stateTag(c)}</td>
          <td class="num">${p ? (p.restarts ? `<span class="tag warn">${p.restarts}</span>` : 0) : "–"}</td>
          <td class="num">${p && p.since ? ago(p.since) : "–"}</td>
          <td class="num nowrap">
            <button class="btn small" data-act="start" data-target="${esc(c.key)}" title="Iniciar">▶</button>
            <button class="btn small" data-act="restart" data-target="${esc(c.key)}" title="Reiniciar (recria o pod)">↻</button>
            <button class="btn small danger" data-act="stop" data-target="${esc(c.key)}" title="Parar">■</button></td></tr>`;
      }).join("");
  },

  renderOcudu(busy, logged) {
    const box = $("#ctl-ocudu-card");
    const o = this.data.ocudu;
    box.classList.toggle("hidden", !o);
    if (!o) return;
    const s = o.status || {};
    $("#ctl-ocudu-sub").innerHTML = `${esc(o.target)} · ` + (o.online
      ? (s.error ? `<span class="tag err">sem SSH</span> ${esc(s.error)}` : `atualizado há ${ago(Date.now() / 1000 - o.age)}`)
      : '<span class="tag err">agente sem contato</span> (journalctl -u open5gs-k3s-gnb-ctl na máquina do core)');
    const a = s.active, f = s.failed;
    const setup = s.unit_installed === false || s.polkit === false;
    $("#ctl-ocudu-setup").classList.toggle("hidden", !setup);
    const ptp = s.ptp || {};
    const nics = s.nics || {};
    const k = [
      { l: "gNB", v: a ? (a.sub === "running" ? "rodando" : a.sub) : (s.manual || []).length ? "rodando fora do painel" : "parado",
        s: a ? `${a.config}.yml · PID ${a.pid}` : (s.manual || []).length ? `PID ${(s.manual || []).map((m) => m.pid).join(", ")} (pare no terminal)` : f ? `última vez: falhou (${f.config})` : "",
        c: a && a.sub === "running" ? "ok" : (s.manual || []).length ? "warn" : f ? "err" : "" },
      { l: "Ligado desde", v: a && a.since ? a.since.replace(/^\w+ /, "").replace(/ [A-Z-]+\d*$/, "") : "–", s: "" },
      { l: "PTP (ptp4l / ts2phc / phc2sys)", v: ["ptp4l-gm", "ts2phc", "phc2sys"].map((x) => ptp[x] === "active" ? "✓" : "✗").join(" "),
        s: Object.values(ptp).every((x) => x === "active") ? "todos ativos" : "algum serviço PTP parado", c: Object.values(ptp).every((x) => x === "active") ? "ok" : "err" },
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
        c.amf ? ` — AMF ${esc(c.amf)}${c.amf === CONFIG.amf_ip ? " (este core)" : ""}` : ""}${c.bw ? ` · ${c.bw} MHz` : ""}</option>`).join("");
    }
    const c = (s.configs || []).find((x) => x.name === sel.value) || {};
    $("#ctl-ocudu-cfginfo").innerHTML = c.name ? [
      c.amf ? (c.amf === CONFIG.amf_ip ? '<span class="tag ok">aponta para este core</span>' : `<span class="tag warn">AMF ${esc(c.amf)} — não é este core</span>`) : "",
      c.arfcn ? `ARFCN ${c.arfcn}` : "", c.bw ? `${c.bw} MHz` : "", c.nic ? `fronthaul ${esc(c.nic)}` : "",
      c.mtime ? `alterado em ${new Date(c.mtime * 1000).toLocaleString("pt-BR")}` : "",
    ].filter(Boolean).join(" · ") : "";
    const j = (a || f || {}).journal || [];
    $("#ctl-ocudu-journal").textContent = j.length ? j.join("\n") : "(sem saída do serviço)";
    $("#ctl-ocudu-manual").classList.toggle("hidden", !(s.manual || []).length);
    $("#ctl-ocudu-manual").innerHTML = (s.manual || []).length ? `Há um <b>gnb aberto fora do painel</b> (${(s.manual || []).map((m) => `PID ${m.pid}: <code>${esc(m.cmd)}</code>`).join("; ")}). O painel não inicia outro enquanto ele existir; pare-o no terminal (Ctrl+C).` : "";
  },

  renderJob() {
    const j = this.data.job;
    $("#ctl-job").classList.toggle("hidden", !j);
    if (j) {
      const st = { running: '<span class="tag warn">em andamento</span>', ok: '<span class="tag ok">concluído</span>',
        warn: '<span class="tag warn">concluído com avisos</span>', error: '<span class="tag err">falhou</span>' }[j.state];
      $("#ctl-job-title").innerHTML = `${esc(j.title)} ${st} <span class="muted">${hhmmss(j.t0 * 1000)}${j.t1 ? " – " + hhmmss(j.t1 * 1000) : ""}</span>`;
      const box = $("#ctl-job-log");
      const atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
      box.innerHTML = j.lines.map((l) => `<div class="ev ${l.level === "error" ? "error" : l.level === "warn" ? "warning" : "info"}">
        <span class="t">${hhmmss(l.t * 1000)}</span><span class="src">${l.level === "error" ? "erro" : l.level === "warn" ? "aviso" : ""}</span><span class="msg">${esc(l.msg)}</span><span class="cnt"></span></div>`).join("");
      if (atEnd) box.scrollTop = box.scrollHeight;
    }
    const r = this.data.recent || [];
    $("#ctl-recent").innerHTML = r.length ? r.map((x) => `<li>${hhmmss(x.t0 * 1000)} · ${esc(x.title)} — ${
      { ok: "concluído", warn: "com avisos", error: "falhou", running: "em andamento" }[x.state]}</li>`).join("") : '<li class="muted">nenhuma</li>';
  },

  async act(action, target, config) {
    const label = { start: "Iniciar", stop: "Parar", restart: "Reiniciar" }[action];
    const what = { all: "core + UERANSIM", core: "o core inteiro", ueransim: "o UERANSIM", ocudu: "o gNB OCUDU" }[target] || target.toUpperCase();
    if ((action !== "start" || target === "ocudu") && !confirm(`${label} ${what}?` +
      (action !== "start" && ["core", "all", "amf", "upf", "smf", "ocudu"].includes(target) ? "\n\nQuem estiver usando a rede perde a conexão." : ""))) return;
    try {
      await Settings.call("POST", "api/control", { action, target, config });
    } catch (e) { alert(e.message); }
    this.refresh();
  },
};

document.addEventListener("click", (e) => {
  const b = e.target.closest("#tab-control [data-act]");
  if (!b) return;
  const t = b.dataset.target;
  Control.act(b.dataset.act, t, t === "ocudu" ? $("#ctl-ocudu-cfg").value : undefined);
});
$("#ctl-ocudu-cfg").addEventListener("change", (e) => {
  Control.cfgSel = e.target.value;
  try { localStorage.setItem("icd.ocudu.cfg", Control.cfgSel); } catch { /* sem storage */ }
  Control.refresh();
});
$("#ctl-ocudu-all").addEventListener("change", (e) => { Control.showAll = e.target.checked; Control.refresh(); });
$("#ctl-login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const d = await Settings.call("POST", "api/admin/login", { password: $("#ctl-pass").value });
    Settings.setToken(d.token);
    $("#ctl-pass").value = "";
    $("#ctl-login-msg").textContent = "";
    Control.refresh();
  } catch (err) { $("#ctl-login-msg").textContent = err.message; }
});
$("#ctl-logout").addEventListener("click", async () => { await Settings.logout(); Control.refresh(); });
