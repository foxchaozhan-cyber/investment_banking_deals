/* Global IB deals dashboard. Reads data/*.json produced by the daily pipeline. */
(() => {
  "use strict";

  const SEGMENTS = [
    { key: "ecm1", label: "ECM primary", color: "var(--series-1)" },
    { key: "ecm2", label: "ECM secondary", color: "var(--series-2)" },
    { key: "mna", label: "M&A", color: "var(--series-3)" },
  ];
  const SEG = Object.fromEntries(SEGMENTS.map((s) => [s.key, s]));
  const SOURCE_LABELS = { nasdaq_ipo: "Nasdaq IPOs", edgar: "SEC EDGAR", news: "News", manual: "Manual CSV" };
  const PAGE = 50;
  const SVGNS = "http://www.w3.org/2000/svg";

  const state = {
    deals: [], meta: {}, filings: null, thresholds: { ecm_usd: 1e8, mna_usd: 5e8 },
    asOf: new Date(), range: "30", sort: { key: "date", dir: -1 }, shown: PAGE, filtered: [],
  };

  // ---------- helpers ----------
  const $ = (id) => document.getElementById(id);
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "style") n.setAttribute("style", v);
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const k of kids.flat()) if (k != null) n.append(k.nodeType ? k : document.createTextNode(String(k)));
    return n;
  }
  function svg(tag, attrs, ...kids) {
    const n = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v != null) n.setAttribute(k, v);
    for (const k of kids.flat()) if (k != null) n.append(k.nodeType ? k : document.createTextNode(String(k)));
    return n;
  }
  function fmtUSD(v, digits) {
    if (v == null || !isFinite(v)) return "—";
    const a = Math.abs(v);
    const f = (x, u) => `$${x.toFixed(digits ?? (x >= 100 ? 0 : 1)).replace(/\.0$/, "")}${u}`;
    if (a >= 1e12) return f(v / 1e12, "T");
    if (a >= 1e9) return f(v / 1e9, "B");
    if (a >= 1e6) return f(v / 1e6, "M");
    if (a >= 1e3) return f(v / 1e3, "K");
    return `$${Math.round(v)}`;
  }
  const fmtInt = (n) => n.toLocaleString("en-US");
  const parseDay = (s) => new Date(`${s.slice(0, 10)}T00:00:00Z`);
  const iso = (d) => d.toISOString().slice(0, 10);
  const addDays = (d, n) => new Date(d.getTime() + n * 864e5);
  const segOf = (d) => (d.category === "M&A" ? "mna" : d.market === "Secondary" ? "ecm2" : "ecm1");
  const regionOf = (d) => d.region || "Unspecified";
  const isMajor = (d) => d.value_usd != null &&
    d.value_usd >= (d.category === "M&A" ? state.thresholds.mna_usd : state.thresholds.ecm_usd);

  async function loadJSON(name) {
    for (const base of ["data/", "../data/"]) {
      try {
        const r = await fetch(base + name, { cache: "no-cache" });
        if (r.ok) return await r.json();
      } catch (_) { /* try next */ }
    }
    return null;
  }

  // ---------- tooltip ----------
  const tip = $("tip");
  function showTip(evt, head, rows) {
    tip.replaceChildren(el("div", { class: "t-head" }, head));
    for (const r of rows) {
      tip.append(el("div", { class: "t-row" },
        r.color ? el("span", { class: "key", style: `background:${r.color}` }) : null,
        el("b", {}, r.value), el("span", { class: "muted" }, r.label)));
    }
    tip.hidden = false;
    const rect = evt.target.getBoundingClientRect ? evt.target.getBoundingClientRect() : null;
    const x = evt.clientX ?? (rect ? rect.right : 0);
    const y = evt.clientY ?? (rect ? rect.top : 0);
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = `${Math.min(window.innerWidth - w - 8, x + 12)}px`;
    tip.style.top = `${Math.max(8, y - h - 12)}px`;
  }
  const hideTip = () => { tip.hidden = true; };
  function hover(node, fn) {
    node.setAttribute("tabindex", "0");
    node.addEventListener("pointermove", (e) => fn(e));
    node.addEventListener("focus", (e) => fn(e));
    node.addEventListener("pointerleave", hideTip);
    node.addEventListener("blur", hideTip);
  }

  // ---------- filters ----------
  function rangeStart() {
    if (state.range === "ytd") return new Date(Date.UTC(state.asOf.getUTCFullYear(), 0, 1));
    return addDays(state.asOf, -Number(state.range) + 1);
  }
  function applyFilters() {
    const start = iso(rangeStart()), end = iso(state.asOf);
    const f = {
      category: $("f-category").value, market: $("f-market").value, type: $("f-type").value,
      region: $("f-region").value, status: $("f-status").value, major: $("f-major").checked,
      q: $("f-q").value.trim().toLowerCase(),
    };
    state.filtered = state.deals.filter((d) => {
      if (d.date < start || d.date > end) return false;
      if (f.category && d.category !== f.category) return false;
      if (f.market && d.market !== f.market) return false;
      if (f.type && d.deal_type !== f.type) return false;
      if (f.region && regionOf(d) !== f.region) return false;
      if (f.status && d.status !== f.status) return false;
      if (f.major && !isMajor(d)) return false;
      if (f.q) {
        const hay = [d.issuer, d.acquirer, d.country, d.region, d.sector, d.exchange, d.ticker, d.deal_type]
          .filter(Boolean).join(" ").toLowerCase();
        if (!hay.includes(f.q)) return false;
      }
      return true;
    });
    state.shown = PAGE;
    renderAll();
  }
  function fillSelect(id, values) {
    const s = $(id);
    for (const v of values) s.append(el("option", {}, v));
  }

  // ---------- tiles ----------
  function renderTiles() {
    const ds = state.filtered;
    const sum = (arr) => arr.reduce((a, d) => a + (d.value_usd || 0), 0);
    const mna = ds.filter((d) => d.category === "M&A"), ecm = ds.filter((d) => d.category === "ECM");
    const sized = ds.filter((d) => d.value_usd != null);
    const largest = sized.reduce((a, d) => (!a || d.value_usd > a.value_usd ? d : a), null);
    const tiles = [
      ["M&A value", fmtUSD(sum(mna)), `${fmtInt(mna.length)} deals`],
      ["ECM value", fmtUSD(sum(ecm)),
        `${fmtInt(ecm.filter((d) => d.market === "Primary").length)} primary · ${fmtInt(ecm.filter((d) => d.market === "Secondary").length)} secondary`],
      ["Deals", fmtInt(ds.length), `${fmtInt(ds.length - sized.length)} without disclosed size`],
      ["Largest deal", largest ? fmtUSD(largest.value_usd) : "—", largest ? dealName(largest) : "No sized deals"],
    ];
    $("tiles").replaceChildren(...tiles.map(([l, v, n]) =>
      el("div", { class: "tile" }, el("div", { class: "label" }, l), el("div", { class: "value" }, v),
        el("div", { class: "note", title: n }, n))));
  }
  const dealName = (d) => (d.acquirer ? `${d.acquirer} / ${d.issuer || "?"}` : d.issuer || "Unnamed deal");

  // ---------- charts ----------
  function niceMax(v) {
    if (v <= 0) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    const m = v / p;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
  }
  function binning() {
    const days = Math.round((state.asOf - rangeStart()) / 864e5) + 1;
    return days <= 31 ? "day" : days <= 190 ? "week" : "month";
  }
  function binKey(dateStr, unit) {
    const d = parseDay(dateStr);
    if (unit === "day") return iso(d);
    if (unit === "week") return iso(addDays(d, -((d.getUTCDay() + 6) % 7)));
    return iso(new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1)));
  }
  function binsFor(unit) {
    const keys = [];
    let d = parseDay(binKey(iso(rangeStart()), unit));
    while (d <= state.asOf) {
      keys.push(iso(d));
      d = unit === "day" ? addDays(d, 1) : unit === "week" ? addDays(d, 7)
        : new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1));
    }
    return keys;
  }
  function binLabel(key, unit, short) {
    const d = parseDay(key);
    const opts = unit === "month" ? { month: "short", year: short ? "2-digit" : "numeric", timeZone: "UTC" }
      : { month: "short", day: "numeric", timeZone: "UTC" };
    const s = d.toLocaleDateString("en-US", opts);
    return unit === "week" && !short ? `Week of ${s}` : s;
  }
  // Column with a 4px rounded data-end and a square base.
  function colPath(x, y, w, h, roundTop) {
    if (h <= 0) return "";
    const r = roundTop ? Math.min(4, h, w / 2) : 0;
    return `M${x},${y + h}V${y + r}${r ? `Q${x},${y} ${x + r},${y}` : ""}H${x + w - r}` +
      `${r ? `Q${x + w},${y} ${x + w},${y + r}` : ""}V${y + h}Z`;
  }
  function barPath(x, y, w, h) { // horizontal bar, rounded at the right end
    if (w <= 0) return "";
    const r = Math.min(4, w, h / 2);
    return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
  }

  function renderTimeSeries() {
    const host = $("ts-chart");
    const unit = binning();
    const keys = binsFor(unit);
    const bins = new Map(keys.map((k) => [k, { ecm1: 0, ecm2: 0, mna: 0, n: 0 }]));
    for (const d of state.filtered) {
      const b = bins.get(binKey(d.date, unit));
      if (!b) continue;
      b.n += 1;
      if (d.value_usd != null) b[segOf(d)] += d.value_usd;
    }
    $("ts-sub").textContent = `US$ per ${unit}, sized deals`;
    $("ts-legend").replaceChildren(...SEGMENTS.map((s) =>
      el("li", {}, el("span", { class: "sw", style: `background:${s.color}` }), s.label)));

    const W = Math.max(320, host.clientWidth || 800), H = 240;
    const m = { t: 12, r: 8, b: 26, l: 48 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const totals = keys.map((k) => SEGMENTS.reduce((a, s) => a + bins.get(k)[s.key], 0));
    const max = niceMax(Math.max(0, ...totals));
    // Tick count that keeps every tick a round number (2.5 -> 0.5 steps, 5 -> 1, 10 -> 2).
    const mant = max / Math.pow(10, Math.floor(Math.log10(max)));
    const nTicks = mant === 2.5 || mant === 5 || mant === 10 || mant === 1 ? 5 : 4;
    const y = (v) => m.t + ih - (v / max) * ih;
    const band = iw / keys.length;
    const bw = Math.max(2, Math.min(24, band * 0.7));
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `Stacked deal value per ${unit} by segment` });
    for (let i = 0; i <= nTicks; i++) {
      const v = (max / nTicks) * i, yy = y(v);
      root.append(svg("line", { class: i ? "gridline" : "baseline", x1: m.l, x2: W - m.r, y1: yy, y2: yy }));
      root.append(svg("text", { class: "tick", x: m.l - 6, y: yy + 4, "text-anchor": "end" }, fmtUSD(v)));
    }
    const every = Math.ceil(keys.length / Math.max(2, Math.floor(iw / 64)));
    keys.forEach((k, i) => {
      const cx = m.l + band * i + band / 2;
      if (i % every === 0) {
        root.append(svg("text", { class: "tick", x: cx, y: H - 8, "text-anchor": "middle" }, binLabel(k, unit, true)));
      }
      const b = bins.get(k);
      const g = svg("g", { class: "mark", "aria-label": `${binLabel(k, unit)}: ${fmtUSD(totals[i])}` });
      let acc = 0;
      const present = SEGMENTS.filter((s) => b[s.key] > 0);
      present.forEach((s, j) => {
        const y0 = y(acc), y1 = y(acc + b[s.key]);
        const gap = j > 0 ? 2 : 0; // 2px surface gap between stacked segments
        const h = Math.max(0, y0 - y1 - gap);
        if (h > 0) {
          g.append(svg("path", { d: colPath(cx - bw / 2, y1, bw, h, j === present.length - 1), fill: s.color }));
        }
        acc += b[s.key];
      });
      g.append(svg("rect", { class: "hit", x: m.l + band * i, y: m.t, width: band, height: ih }));
      hover(g, (e) => showTip(e, binLabel(k, unit), [
        ...SEGMENTS.slice().reverse().map((s) => ({ value: fmtUSD(b[s.key]), label: s.label, color: s.color })),
        { value: fmtUSD(totals[i]), label: `total · ${b.n} deals` },
      ]));
      root.append(g);
    });
    host.replaceChildren(totals.some((t) => t > 0) ? root : el("div", { class: "empty" }, "No sized deals in this selection."));
    $("ts-table").replaceChildren(simpleTable(
      [unit === "week" ? "Week of" : unit === "month" ? "Month" : "Date", ...SEGMENTS.map((s) => s.label), "Total", "Deals"],
      keys.map((k, i) => [binLabel(k, unit, false), ...SEGMENTS.map((s) => fmtUSD(bins.get(k)[s.key])), fmtUSD(totals[i]), bins.get(k).n]),
    ));
  }

  function renderBars(hostId, tableId, rows, colorFor) {
    const host = $(hostId);
    rows = rows.filter((r) => r.value > 0 || r.n > 0).sort((a, b) => b.value - a.value);
    if (!rows.length) {
      host.replaceChildren(el("div", { class: "empty" }, "No deals in this selection."));
      $(tableId).replaceChildren();
      return;
    }
    const W = Math.max(280, host.clientWidth || 400);
    const rowH = 32, bh = 18, labelW = Math.min(150, W * 0.38), valueW = 64;
    const H = rows.length * rowH + 4;
    const max = Math.max(...rows.map((r) => r.value)) || 1;
    const iw = W - labelW - valueW;
    const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Deal value by group" });
    root.append(svg("line", { class: "baseline", x1: labelW, x2: labelW, y1: 0, y2: H }));
    rows.forEach((r, i) => {
      const yy = i * rowH + (rowH - bh) / 2;
      const w = (r.value / max) * iw;
      const g = svg("g", { class: "mark" });
      g.append(svg("text", { class: "cat-label", x: labelW - 8, y: yy + bh / 2 + 4, "text-anchor": "end" }, r.label));
      if (w > 0) g.append(svg("path", { d: barPath(labelW, yy, Math.max(w, 2), bh), fill: colorFor(r) }));
      g.append(svg("text", { class: "bar-label", x: labelW + Math.max(w, 2) + 6, y: yy + bh / 2 + 4 }, fmtUSD(r.value)));
      g.append(svg("rect", { class: "hit", x: 0, y: i * rowH, width: W, height: rowH }));
      hover(g, (e) => showTip(e, r.label, [
        { value: fmtUSD(r.value), label: "sized value", color: colorFor(r) },
        { value: fmtInt(r.n), label: "deals" },
      ]));
      root.append(g);
    });
    host.replaceChildren(root);
    $(tableId).replaceChildren(simpleTable(["Group", "Value (US$)", "Deals"],
      rows.map((r) => [r.label, fmtUSD(r.value), r.n])));
  }
  function groupBy(fn) {
    const m = new Map();
    for (const d of state.filtered) {
      const k = fn(d);
      const r = m.get(k) || { label: k, value: 0, n: 0, seg: segOf(d) };
      r.value += d.value_usd || 0;
      r.n += 1;
      m.set(k, r);
    }
    return [...m.values()];
  }

  function simpleTable(head, rows) {
    return el("table", { class: "data" },
      el("thead", {}, el("tr", {}, head.map((h, i) => el("th", { class: i ? "num" : null }, h)))),
      el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c, i) => el("td", { class: i ? "num" : null }, c))))));
  }

  // ---------- deals table ----------
  const COLS = [
    { key: "date", label: "Date", get: (d) => d.date },
    { key: "deal", label: "Deal", get: (d) => (d.issuer || "").toLowerCase() },
    { key: "deal_type", label: "Type", get: (d) => d.deal_type },
    { key: "value_usd", label: "Value (US$)", num: true, get: (d) => d.value_usd ?? -1 },
    { key: "geo", label: "Country / region", get: (d) => d.country || d.region || "" },
    { key: "status", label: "Status", get: (d) => d.status },
    { key: "src", label: "Sources", get: (d) => d.sources.length },
  ];
  function renderTable() {
    const { key, dir } = state.sort;
    const col = COLS.find((c) => c.key === key);
    const rows = state.filtered.slice().sort((a, b) => {
      const x = col.get(a), y = col.get(b);
      return (x < y ? -1 : x > y ? 1 : 0) * dir || (b.value_usd ?? -1) - (a.value_usd ?? -1);
    });
    $("deal-count").textContent = `${fmtInt(rows.length)} deals · sorted by ${col.label.toLowerCase()}`;
    const head = el("tr", {}, COLS.map((c) => el("th", {
      class: c.num ? "num" : null, scope: "col",
      "aria-sort": c.key === key ? (dir > 0 ? "ascending" : "descending") : null,
      onclick: () => {
        state.sort = { key: c.key, dir: c.key === key ? -dir : (c.key === "date" || c.num ? -1 : 1) };
        renderTable();
      },
    }, c.label + (c.key === key ? (dir > 0 ? " ↑" : " ↓") : ""))));
    const body = rows.slice(0, state.shown).map((d) => el("tr", {},
      el("td", { class: "src" }, d.date),
      el("td", { class: "name" }, d.issuer || "—",
        d.acquirer ? el("span", { class: "low" }, `Acquirer: ${d.acquirer}`) : null,
        d.ticker || d.exchange ? el("span", { class: "low" }, [d.ticker, d.exchange].filter(Boolean).join(" · ")) : null,
        d.sector ? el("span", { class: "low" }, d.sector) : null),
      el("td", {}, el("span", { class: "seg-dot", style: `background:${SEG[segOf(d)].color}` }), d.deal_type,
        el("span", { class: "low" }, d.category === "ECM" ? `ECM · ${d.market}` : "M&A")),
      el("td", { class: "num" }, fmtUSD(d.value_usd),
        d.currency && d.currency !== "USD" && d.value != null
          ? el("span", { class: "low" }, `${d.currency} ${fmtUSD(d.value).slice(1)}`) : null),
      el("td", {}, d.country || "—", d.region && d.country !== d.region ? el("span", { class: "low" }, d.region) : null),
      el("td", {}, el("span", { class: "badge" }, d.status),
        d.origin === "news" ? el("span", { class: "low", title: "Extracted automatically from headlines" }, "from news") : null),
      el("td", { class: "src" }, d.sources.slice(0, 3).flatMap((s, i) => [
        i ? el("br") : null,
        s.url ? el("a", { href: s.url, target: "_blank", rel: "noopener noreferrer", title: s.title || "" }, s.name)
          : el("span", { title: s.title || "" }, s.name),
      ])),
    ));
    $("deals").replaceChildren(el("thead", {}, head), el("tbody", {}, body.length ? body
      : el("tr", {}, el("td", { colspan: COLS.length, class: "muted" }, "No deals match these filters."))));
    $("more").hidden = rows.length <= state.shown;
  }

  function downloadCSV() {
    const fields = ["date", "category", "market", "deal_type", "status", "issuer", "acquirer", "value", "currency",
      "value_usd", "country", "region", "exchange", "ticker", "sector", "origin"];
    const esc = (v) => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
    const lines = [fields.concat("source_url").join(",")].concat(state.filtered.map((d) =>
      fields.map((f) => esc(d[f])).concat(esc(d.sources[0]?.url)).join(",")));
    const a = el("a", { href: URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" })),
      download: `ib-deals-${iso(state.asOf)}.csv` });
    document.body.append(a); a.click(); a.remove();
  }

  // ---------- filings pulse ----------
  function renderPulse() {
    const host = $("pulse");
    const f = state.filings;
    if (!f || !f.groups) {
      host.replaceChildren(el("p", { class: "muted" }, "No EDGAR data yet."));
      return;
    }
    const days = [];
    for (let i = 29; i >= 0; i--) {
      const d = addDays(state.asOf, -i);
      if (d.getUTCDay() % 6) days.push(iso(d)); // business days only
    }
    const colorFor = (g) => (g.category === "M&A" ? SEG.mna.color : g.market === "Secondary" ? SEG.ecm2.color : SEG.ecm1.color);
    host.replaceChildren(...f.groups.map((g) => {
      const series = days.map((d) => (f.daily_counts[d] || {})[g.label] || 0);
      const total = series.reduce((a, b) => a + b, 0);
      const max = Math.max(1, ...series);
      const W = 120, H = 32, step = W / Math.max(1, series.length - 1);
      const pts = series.map((v, i) => `${(i * step).toFixed(1)},${(H - 3 - (v / max) * (H - 6)).toFixed(1)}`);
      const spark = svg("svg", { viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true" },
        svg("polyline", { points: pts.join(" "), fill: "none", stroke: colorFor(g), "stroke-width": 2,
          "stroke-linejoin": "round", "stroke-linecap": "round" }),
        svg("circle", { cx: (series.length - 1) * step, cy: pts[pts.length - 1].split(",")[1], r: 3,
          fill: colorFor(g), stroke: "var(--surface-1)", "stroke-width": 2 }));
      const card = el("div", { class: "p" },
        el("div", { class: "p-label" }, g.label),
        el("div", { class: "p-row" }, el("div", { class: "p-value" }, fmtInt(total)), spark));
      hover(card, (e) => showTip(e, g.label, [
        { value: fmtInt(total), label: "filings, last 30 days", color: colorFor(g) },
        { value: fmtInt(series[series.length - 1]), label: `on ${days[days.length - 1]}` },
      ]));
      return card;
    }));
    const recent = (f.recent || []).slice(0, 60);
    $("filings").replaceChildren(
      el("thead", {}, el("tr", {}, ["Date", "Form", "Group", "Company"].map((h) => el("th", {}, h)))),
      el("tbody", {}, recent.map((r) => el("tr", {},
        el("td", { class: "src" }, r.date), el("td", { class: "src" }, r.form), el("td", {}, r.group),
        el("td", {}, el("a", { href: r.url, target: "_blank", rel: "noopener noreferrer" }, r.company))))));
  }

  // ---------- header ----------
  function renderHeader() {
    const meta = state.meta || {};
    const when = meta.generated_at ? new Date(meta.generated_at) : null;
    $("updated").textContent = when
      ? `Updated ${when.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}`
      : "Not refreshed yet";
    const now = Date.now();
    $("health").replaceChildren(...Object.entries(meta.sources || {}).map(([name, s]) => {
      let status = s.status;
      const last = s.last_success ? new Date(s.last_success).getTime() : null;
      if (status === "error" && last && now - last < 3 * 864e5) status = "stale";
      const label = { ok: "OK", partial: "Partial", error: "Failed", stale: "Stale", skipped: "Off" }[status] || status;
      const detail = [s.records != null ? `${s.records} records` : null, s.message, s.mode === "claude" ? `Claude: ${s.model}` : null,
        s.last_success ? `last success ${s.last_success}` : null].filter(Boolean).join(" · ");
      return el("li", { class: status, title: detail }, el("span", { class: "dot" }),
        `${SOURCE_LABELS[name] || name}: ${label}`);
    }));
    $("fx-note").textContent = meta.fx ? `FX rates for US$ conversion: ${meta.fx}.` : "";
  }

  function renderAll() {
    hideTip();
    renderTiles();
    renderTimeSeries();
    renderBars("region-chart", "region-table", groupBy(regionOf), () => SEG.ecm1.color);
    renderBars("type-chart", "type-table", groupBy((d) => d.deal_type), (r) => SEG[r.seg].color);
    renderTable();
    renderPulse();
  }

  // ---------- theme ----------
  function initTheme() {
    let saved = null;
    try { saved = localStorage.getItem("ibdeals-theme"); } catch (_) { /* storage unavailable */ }
    if (saved) document.documentElement.dataset.theme = saved;
    $("theme").addEventListener("click", () => {
      const dark = document.documentElement.dataset.theme
        ? document.documentElement.dataset.theme === "dark"
        : matchMedia("(prefers-color-scheme: dark)").matches;
      const next = dark ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("ibdeals-theme", next); } catch (_) { /* ignore */ }
    });
  }

  // ---------- boot ----------
  async function main() {
    initTheme();
    const [deals, meta, filings] = await Promise.all([loadJSON("deals.json"), loadJSON("meta.json"), loadJSON("filings.json")]);
    state.deals = (deals && deals.deals) || [];
    state.meta = meta || {};
    state.filings = filings;
    if (deals && deals.thresholds) state.thresholds = deals.thresholds;
    if (state.meta.as_of) state.asOf = parseDay(state.meta.as_of);
    else state.asOf = parseDay(iso(new Date()));

    const uniq = (fn) => [...new Set(state.deals.map(fn).filter(Boolean))].sort();
    fillSelect("f-type", uniq((d) => d.deal_type));
    fillSelect("f-region", uniq(regionOf));
    fillSelect("f-status", uniq((d) => d.status));
    $("f-major").parentElement.title =
      `ECM ≥ ${fmtUSD(state.thresholds.ecm_usd)}, M&A ≥ ${fmtUSD(state.thresholds.mna_usd)}`;

    $("range").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      state.range = b.dataset.days;
      for (const x of $("range").querySelectorAll("button")) x.setAttribute("aria-pressed", String(x === b));
      applyFilters();
    });
    for (const id of ["f-category", "f-market", "f-type", "f-region", "f-status", "f-major"]) {
      $(id).addEventListener("change", applyFilters);
    }
    let t;
    $("f-q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(applyFilters, 150); });
    $("more").addEventListener("click", () => { state.shown += PAGE; renderTable(); });
    $("csv").addEventListener("click", downloadCSV);
    let rt;
    window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(renderAll, 150); });

    renderHeader();
    applyFilters();
  }
  main();
})();
