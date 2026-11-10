/* Terminal tab (administrator only): shells on the core machine, several at once (like VS Code).
   Each terminal is an xterm.js view with its own WebSocket (api/term/ws) — see dashboard/app/term.py.
   Terminals stay open while you switch dashboard tabs; they end when closed or when the page reloads. */
"use strict";

const MAC = /Mac|iPhone|iPad/.test(navigator.platform || "");

const Term = {
  tabs: [],          // {id, name, profile, term, fit, ws, pane, btn, alive}
  cur: null,
  seq: 0,
  count: {},
  status: null,
  shown: false,

  enabled() { return !!(CONFIG && CONFIG.terminal) && !!Settings.token; },

  // tab button: only for the administrator; logging out closes every terminal
  updateTab() {
    const on = this.enabled();
    $("#tabbtn-terminal").classList.toggle("hidden", !on);
    if (!on) {
      this.tabs.slice().forEach((t) => this.close(t.id));
      if (typeof currentTab !== "undefined" && currentTab === "terminal") showTab("overview");
    }
  },

  async refresh() {
    if (!this.enabled()) return;
    try {
      const r = await fetch("api/term", { cache: "no-store", headers: { "X-Admin-Token": Settings.token } });
      if (r.status === 401) { Settings.setToken(""); Admin.changed(); return; }
      this.status = await r.json();
    } catch { this.status = null; }
    const st = this.status;
    const sel = $("#term-profile");
    const profs = (st && st.profiles) || [];
    if (sel.dataset.list !== profs.join("|")) {
      const prev = sel.value;
      sel.innerHTML = profs.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
      if (profs.includes(prev)) sel.value = prev;
      sel.dataset.list = profs.join("|");
    }
    const ok = st && st.agent;
    $("#term-new").disabled = !ok;
    $("#term-status").textContent = !st ? "dashboard without terminal support"
      : !ok ? "terminal agent not connected (on the core machine: journalctl -u open5gs-k3s-term)"
      : `${st.sessions}/${st.max_sessions} open`;
    $("#term-status").classList.toggle("bad", !ok);
    $("#term-empty").classList.toggle("hidden", this.tabs.length > 0);
  },

  // first visit: open one terminal by itself
  onShow() {
    if (!this.enabled()) { showTab("overview"); return; }
    this.shown = true;
    this.refresh().then(() => {
      if (!this.tabs.length && this.status && this.status.agent) this.open();
      this.fitCur();
    });
  },

  open(profile) {
    profile = profile || $("#term-profile").value || (this.status && this.status.profiles[0]) || "";
    const id = ++this.seq;
    this.count[profile] = (this.count[profile] || 0) + 1;
    const name = profile + (this.count[profile] > 1 ? " " + this.count[profile] : "");
    const pane = document.createElement("div");
    pane.className = "term-pane notr";
    $("#term-panes").appendChild(pane);
    const dark = document.documentElement.dataset.theme !== "light";
    const term = new Terminal({
      cursorBlink: true, fontSize: 13, scrollback: 10000, allowProposedApi: false,
      fontFamily: getComputedStyle(document.documentElement).getPropertyValue("--mono") || "monospace",
      theme: dark ? { background: "#0a0e14" } : { background: "#0f1720", foreground: "#d6dde6" },
    });
    const fit = new FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(pane);
    const t = { id, name, profile, term, fit, pane, ws: null, alive: true, btn: null };
    this.tabs.push(t);
    this.renderTabs();
    this.select(id);
    try { fit.fit(); } catch { /* hidden */ }

    const u = new URL("api/term/ws", location.href);
    u.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    u.search = new URLSearchParams({ t: Settings.token, profile, cols: term.cols, rows: term.rows }).toString();
    const ws = new WebSocket(u);
    ws.binaryType = "arraybuffer";
    t.ws = ws;
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") { term.write(new Uint8Array(ev.data)); return; }
      let m = {};
      try { m = JSON.parse(ev.data); } catch { /* not a notice */ }
      if (m.error) term.write(`\r\n\x1b[31m[${m.error}]\x1b[0m\r\n`);
      if ("exit" in m) term.write(`\r\n\x1b[90m[process ended${m.exit != null ? ", code " + m.exit : ""}]\x1b[0m\r\n`);
    };
    ws.onclose = () => {
      t.alive = false;
      term.write("\r\n\x1b[90m[session closed — close this tab or open a new terminal]\x1b[0m\r\n");
      this.renderTabs();
      this.refresh();
    };
    term.onData((d) => { if (ws.readyState === 1) ws.send(JSON.stringify({ i: d })); });
    term.onResize(({ cols, rows }) => { if (ws.readyState === 1) ws.send(JSON.stringify({ r: [cols, rows] })); });
    // Keys like VS Code. Copy: Ctrl+C with a selection (without one, ^C still goes to the shell),
    // Ctrl+Shift+C, Cmd+C on macOS. Paste: Ctrl+V, Ctrl+Shift+V, Cmd+V — xterm ignores the key and the
    // browser fires its native paste event on xterm's textarea (navigator.clipboard is blocked over HTTP).
    term.attachCustomKeyEventHandler((e) => this.keys(e, term));
    setTimeout(() => this.refresh(), 800);
    return t;
  },

  // false = xterm ignores the key (nothing is sent to the shell)
  keys(e, term) {
    if (e.altKey) return true;
    const cmd = MAC && e.metaKey && !e.ctrlKey, ctrl = e.ctrlKey && !e.metaKey;
    if (!cmd && !ctrl) return true;
    const k = (e.key || "").toLowerCase();
    if (k === "c") {
      if (ctrl && !e.shiftKey && !term.hasSelection()) return true;   // plain Ctrl+C: interrupt
      if (e.type === "keydown") {
        e.preventDefault();
        if (term.hasSelection()) { this.copy(term.getSelection(), term); term.clearSelection(); }
      }
      return false;
    }
    // no preventDefault: the browser pastes into xterm's textarea (Ctrl+V on macOS stays ^V)
    if (k === "v" && (cmd || !MAC)) return false;
    return true;
  },

  // navigator.clipboard only exists in a secure context (HTTPS/localhost); over plain HTTP use a
  // temporary textarea + execCommand("copy"), then give the focus back to the terminal
  copy(text, term) {
    const fallback = () => {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;top:0;left:-9999px;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch { /* no clipboard */ }
      ta.remove();
      term.focus();
    };
    if (window.isSecureContext && navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => term.focus(), fallback);
    } else fallback();
  },

  select(id) {
    this.cur = id;
    this.tabs.forEach((t) => t.pane.classList.toggle("active", t.id === id));
    this.renderTabs();
    this.fitCur();
    const t = this.tabs.find((x) => x.id === id);
    if (t) setTimeout(() => t.term.focus(), 0);
  },

  close(id) {
    const i = this.tabs.findIndex((t) => t.id === id);
    if (i < 0) return;
    const t = this.tabs[i];
    try { t.ws && t.ws.close(); } catch { /* already closed */ }
    t.term.dispose();
    t.pane.remove();
    this.tabs.splice(i, 1);
    if (this.cur === id) {
      const n = this.tabs[Math.min(i, this.tabs.length - 1)];
      this.cur = null;
      if (n) this.select(n.id);
    }
    this.renderTabs();
    $("#term-empty").classList.toggle("hidden", this.tabs.length > 0);
  },

  rename(id) {
    const t = this.tabs.find((x) => x.id === id);
    if (!t) return;
    const v = prompt("Terminal name", t.name);
    if (v && v.trim()) { t.name = v.trim().slice(0, 40); this.renderTabs(); }
  },

  renderTabs() {
    const box = $("#term-tabs");
    box.innerHTML = "";
    this.tabs.forEach((t) => {
      const b = document.createElement("div");
      b.className = "term-tab" + (t.id === this.cur ? " active" : "") + (t.alive ? "" : " dead");
      b.title = `${t.profile} — double-click to rename, middle click to close`;
      b.innerHTML = `<span class="term-dot"></span><span class="term-name notr">${esc(t.name)}</span>` +
        `<button class="term-x" title="Close terminal">×</button>`;
      b.addEventListener("click", (e) => { if (e.target.closest(".term-x")) this.close(t.id); else this.select(t.id); });
      b.addEventListener("dblclick", (e) => { if (!e.target.closest(".term-x")) this.rename(t.id); });
      b.addEventListener("auxclick", (e) => { if (e.button === 1) this.close(t.id); });
      box.appendChild(b);
    });
  },

  fitCur() {
    const t = this.tabs.find((x) => x.id === this.cur);
    if (!t || currentTab !== "terminal") return;
    requestAnimationFrame(() => { try { t.fit.fit(); } catch { /* not visible */ } });
  },
};

$("#term-new").addEventListener("click", () => Term.open());
$("#term-empty-open").addEventListener("click", () => Term.open());
window.addEventListener("resize", () => Term.fitCur());
setInterval(() => { if (currentTab === "terminal") Term.refresh(); }, 5000);
