/* Innova Center Dashboard — aba Documentação: os .md do projeto (o mesmo conteúdo do git),
   lidos da pasta do projeto na máquina do core. Markdown renderizado aqui, sem bibliotecas. */
"use strict";

const Md = {
  inline(t) {
    // `código` primeiro (nada dentro dele é formatado)
    const codes = [];
    t = t.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0001${codes.length - 1}\u0001`; });
    t = esc(t)
      .replace(/!\[([^\]]*)\]\(([^)\s]+)[^)]*\)/g, (_, alt) => `<span class="muted">[imagem: ${alt}]</span>`)
      .replace(/\[([^\]]+)\]\(([^)\s]+)[^)]*\)/g, (_, txt, href) => {
        const h = href.replace(/&amp;/g, "&");
        if (/^https?:\/\//.test(h)) return `<a href="${esc(h)}" target="_blank" rel="noopener">${txt}</a>`;
        if (/\.md(#.*)?$/i.test(h)) return `<a href="#" data-doc="${esc(h)}">${txt}</a>`;
        if (h.startsWith("#")) return `<a href="#" data-anchor="${esc(h.slice(1))}">${txt}</a>`;
        return `<span title="${esc(h)}">${txt}</span>`;
      })
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/(^|[\s(])\*([^*\s][^*]*)\*/g, "$1<i>$2</i>")
      .replace(/(^|[\s(])_([^_\s][^_]*)_(?=[\s.,;:)!?]|$)/g, "$1<i>$2</i>");
    return t.replace(/\u0001(\d+)\u0001/g, (_, i) => `<code>${esc(codes[+i])}</code>`);
  },
  slug(t) {   // como o GitHub: minúsculas, sem pontuação (acentos ficam), cada espaço vira "-"
    return t.replace(/<[^>]+>/g, "").toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu, "").trim().replace(/\s/g, "-");
  },
  render(src) {
    const lines = src.replace(/\r/g, "").split("\n");
    const out = [];
    let i = 0;
    const isTableSep = (l) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(l);
    const cells = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
    while (i < lines.length) {
      const l = lines[i];
      let m;
      if (/^\s*```/.test(l)) {                               // bloco de código (também recuado)
        const ind = l.match(/^\s*/)[0].length;
        const lang = l.trim().slice(3).trim();
        const buf = [];
        for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) buf.push(lines[i].slice(Math.min(ind, lines[i].match(/^\s*/)[0].length)));
        i++;
        out.push(`<pre class="code" data-lang="${esc(lang)}"><code>${esc(buf.join("\n"))}</code></pre>`);
        continue;
      }
      if ((m = /^(#{1,6})\s+(.*)$/.exec(l))) {                // título
        const n = m[1].length, txt = m[2].replace(/\s+#+\s*$/, "");
        out.push(`<h${n} id="${esc(this.slug(txt.replace(/[`*]/g, "")))}">${this.inline(txt)}</h${n}>`);
        i++; continue;
      }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(l)) { out.push("<hr>"); i++; continue; }
      if (l.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {   // tabela
        const head = cells(l);
        i += 2;
        const rows = [];
        for (; i < lines.length && lines[i].includes("|") && lines[i].trim(); i++) rows.push(cells(lines[i]));
        out.push(`<div class="tablewrap"><table><tr>${head.map((h) => `<th>${this.inline(h)}</th>`).join("")}</tr>` +
          rows.map((r) => `<tr>${r.map((c) => `<td>${this.inline(c)}</td>`).join("")}</tr>`).join("") + "</table></div>");
        continue;
      }
      if (/^\s*>/.test(l)) {                                  // citação
        const buf = [];
        for (; i < lines.length && /^\s*>/.test(lines[i]); i++) buf.push(lines[i].replace(/^\s*>\s?/, ""));
        out.push(`<blockquote>${this.render(buf.join("\n"))}</blockquote>`);
        continue;
      }
      if (/^\s*([-*+]|\d+[.)])\s+/.test(l)) {                 // listas (com sub-níveis por recuo)
        const buf = [];
        const item = (x) => /^\s*([-*+]|\d+[.)])\s+/.test(x);
        let fence = false;
        for (; i < lines.length; i++) {
          const x = lines[i];
          if (fence) { buf.push(x); if (/^\s*```/.test(x)) fence = false; continue; }
          if (item(x) || /^\s{2,}\S/.test(x)) { buf.push(x); if (/^\s*```/.test(x)) fence = true; continue; }
          // linha em branco: a lista continua se a próxima for item ou estiver recuada
          if (!x.trim() && i + 1 < lines.length && (item(lines[i + 1]) || /^\s{2,}\S/.test(lines[i + 1]))) { buf.push(x); continue; }
          break;
        }
        out.push(this.list(buf));
        continue;
      }
      if (!l.trim()) { i++; continue; }
      const buf = [];                                         // parágrafo
      for (; i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*```|\s*>|\s*([-*+]|\d+[.)])\s+)/.test(lines[i]) &&
        !(lines[i].includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])); i++) buf.push(lines[i]);
      out.push(`<p>${this.inline(buf.join(" "))}</p>`);
    }
    return out.join("\n");
  },
  list(lines) {
    const indent = (l) => l.match(/^\s*/)[0].length;
    const re = /^\s*([-*+]|\d+[.)])\s+/;
    const base = indent(lines[0]);
    const ordered = /^\s*\d+[.)]/.test(lines[0]);
    const items = [];
    let fence = false;
    for (const l of lines) {
      if (!fence && indent(l) <= base && re.test(l)) {
        items.push({ text: l.replace(re, ""), body: [], cont: indent(l) + (l.match(re)[0].length - indent(l)) });
        continue;
      }
      if (!items.length) continue;
      const it = items[items.length - 1];
      if (/^\s*```/.test(l)) fence = !fence;
      if (!it.body.length && !fence && l.trim() && !re.test(l) && !/^\s*```/.test(l)) it.text += " " + l.trim();
      else it.body.push(l);
    }
    const tag = ordered ? "ol" : "ul";
    return `<${tag}>` + items.map((it) => {
      const chk = /^\[( |x)\]\s/i.exec(it.text);
      const txt = chk ? `<input type="checkbox" disabled ${chk[1] !== " " ? "checked" : ""}> ` + this.inline(it.text.slice(4)) : this.inline(it.text);
      const cut = Math.min(it.cont, ...it.body.filter((x) => x.trim()).map(indent));
      const body = it.body.length ? this.render(it.body.map((x) => x.slice(Math.min(cut, indent(x)))).join("\n")) : "";
      return `<li>${txt}${body}</li>`;
    }).join("") + `</${tag}>`;
  },
};

const Docs = {
  list: [],
  git: {},
  cur: null,
  loaded: false,
  async refresh() {
    if (this.loaded) return;
    const d = await api("api/docs");
    this.loaded = true;
    this.list = d.docs || [];
    this.git = d.git || {};
    const g = this.git;
    $("#docs-git").innerHTML = !d.enabled ? "pasta do projeto não montada no painel (precisa da senha de administrador no config.env)"
      : `git: ${g.branch ? `branch <b>${esc(g.branch)}</b>` : "?"}${g.commit ? ` · commit <code>${esc(g.commit)}</code>` : ""}` +
        (g.remote ? ` · <a href="${esc(g.remote)}" target="_blank" rel="noopener">repositório</a>` : "") +
        "<br>o mesmo conteúdo do repositório, lido da máquina do core";
    this.renderList();
    if (!this.cur) this.open(store.get("docs.cur", null) || (this.list[0] || {}).path);
  },
  renderList() {
    const f = ($("#docs-filter").value || "").toLowerCase();
    const groups = {};
    for (const d of this.list) {
      if (f && !(d.title + " " + d.path).toLowerCase().includes(f)) continue;
      const g = d.path.includes("/") ? d.path.split("/").slice(0, -1).join("/") : "projeto";
      (groups[g] ||= []).push(d);
    }
    const name = { projeto: "Projeto", docs: "docs/", free5gc: "free5GC" };
    $("#docs-list").innerHTML = Object.entries(groups).map(([g, ds]) => `<div class="grp">${esc(name[g] || g + "/")}</div>` +
      ds.map((d) => `<button class="src ${d.path === this.cur ? "active" : ""}" data-path="${esc(d.path)}" title="${esc(d.path)}">
        <span>${esc(d.title)}</span></button>`).join("")).join("") || '<div class="empty">nada encontrado</div>';
  },
  async open(path, anchor) {
    if (!path) { $("#docs-view").innerHTML = '<div class="empty">Nenhum documento.</div>'; return; }
    try {
      const d = await api("api/docs/file?path=" + encodeURIComponent(path));
      this.cur = path;
      store.set("docs.cur", path);
      $("#docs-path").textContent = path;
      const g = this.git;
      const raw = $("#docs-raw");
      raw.classList.toggle("hidden", !(g.remote && g.branch));
      if (g.remote && g.branch) raw.href = `${g.remote}/blob/${encodeURIComponent(g.branch)}/${path}`;
      $("#docs-view").innerHTML = Md.render(d.text);
      this.renderList();
      if (anchor) { const el = document.getElementById(anchor); if (el) el.scrollIntoView(); }
      else $("#docs-view").scrollTop = 0;
    } catch (e) { $("#docs-view").innerHTML = `<div class="note err">${esc(e.message)}</div>`; }
  },
  resolve(href) {
    const [file, anchor] = href.split("#");
    const base = this.cur && this.cur.includes("/") ? this.cur.split("/").slice(0, -1) : [];
    const parts = [...base];
    for (const p of file.split("/")) { if (p === "..") parts.pop(); else if (p && p !== ".") parts.push(p); }
    return [parts.join("/"), anchor];
  },
};

document.addEventListener("click", (e) => {
  const b = e.target.closest("#docs-list [data-path]");
  if (b) return Docs.open(b.dataset.path);
  const a = e.target.closest("#docs-view a[data-doc], #docs-view a[data-anchor]");
  if (!a) return;
  e.preventDefault();
  if (a.dataset.anchor) { const el = document.getElementById(a.dataset.anchor); if (el) el.scrollIntoView({ behavior: "smooth" }); return; }
  const [p, anchor] = Docs.resolve(a.dataset.doc);
  Docs.open(p, anchor);
});
$("#docs-filter").addEventListener("input", () => Docs.renderList());
