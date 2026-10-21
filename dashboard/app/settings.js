/* Aba Configuração: editar o config.env (senha de administrador) */
"use strict";

const Settings = {
  token: (() => { try { return sessionStorage.getItem("icd.admin") || ""; } catch { return ""; } })(),
  data: null,
  edits: {},
  plan: null,
  restore: null,
  loaded: false,

  async call(method, path, body) {
    const r = await fetch(path, {
      method, cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Admin-Token": this.token },
      body: body ? JSON.stringify(body) : undefined,
    });
    let d = {};
    try { d = await r.json(); } catch { /* sem corpo */ }
    if (r.status === 401 && d.admin) { this.setToken(""); this.render(); }
    if (!r.ok) { const e = new Error(d.error || r.status + " " + r.statusText); e.data = d; e.status = r.status; throw e; }
    return d;
  },
  setToken(t) {
    this.token = t;
    try { t ? sessionStorage.setItem("icd.admin", t) : sessionStorage.removeItem("icd.admin"); } catch { /* sem storage */ }
  },
  msg(html, kind = "") {
    const m = $("#cfg-msg");
    m.className = "cfgmsg " + kind;
    m.innerHTML = html;
    m.classList.toggle("hidden", !html);
  },

  // Chamado pelo ciclo de atualização: só carrega uma vez (edição não pode ser atropelada)
  async refresh() {
    if (!this.loaded) await this.load();
  },
  async load(reveal = false) {
    if (!this.token) { this.render(); return; }
    try {
      this.data = await this.call("GET", "api/settings" + (reveal ? "?reveal=1" : ""));
      this.loaded = true;
      this.edits = {};
      this.plan = null;
      this.restore = null;
    } catch (e) {
      if (e.status !== 401) this.msg(esc(e.message), "err");
    }
    this.render();
  },
  async login() {
    const pw = $("#cfg-pass").value;
    try {
      const d = await this.call("POST", "api/admin/login", { password: pw });
      this.setToken(d.token);
      $("#cfg-pass").value = "";
      this.msg("");
      await this.load();
    } catch (e) { this.msg(esc(e.message), "err"); }
  },
  async logout() {
    try { await this.call("POST", "api/admin/logout", {}); } catch { /* já expirou */ }
    this.setToken("");
    this.data = null;
    this.loaded = false;
    this.render();
  },

  // ---- desenho
  render() {
    const logged = !!this.token && !!this.data;
    $("#cfg-login").classList.toggle("hidden", logged);
    $("#cfg-main").classList.toggle("hidden", !logged);
    if (!logged) return;
    const d = this.data;
    $("#cfg-sub").innerHTML = `${d.writable ? "" : '<span class="tag err">arquivo sem permissão de escrita para o painel</span> '}` +
      (d.revealed ? '<span class="tag warn">segredos visíveis</span>' : "");
    $("#cfg-reveal").textContent = d.revealed ? "Esconder segredos" : "Mostrar segredos";
    const q = $("#cfg-filter").value.trim().toLowerCase();
    $("#cfg-sections").innerHTML = d.sections.map((s) => {
      const vars = s.vars.filter((v) => !q || v.name.toLowerCase().includes(q) || (v.doc || "").toLowerCase().includes(q)
        || (v.comment || "").toLowerCase().includes(q) || String(v.value ?? (v.items || []).join(" ")).toLowerCase().includes(q));
      if (!vars.length) return "";
      return `<div class="card cfgsec"><h2>${esc(s.title)}${s.notes ? ` <span class="muted">${esc(s.notes)}</span>` : ""}</h2>
        ${vars.map((v) => this.row(v)).join("")}</div>`;
    }).join("") || '<div class="card muted">Nenhuma variável com esse filtro.</div>';
    $$("#cfg-sections [data-var]").forEach((el) => el.addEventListener("input", () => this.changed(el)));
    this.counter();
    this.backups();
  },
  row(v) {
    const cur = this.edits[v.name];
    const locked = v.secret && !this.data.revealed;
    const help = [v.doc, v.comment ? v.comment.replace(/^#\s*/, "") : ""].filter(Boolean).join("\n");
    let input;
    if (v.kind === "bool") {
      const val = cur ?? v.value;
      input = `<select data-var="${esc(v.name)}" ${locked ? "disabled" : ""}>
        <option value="true" ${val === "true" ? "selected" : ""}>true</option>
        <option value="false" ${val === "false" ? "selected" : ""}>false</option></select>`;
    } else if (v.kind === "array") {
      const val = cur ?? v.items;
      input = `<textarea data-var="${esc(v.name)}" rows="${Math.max(2, Math.min(10, val.length + 1))}" spellcheck="false"
        placeholder="um item por linha" ${locked ? "disabled" : ""}>${esc(val.join("\n"))}</textarea>`;
    } else {
      const val = cur ?? v.value;
      input = `<input type="text" data-var="${esc(v.name)}" value="${esc(val)}" spellcheck="false" ${locked ? "disabled" : ""}>`;
    }
    const mod = v.name in this.edits;
    return `<div class="cfgrow${mod ? " mod" : ""}" id="cfgrow-${esc(v.name)}">
      <div class="cfgname"><code>${esc(v.name)}</code>${v.secret ? ' <span class="tag warn">segredo</span>' : ""}
        ${v.kind === "array" ? ' <span class="tag">lista</span>' : ""}</div>
      <div class="cfgval">${input}${help ? `<div class="cfghelp">${esc(help)}</div>` : ""}</div></div>`;
  },
  original(name) {
    for (const s of this.data.sections) for (const v of s.vars) if (v.name === name) return v;
    return null;
  },
  changed(el) {
    const v = this.original(el.dataset.var);
    let val = el.value;
    if (v.kind === "array") {
      val = val.split("\n").map((x) => x.trim()).filter(Boolean);
      if (JSON.stringify(val) === JSON.stringify(v.items)) delete this.edits[v.name]; else this.edits[v.name] = val;
    } else if (val === v.value) delete this.edits[v.name];
    else this.edits[v.name] = val;
    $("#cfgrow-" + CSS.escape(v.name)).classList.toggle("mod", v.name in this.edits);
    this.plan = null;
    $("#cfg-review").classList.add("hidden");
    this.counter();
  },
  counter() {
    const n = Object.keys(this.edits).length;
    $("#cfg-count").textContent = n ? `${n} ${n > 1 ? "alterações não salvas" : "alteração não salva"}` : "sem alterações";
    $("#cfg-preview").disabled = !n;
    $("#cfg-discard").disabled = !n;
  },
  backups() {
    const b = this.data.backups || [];
    $("#cfg-backups").innerHTML = b.length
      ? b.map((x) => `<li><button class="link" data-bk="${esc(x.name)}">${esc(this.bkDate(x.name))}</button></li>`).join("")
      : '<li class="muted">nenhum backup ainda (cada gravação guarda o arquivo anterior)</li>';
    $$("#cfg-backups [data-bk]").forEach((b) => b.addEventListener("click", () => this.previewRestore(b.dataset.bk)));
  },
  bkDate(n) {
    const m = n.match(/(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/);
    return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}:${m[6]}` : n;
  },

  // ---- revisar / gravar
  async preview() {
    this.restore = null;
    await this.review({ changes: this.edits, hash: this.data.hash });
  },
  async previewRestore(name) {
    this.restore = name;
    await this.review({ restore: name, hash: this.data.hash }, `Restaurar o backup de ${this.bkDate(name)}`);
  },
  async review(body, title = "Revisar alterações") {
    this.msg("");
    $("#cfg-review-title").textContent = title;
    try {
      this.plan = await this.call("POST", "api/settings/preview", body);
      this.plan.body = body;
    } catch (e) { this.msg(esc(e.message), "err"); return; }
    const p = this.plan;
    $("#cfg-review").classList.remove("hidden");
    $("#cfg-diff").innerHTML = p.diff ? p.diff.split("\n").map((l) => {
      const c = l.startsWith("+++") || l.startsWith("---") ? "h" : l[0] === "+" ? "add" : l[0] === "-" ? "del" : l[0] === "@" ? "h" : "";
      return `<span class="${c}">${esc(l)}</span>`;
    }).join("\n") : '<span class="muted">nada muda</span>';
    const val = p.validation || {};
    $("#cfg-valid").innerHTML = val.ok === true ? '<span class="tag ok">validação do install: ok</span>'
      : val.ok === false ? `<span class="tag err">a validação do install recusou</span><pre class="cfgout">${esc(val.output)}</pre>`
      : `<span class="tag warn">validação indisponível</span> <span class="muted">${esc(val.output)}</span>`;
    $("#cfg-impact").innerHTML = this.impactHtml(p.impact);
    $("#cfg-save").disabled = !p.changed.length || val.ok === false || !this.data.writable;
    $("#cfg-review").scrollIntoView({ behavior: "smooth", block: "start" });
  },
  impactHtml(im) {
    if (!im || !im.command) return `<span class="muted">${esc(im ? im.text : "")}</span>`;
    const cls = { dashboard: "ok", test: "ok", deploy: "warn", full: "err" }[im.level] || "";
    return `<div><span class="tag ${cls}">para aplicar</span> <code class="cmd">${esc(im.command)}</code>
      <button class="btn small" data-copy="${esc(im.command)}">copiar</button></div><div class="muted">${esc(im.text)}</div>`;
  },
  async save() {
    if (!this.plan) return;
    $("#cfg-save").disabled = true;
    try {
      const d = await this.call("POST", "api/settings/save", this.plan.body);
      const what = this.restore ? "Backup restaurado" : "config.env salvo";
      await this.load(this.data.revealed);
      this.msg(`<b>${what}.</b> Alterado: ${d.changed.map((n) => `<code>${esc(n)}</code>`).join(", ")}.
        Backup do anterior: ${esc(this.bkDate(d.backup))}.<br>Ainda <b>não</b> está aplicado — rode na máquina do core:
        <div style="margin-top:6px">${this.impactHtml(d.impact)}</div>`, "ok");
    } catch (e) {
      this.msg(esc(e.message) + (e.data && e.data.validation && e.data.validation.output
        ? `<pre class="cfgout">${esc(e.data.validation.output)}</pre>` : ""), "err");
      $("#cfg-save").disabled = false;
    }
  },
};

$("#cfg-login-form").addEventListener("submit", (e) => { e.preventDefault(); Settings.login(); });
$("#cfg-logout").addEventListener("click", () => Settings.logout());
$("#cfg-reveal").addEventListener("click", () => {
  if (Object.keys(Settings.edits).length && !confirm("Descartar as alterações não salvas?")) return;
  Settings.load(!Settings.data.revealed);
});
$("#cfg-reload").addEventListener("click", () => {
  if (Object.keys(Settings.edits).length && !confirm("Descartar as alterações não salvas?")) return;
  Settings.load(Settings.data && Settings.data.revealed);
});
$("#cfg-discard").addEventListener("click", () => { Settings.edits = {}; Settings.plan = null; $("#cfg-review").classList.add("hidden"); Settings.render(); });
$("#cfg-filter").addEventListener("input", () => Settings.render());
$("#cfg-preview").addEventListener("click", () => Settings.preview());
$("#cfg-save").addEventListener("click", () => Settings.save());
$("#cfg-cancel").addEventListener("click", () => { Settings.plan = null; $("#cfg-review").classList.add("hidden"); });
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-copy]");
  if (!b) return;
  navigator.clipboard?.writeText(b.dataset.copy).then(() => { b.textContent = "copiado"; setTimeout(() => (b.textContent = "copiar"), 1500); },
    () => { /* sem clipboard (http): o texto está visível */ });
});
window.addEventListener("beforeunload", (e) => { if (Object.keys(Settings.edits).length) e.preventDefault(); });
