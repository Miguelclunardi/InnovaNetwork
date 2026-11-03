/* Settings tab: edit config.env (administrator password) */
"use strict";

const Settings = {
  // single administrator session: the same token serves every dashboard tab and browser tab
  token: (() => { try { return localStorage.getItem("icd.admin") || ""; } catch { return ""; } })(),
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
    try { d = await r.json(); } catch { /* no body */ }
    if (r.status === 401 && d.admin) { this.setToken(""); Admin.changed(); }
    if (!r.ok) { const e = new Error(d.error || r.status + " " + r.statusText); e.data = d; e.status = r.status; throw e; }
    return d;
  },
  setToken(t) {
    this.token = t;
    try {
      t ? localStorage.setItem("icd.admin", t) : localStorage.removeItem("icd.admin");
      sessionStorage.removeItem("icd.admin");
    } catch { /* no storage */ }
  },
  msg(html, kind = "") {
    const m = $("#cfg-msg");
    m.className = "cfgmsg " + kind;
    m.innerHTML = html;
    m.classList.toggle("hidden", !html);
  },

  // Called by the refresh loop: loads only once (an edit in progress must not be overwritten)
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
  async logout() {
    try { await this.call("POST", "api/admin/logout", {}); } catch { /* already expired */ }
    this.setToken("");
    Admin.changed();
  },

  // ---- rendering
  render() {
    const logged = !!this.token && !!this.data;
    $("#cfg-login").classList.toggle("hidden", logged);
    $("#cfg-main").classList.toggle("hidden", !logged);
    if (!logged) return;
    const d = this.data;
    $("#cfg-sub").innerHTML = `${d.writable ? "" : '<span class="tag err">the dashboard cannot write the file</span> '}` +
      (d.revealed ? '<span class="tag warn">secrets visible</span>' : "");
    $("#cfg-reveal").textContent = d.revealed ? "Hide secrets" : "Show secrets";
    const q = $("#cfg-filter").value.trim().toLowerCase();
    $("#cfg-sections").innerHTML = d.sections.map((s) => {
      const vars = s.vars.filter((v) => !q || v.name.toLowerCase().includes(q) || (v.doc || "").toLowerCase().includes(q)
        || (v.comment || "").toLowerCase().includes(q) || String(v.value ?? (v.items || []).join(" ")).toLowerCase().includes(q));
      if (!vars.length) return "";
      return `<div class="card cfgsec"><h2>${esc(s.title)}${s.notes ? ` <span class="muted">${esc(s.notes)}</span>` : ""}</h2>
        ${vars.map((v) => this.row(v)).join("")}</div>`;
    }).join("") || '<div class="card muted">No variable matches this filter.</div>';
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
        placeholder="one item per line" ${locked ? "disabled" : ""}>${esc(val.join("\n"))}</textarea>`;
    } else {
      const val = cur ?? v.value;
      input = `<input type="text" data-var="${esc(v.name)}" value="${esc(val)}" spellcheck="false" ${locked ? "disabled" : ""}>`;
    }
    const mod = v.name in this.edits;
    return `<div class="cfgrow${mod ? " mod" : ""}" id="cfgrow-${esc(v.name)}">
      <div class="cfgname"><code>${esc(v.name)}</code>${v.secret ? ' <span class="tag warn">secret</span>' : ""}
        ${v.kind === "array" ? ' <span class="tag">list</span>' : ""}</div>
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
    $("#cfg-count").textContent = n ? `${n} unsaved change${n > 1 ? "s" : ""}` : "no changes";
    $("#cfg-preview").disabled = !n;
    $("#cfg-discard").disabled = !n;
  },
  backups() {
    const b = this.data.backups || [];
    $("#cfg-backups").innerHTML = b.length
      ? b.map((x) => `<li><button class="link" data-bk="${esc(x.name)}">${esc(this.bkDate(x.name))}</button></li>`).join("")
      : '<li class="muted">no backup yet (every save keeps the previous file)</li>';
    $$("#cfg-backups [data-bk]").forEach((b) => b.addEventListener("click", () => this.previewRestore(b.dataset.bk)));
  },
  bkDate(n) {
    const m = n.match(/(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/);
    return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}:${m[6]}` : n;
  },

  // ---- review / save
  async preview() {
    this.restore = null;
    await this.review({ changes: this.edits, hash: this.data.hash });
  },
  async previewRestore(name) {
    this.restore = name;
    await this.review({ restore: name, hash: this.data.hash }, `Restore the backup of ${this.bkDate(name)}`);
  },
  async review(body, title = "Review changes") {
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
    }).join("\n") : '<span class="muted">nothing changes</span>';
    const val = p.validation || {};
    $("#cfg-valid").innerHTML = val.ok === true ? '<span class="tag ok">install validation: ok</span>'
      : val.ok === false ? `<span class="tag err">the install validation rejected it</span><pre class="cfgout">${esc(val.output)}</pre>`
      : `<span class="tag warn">validation unavailable</span> <span class="muted">${esc(val.output)}</span>`;
    $("#cfg-impact").innerHTML = this.impactHtml(p.impact);
    $("#cfg-save").disabled = !p.changed.length || val.ok === false || !this.data.writable;
    $("#cfg-review").scrollIntoView({ behavior: "smooth", block: "start" });
  },
  impactHtml(im) {
    if (!im || !im.command) return `<span class="muted">${esc(im ? im.text : "")}</span>`;
    const cls = { dashboard: "ok", test: "ok", deploy: "warn", full: "err" }[im.level] || "";
    return `<div><span class="tag ${cls}">to apply</span> <code class="cmd">${esc(im.command)}</code>
      <button class="btn small" data-copy="${esc(im.command)}">copy</button></div><div class="muted">${esc(im.text)}</div>`;
  },
  async save() {
    if (!this.plan) return;
    $("#cfg-save").disabled = true;
    try {
      const d = await this.call("POST", "api/settings/save", this.plan.body);
      const what = this.restore ? "Backup restored" : "config.env saved";
      await this.load(this.data.revealed);
      this.msg(`<b>${what}.</b> Changed: ${d.changed.map((n) => `<code>${esc(n)}</code>`).join(", ")}.
        Backup of the previous one: ${esc(this.bkDate(d.backup))}.<br>It is <b>not</b> applied yet: run on the core machine:
        <div style="margin-top:6px">${this.impactHtml(d.impact)}</div>`, "ok");
    } catch (e) {
      this.msg(esc(e.message) + (e.data && e.data.validation && e.data.validation.output
        ? `<pre class="cfgout">${esc(e.data.validation.output)}</pre>` : ""), "err");
      $("#cfg-save").disabled = false;
    }
  },
};

$("#cfg-logout").addEventListener("click", () => Settings.logout());
$("#cfg-reveal").addEventListener("click", () => {
  if (Object.keys(Settings.edits).length && !confirm("Discard the unsaved changes?")) return;
  Settings.load(!Settings.data.revealed);
});
$("#cfg-reload").addEventListener("click", () => {
  if (Object.keys(Settings.edits).length && !confirm("Discard the unsaved changes?")) return;
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
  navigator.clipboard?.writeText(b.dataset.copy).then(() => { b.textContent = "copied"; setTimeout(() => (b.textContent = "copy"), 1500); },
    () => { /* no clipboard (http): the text is visible */ });
});
window.addEventListener("beforeunload", (e) => { if (Object.keys(Settings.edits).length) e.preventDefault(); });

/* "Admin" button at the top: single login for Control, Settings and the other browser tabs */
const Admin = {
  enabled: false,
  async init() {
    try {
      const d = await (await fetch("api/admin", { cache: "no-store", headers: { "X-Admin-Token": Settings.token } })).json();
      this.enabled = !!d.enabled;
      if (Settings.token && !d.admin) Settings.setToken("");   // expired or the dashboard restarted
    } catch { /* old dashboard */ }
    this.render();
  },
  render() {
    $("#admin-box").classList.toggle("hidden", !this.enabled);
    const on = !!Settings.token;
    const b = $("#admin-btn");
    b.textContent = on ? "🔓 Admin · Sign out" : "🔒 Admin";
    b.classList.toggle("on", on);
    b.title = on ? "Sign out of the administrator session (in every tab)" : "Administrator login: valid for every tab";
  },
  open() {
    $("#admin-pop").classList.remove("hidden");
    $("#admin-msg").textContent = "";
    $("#admin-pass").focus();
  },
  close() { $("#admin-pop").classList.add("hidden"); $("#admin-pass").value = ""; },
  async login() {
    try {
      const d = await Settings.call("POST", "api/admin/login", { password: $("#admin-pass").value });
      Settings.setToken(d.token);
      this.close();
      this.changed();
    } catch (e) { $("#admin-msg").textContent = e.message; }
  },
  // the session changed (here or in another browser tab): redraw whatever depends on it
  changed() {
    Settings.data = null;
    Settings.loaded = false;
    this.render();
    Settings.render();
    if (Settings.token && typeof currentTab !== "undefined" && currentTab === "settings") Settings.load();
    if (typeof Control !== "undefined" && Control.refresh) Control.refresh();
  },
};
$("#admin-btn").addEventListener("click", () => {
  if (Settings.token) return Settings.logout();
  $("#admin-pop").classList.contains("hidden") ? Admin.open() : Admin.close();
});
$("#admin-cancel").addEventListener("click", () => Admin.close());
$("#admin-pop").addEventListener("submit", (e) => { e.preventDefault(); Admin.login(); });
document.addEventListener("click", (e) => { if (e.target.closest("[data-admin-login]")) Admin.open(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") Admin.close(); });
window.addEventListener("storage", (e) => {
  if (e.key !== "icd.admin") return;
  Settings.token = e.newValue || "";
  Admin.changed();
});
Admin.init();
