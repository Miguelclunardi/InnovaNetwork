/* Innova Center Dashboard — language (English / Português).
   The source texts are in English. In Portuguese mode, a MutationObserver translates the text the
   dashboard writes on the page (text nodes and the title/placeholder/aria-label/label attributes)
   with the dictionary below. Logs, code and the documentation text are never translated.
   Do not edit the dictionary here: edit dashboard/i18n/pt.json and run dashboard/i18n/build.py. */
const I18N = (() => {
  const KEY = "icd.lang";
  let lang = null;
  try { lang = JSON.parse(localStorage.getItem(KEY)); } catch { /* no storage */ }
  const q = new URLSearchParams(location.search).get("lang");   // ?lang=pt or ?lang=en (also remembered)
  if (q === "pt" || q === "en") {
    lang = q;
    try { localStorage.setItem(KEY, JSON.stringify(q)); } catch { /* no storage */ }
  }
  if (lang !== "pt" && lang !== "en") lang = /^pt\b/i.test(navigator.language || "") ? "pt" : "en";
  const locale = lang === "pt" ? "pt-BR" : "en-GB";
  document.documentElement.lang = lang === "pt" ? "pt-BR" : "en";

  const DICT = /*DICT*/null;

  // ---- lookup: exact text, then patterns with {n} placeholders, then multi-word fragments
  const norm = (s) => s.replace(/\s+/g, " ").trim();
  const exact = new Map(Object.entries(DICT.exact).map(([k, v]) => [norm(k), v]));
  const reEsc = (s) => s.replace(/[.*+?^$()|[\]\\]/g, "\\$&");
  const patterns = DICT.patterns.map(([en, pt]) => {
    const names = [];
    const src = norm(en).split(/(\{\d+\})/).map((p) => {
      const m = /^\{(\d+)\}$/.exec(p);
      if (!m) return reEsc(p).replace(/[{}]/g, "\\$&");
      names.push(m[1]);
      return "(.*?)";
    }).join("");
    return { re: new RegExp("^" + src + "$"), names, pt };
  });
  const frags = [...exact.keys()].filter((k) => k.includes(" ") && k.length >= 8 && !/[{}]/.test(k))
    .sort((a, b) => b.length - a.length);
  const fragRe = frags.length ? new RegExp("(?<![\\wÀ-ú])(" + frags.map(reEsc).join("|") + ")(?![\\wÀ-ú])", "g") : null;

  // "5 s ago" / "3 min ago" -> "há 5 s" anywhere in a text (durations come from ago() in app.js)
  const AGO = /(\d+(?:[.,]\d+)?\s?(?:ms|s|min|h|d)) ago\b/g;

  function lookup(s, depth) {
    const hit = exact.get(s);
    if (hit !== undefined) return hit;
    for (const p of patterns) {
      const m = p.re.exec(s);
      if (!m) continue;
      const val = {};
      p.names.forEach((n, i) => {
        const v = m[i + 1];
        val[n] = depth < 2 ? core(v, true, depth + 1) ?? v : v;
      });
      return p.pt.replace(/\{(\d+)\}/g, (_, n) => (n in val ? val[n] : ""));
    }
    return null;
  }

  function core(s0, strict, depth) {
    let r = lookup(s0, depth);
    if (r != null) return r;
    const s = s0.replace(AGO, "há $1");
    if (s !== s0 && (r = lookup(s, depth)) != null) return r;
    if (strict || !fragRe) return s !== s0 ? s : null;
    let changed = s !== s0;
    const out = s.replace(fragRe, (f) => { changed = true; return exact.get(f); });
    return changed ? out : null;
  }


  const cache = new Map();
  // Translates one string, keeping the surrounding white space; returns it unchanged when unknown.
  function t(s, strict = false) {
    if (lang !== "pt" || !s || !/[A-Za-z]{2}/.test(s)) return s;
    const ck = (strict ? "1" : "0") + s;
    if (cache.has(ck)) return cache.get(ck);
    const lead = s.match(/^\s*/)[0], trail = s.slice(lead.length).match(/\s*$/)[0];
    const r = core(norm(s), strict, 0);
    const out = r == null ? s : lead + r + trail;
    if (cache.size > 5000) cache.clear();
    cache.set(ck, out);
    return out;
  }
  // dialogs: per line; a leading Start/Stop/Restart verb is a command (not the "Start" column header)
  const VERB = { Start: "Iniciar", Stop: "Parar", Restart: "Reiniciar" };
  const tLines = (s) => String(s).split("\n").map((l) => t(l).replace(/^(Start|Stop|Restart)\b/, (v) => VERB[v])).join("\n");

  // ---- the page
  const SKIP = "#log-view, #docs-view, pre, code, script, style, textarea, .notr, #ctl-ocudu-journal";
  const STRICT = ".msg";   // event lines: whole message or pattern only (they may carry raw log text)
  const ATTRS = ["title", "placeholder", "aria-label", "label"];
  const done = new WeakMap();   // node -> text we wrote (skip it next time)

  function textNode(n) {
    const p = n.parentElement;
    if (!p || p.closest(SKIP)) return;
    const v = n.nodeValue;
    if (done.get(n) === v) return;
    const r = t(v, !!p.closest(STRICT));
    if (r !== v) n.nodeValue = r;
    done.set(n, r);
  }
  function attrs(el) {
    if (el.closest(SKIP)) return;
    for (const a of ATTRS) {
      const v = el.getAttribute(a);
      if (v) { const r = t(v); if (r !== v) el.setAttribute(a, r); }
    }
  }
  function walk(root) {
    if (root.nodeType === 3) return textNode(root);
    if (root.nodeType !== 1) return;
    attrs(root);
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let n = w.nextNode(); n; n = w.nextNode()) n.nodeType === 3 ? textNode(n) : attrs(n);
  }

  if (lang === "pt") {
    const obs = new MutationObserver((recs) => {
      for (const r of recs) {
        if (r.type === "characterData") textNode(r.target);
        else if (r.type === "attributes") attrs(r.target);
        else r.addedNodes.forEach(walk);
      }
      obs.takeRecords();   // drop the records of our own writes
    });
    const start = () => {
      walk(document.body);
      obs.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    };
    if (document.body) start(); else document.addEventListener("DOMContentLoaded", start);
    // browser dialogs
    const A = window.alert.bind(window), C = window.confirm.bind(window), P = window.prompt.bind(window);
    window.alert = (m) => A(tLines(m));
    window.confirm = (m) => C(tLines(m));
    window.prompt = (m, d) => P(tLines(m), d);
  }

  // ---- language button (shows the language you switch to)
  document.addEventListener("DOMContentLoaded", () => {
    const b = document.getElementById("lang");
    if (!b) return;
    b.textContent = lang === "pt" ? "EN" : "PT";
    b.title = lang === "pt" ? "Switch to English" : "Mudar para português";
    b.addEventListener("click", () => {
      try { localStorage.setItem(KEY, JSON.stringify(lang === "pt" ? "en" : "pt")); } catch { /* no storage */ }
      location.reload();
    });
  });

  return { lang, locale, t };
})();
