/* Innova Center Dashboard — aba Máquinas (CPU, memória, temperatura, rede, discos, processos).
   Usa as utilidades de app.js ($, esc, fmt, fmtRate, ago, api, store, Charts, cols, colorFor). */
"use strict";

function fmtBytes(b) {
  if (b == null) return "–";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return b.toFixed(b >= 100 || i === 0 ? 0 : 1) + " " + u[i];
}
function fmtUptime(s) {
  if (s == null) return "–";
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
}
const lvl = (v, w, e) => (v == null ? "" : v >= e ? "err" : v >= w ? "warn" : "");
const bar = (v, w = 70, e = 90) =>
  `<div class="bar"><i class="${lvl(v, w, e)}" style="width:${Math.max(0, Math.min(100, v || 0))}%"></i></div>`;
// "0-17,20" -> Set de números
function cpuSet(s) {
  const out = new Set();
  (s || "").split(",").forEach((p) => {
    const [a, b] = p.split("-").map(Number);
    if (!isNaN(a)) for (let i = a; i <= (isNaN(b) ? a : b); i++) out.add(i);
  });
  return out;
}

const Machines = {
  selected: store.get("hosts.sel", null),
  async refresh() {
    const { hosts } = await api("api/hosts");
    if (!hosts.find((h) => h.name === this.selected)) this.selected = (hosts[0] || {}).name || null;
    $("#host-list").innerHTML = hosts.map((h) => {
      const status = h.online ? '<span class="tag ok">online</span>'
        : h.error ? '<span class="tag err">sem dados</span>' : '<span class="tag">aguardando</span>';
      return `<button class="hostcard ${h.name === this.selected ? "sel" : ""} ${h.online ? "" : "off"}" data-name="${esc(h.name)}">
        <div class="h"><span class="n">${esc(h.name)}</span>${status}</div>
        <div class="r">${esc(h.role || "")}${h.cpu_model ? " · " + esc(h.cpu_model) : ""}</div>
        ${h.cpu != null ? `<div class="bars">
          <span>CPU</span>${bar(h.cpu)}<span>${fmt(h.cpu)}%</span>
          <span>Memória</span>${bar(h.mem_used_pct, 80, 92)}<span>${fmt(h.mem_used_pct)}%</span>
          <span>Temp.</span>${bar(h.temp_cpu, 75, 88)}<span>${h.temp_cpu != null ? fmt(h.temp_cpu, 0) + " °C" : "–"}</span>
        </div>` : ""}
        ${h.energy ? `<div class="pw">⚡ Potência (medidor): ${h.energy.online && h.energy.power != null
          ? `<b>${fmt(h.energy.power, 0)} W</b>` : '<span class="tag err">medidor sem dados</span>'}</div>` : ""}
        ${!h.online && h.error ? `<div class="err">${esc(h.error)}</div>` : ""}
      </button>`;
    }).join("") || `<div class="empty">Nenhuma máquina configurada.</div>`;
    if (this.selected) await this.detail();
  },

  async detail() {
    const name = this.selected;
    const d = await api("api/hosts/" + encodeURIComponent(name) + "?window=" + $("#hd-window").value);
    if (name !== this.selected) return;   // o usuário já escolheu outra máquina
    const l = d.last;
    $("#host-detail").classList.remove("hidden");
    $("#hd-title").textContent = d.name;
    this.energy(d.energy);
    if (!l) {
      $("#hd-sub").textContent = d.error || "aguardando dados";
      ["#hd-kpis", "#hd-cores", "#hd-procs", "#hd-temps", "#hd-disks", "#hd-net"].forEach((s) => ($(s).innerHTML = ""));
      return;
    }
    $("#hd-sub").textContent = `${d.role || ""} · ${l.os || ""} · kernel ${l.kernel || "?"} · ` +
      `${d.source === "local" ? "lido direto" : "via SSH"} · atualizado há ${ago(Date.now() / 1000 - d.age)}`;
    const hp = l.hugepages_total ? `${l.hugepages_total - l.hugepages_free}/${l.hugepages_total} em uso` : "nenhuma";
    const k = [
      { l: "CPU", v: fmt(l.cpu) + "%", s: `${l.ncpu} núcleos lógicos`, c: lvl(l.cpu, 70, 90) },
      { l: "Carga (1/5/15 min)", v: l.load ? l.load.map((x) => x.toFixed(1)).join(" / ") : "–", s: "processos na fila" },
      { l: "Memória", v: fmt(l.mem_used_pct) + "%", s: `${fmtBytes(l.mem_total - l.mem_available)} de ${fmtBytes(l.mem_total)}`,
        c: lvl(l.mem_used_pct, 80, 92) },
      { l: "Temperatura da CPU", v: l.temp_cpu != null ? fmt(l.temp_cpu, 0) + " °C" : "–", s: "maior sensor da CPU",
        c: lvl(l.temp_cpu, 75, 88) },
      { l: "Ligada há", v: fmtUptime(l.uptime), s: `${l.nprocs || "?"} processos` },
      { l: "Hugepages", v: hp, s: l.hugepage_kb ? `páginas de ${fmtBytes(l.hugepage_kb * 1024)}` : "" },
      { l: "Swap", v: l.swap_total ? fmtBytes(l.swap_total - l.swap_free) : "sem swap", s: l.swap_total ? `de ${fmtBytes(l.swap_total)}` : "" },
    ];
    $("#hd-kpis").innerHTML = k.map((x) => `<div class="kpi ${x.c || ""}"><div class="label">${esc(x.l)}</div>
      <div class="value">${esc(x.v)}</div><div class="sub">${esc(x.s)}</div></div>`).join("");

    // núcleos (os isolados — reservados ao gNB — ficam com fundo azul)
    const iso = cpuSet(l.isolated_cpus);
    $("#hd-cores-sub").textContent = `${l.cpu_model || ""}${iso.size ? ` · isolados (fundo azul): ${l.isolated_cpus}` : ""}`;
    $("#hd-cores").innerHTML = (l.cores || []).map((v, i) => `<div class="core ${iso.has(i) ? "iso" : ""}" title="CPU ${i}: ${fmt(v)}%">
      <div><b>${i}</b> <span class="muted">${fmt(v, 0)}%</span></div>${bar(v)}</div>`).join("");

    // gráficos
    const s = d.series;
    Charts.make("c-host-cpu", [{ label: "CPU %", fill: true }, { label: "Temp. °C", color: "#6b7280", scale: "y2", dec: 0 }],
      { y2: true, scales: { y: { range: [0, 100] } } });
    Charts.set("c-host-cpu", cols(s, ["cpu", "temp"]));
    Charts.make("c-host-mem", [{ label: "Memória %" }, { label: "Load 1 min", color: "#6b7280", scale: "y2" }],
      { y2: true, scales: { y: { range: [0, 100] } } });
    Charts.set("c-host-mem", cols(s, ["mem", "load1"]));
    const ifs = (l.net || []).map((n) => n.iface);
    const mb = (v) => fmt(v, 2);
    Charts.make("c-host-rx", ifs.map((n, i) => ({ label: n, color: colorFor(i), fmt: mb })));
    Charts.set("c-host-rx", cols(s, ifs.map((n) => "rx:" + n)));
    Charts.make("c-host-tx", ifs.map((n, i) => ({ label: n, color: colorFor(i), fmt: mb })));
    Charts.set("c-host-tx", cols(s, ifs.map((n) => "tx:" + n)));

    // tabelas
    $("#hd-procs").innerHTML = `<tr><th>Processo</th><th class="num">PID</th><th class="num">CPU</th><th class="num">Memória</th><th class="num">Núcleo</th></tr>` +
      (l.procs || []).map((p) => `<tr><td><b>${esc(p.name)}</b></td><td class="num">${p.pid}</td>
        <td class="num"><span class="tag ${p.cpu >= 90 ? "warn" : ""}">${fmt(p.cpu)}%</span></td><td class="num">${fmtBytes(p.rss)}</td>
        <td class="num">${p.on_cpu >= 0 ? p.on_cpu : "–"}</td></tr>`).join("");
    $("#hd-temps").innerHTML = `<tr><th>Sensor</th><th>Chip</th><th class="num">°C</th></tr>` +
      (l.temps || []).slice().sort((a, b) => b.c - a.c).map((t) => `<tr><td>${esc(t.label)}</td><td class="muted">${esc(t.chip)}</td>
        <td class="num"><span class="tag ${lvl(t.c, 75, 88)}">${fmt(t.c, 0)}</span></td></tr>`).join("");
    $("#hd-disks").innerHTML = `<tr><th>Montagem</th><th>Tipo</th><th class="num">Usado</th><th class="num">Total</th><th style="width:30%">Uso</th></tr>` +
      (l.disks || []).map((x) => `<tr><td><b>${esc(x.mount)}</b> <span class="muted">${esc(x.dev)}</span></td><td>${esc(x.fs)}</td>
        <td class="num">${fmtBytes(x.used)}</td><td class="num">${fmtBytes(x.total)}</td><td>${bar(x.pct, 80, 92)}</td></tr>`).join("");
    $("#hd-net").innerHTML = `<tr><th>Interface</th><th class="num">Recebendo</th><th class="num">Enviando</th><th class="num">Erros/descartes</th></tr>` +
      (l.net || []).map((n) => `<tr><td><b>${esc(n.iface)}</b></td><td class="num">${fmtRate(n.rx_bps)}</td>
        <td class="num">${fmtRate(n.tx_bps)}</td><td class="num">${n.errs ? `<span class="tag warn">${n.errs}</span>` : 0}</td></tr>`).join("");
  },
};
Machines.energy = function (e) {
  const box = $("#hd-energy");
  box.classList.toggle("hidden", !e);
  if (!e) return;
  $("#hd-energy-sub").textContent = `medidor MiEnergy · ${e.url}` +
    (e.online ? ` · atualizado há ${ago(e.ts)}` : ` · sem dados${e.error ? ": " + e.error : ""}`);
  const k = [
    { l: "Potência ativa", v: e.power != null ? fmt(e.power, 0) + " W" : "–", s: "agora" },
    { l: "Tensão", v: e.voltage != null ? fmt(e.voltage, 1) + " V" : "–", s: "fase A" },
    { l: "Corrente", v: e.current != null ? fmt(e.current, 2) + " A" : "–", s: "fase A" },
    { l: "Fator de potência", v: e.pf != null ? fmt(e.pf, 2) : "–", s: "" },
    { l: "Energia acumulada", v: e.energy_kwh != null ? fmt(e.energy_kwh, 3) + " kWh" : "–", s: "contador do medidor" },
    { l: "Consumo desde o início do painel", v: e.energy_delta_kwh != null ? fmt(e.energy_delta_kwh, 3) + " kWh" : "–",
      s: e.energy_since ? "desde " + new Date(e.energy_since * 1000).toLocaleString("pt-BR") : "" },
  ];
  $("#hd-energy-kpis").innerHTML = k.map((x) => `<div class="kpi"><div class="label">${esc(x.l)}</div>
    <div class="value">${esc(x.v)}</div><div class="sub">${esc(x.s)}</div></div>`).join("");
  const s = e.series || { t: [] };
  Charts.make("c-energy-p", [{ label: "Potência W", fill: true, dec: 0 }]);
  Charts.set("c-energy-p", cols(s, ["power"]));
  Charts.make("c-energy-vi", [{ label: "Tensão V" }, { label: "Corrente A", color: "#6b7280", scale: "y2", dec: 2 }], { y2: true });
  Charts.set("c-energy-vi", cols(s, ["voltage", "current"]));
  const f = e.fields || {};
  $("#hd-energy-fields").innerHTML = `<tr><th>Grandeza</th><th class="num">Valor</th></tr>` +
    Object.entries(f).map(([kk, v]) => `<tr><td>${esc(kk)}</td><td class="num">${esc(v)}</td></tr>`).join("");
};
$("#hd-window").addEventListener("change", () => Machines.detail());
// Máquinas: um ouvinte só, no "pointerdown" (a lista é recriada a cada 2 s); destaca e carrega o detalhe na hora
$("#host-list").addEventListener("pointerdown", (e) => {
  const b = e.target.closest(".hostcard");
  if (!b || e.button !== 0 || b.dataset.name === Machines.selected) return;
  Machines.selected = b.dataset.name;
  store.set("hosts.sel", Machines.selected);
  $$("#host-list .hostcard").forEach((x) => x.classList.toggle("sel", x === b));
  Machines.detail();
});
