// Step 6 — Classify all images, then counts, proportions, statistics and QC views.
import * as api from "../api.js";
import { Viewer } from "../viewer.js";
import { h, icon, errorToast, toast, confirm, modal, fmt, duration, progressBar, switchEl, shortName } from "../ui.js";

let timer = null;
let viewer = null;
let keyHandler = null;
let showAll = false;
let groupMode = "organoid";

export async function render(root, ctx, route, params) {
  if (route === "view") return renderView(root, ctx, params[0]);
  const st = ctx.store.state;
  const job = (st.jobs || []).find((j) => j.kind === "batch");
  if (job) return renderProgress(root, ctx, job);
  const res = await api.get("/api/results");
  if (!res || !st.project.batch.done) return renderStart(root, ctx, res);
  return renderDashboard(root, ctx, res);
}

function header(title, sub, ...right) {
  return h("header", { class: "header" }, h("div", { class: "titles" }, h("h1", {}, title), sub ? h("p", {}, sub) : null), ...right);
}

function renderStart(root, ctx) {
  const st = ctx.store.state;
  const p = st.project;
  root.innerHTML = "";
  const ready = p.classifier.validated && st.classifier;
  const start = h("button", { class: "btn primary", type: "button", disabled: !ready }, `Classify all ${st.files.n} images`, icon("arrow", 16, { width: 2 }));
  start.addEventListener("click", async () => {
    try { await api.post("/api/batch"); ctx.navigate("results"); } catch (e) { errorToast(e); }
  });
  const perImage = st.system.device.device === "GPU" ? 15 : 30;
  root.append(
    header("Results", ready ? "Everything is ready to classify all your images." : "Validate the classifier on the Preview screen first.", start),
    h("div", { class: "content" }, h("div", { class: "card pad", style: { maxWidth: "620px", display: "flex", flexDirection: "column", gap: "12px" } },
      h("h2", { class: "card-title" }, ready ? `${st.files.n} images to classify` : "Not ready yet"),
      h("p", { class: "muted", style: { lineHeight: "1.55" } }, ready
        ? `Each image is segmented, measured and classified, then the Excel file, plots and statistics are written. Expect about ${duration(perImage * st.files.n)} on this computer (${st.system.device.device === "GPU" ? "GPU" : "CPU only"}). You can stop at any time and resume later.`
        : "Label your crops, preview the classification and click “Classify all images” there."),
      p.imported_classifier ? h("div", { class: "status" }, icon("info"), "Using a classifier reused from another project.") : null,
      !ready ? h("a", { class: "btn", href: p.imported_classifier ? "#/project" : "#/preview", style: { alignSelf: "flex-start" } }, "Go to Preview") : null)));
}

function renderProgress(root, ctx, job) {
  root.innerHTML = "";
  const bar = progressBar(job.progress, true);
  const msg = h("div", { style: { fontSize: "14px" } }, job.message || "Starting…");
  const eta = h("div", { class: "muted", style: { fontSize: "13px" } }, "");
  const stop = h("button", { class: "btn", type: "button" }, "Stop");
  stop.addEventListener("click", async () => {
    if (!(await confirm("Stop classifying?", "Images already done are kept. Click “Classify all images” later to continue where it stopped.", "Stop", true))) return;
    try { await api.post(`/api/jobs/${job.id}/cancel`); } catch (e) { errorToast(e); }
  });
  root.append(
    header("Classifying all images", "Segmenting, measuring and classifying every nucleus. You can keep this window open or come back later.", stop),
    h("div", { class: "content" }, h("div", { class: "card pad", style: { maxWidth: "720px", display: "flex", flexDirection: "column", gap: "14px" } },
      h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, h("div", { class: "spinner" }), h("span", { class: "card-title" }, "Working")),
      bar, msg, eta)));
  api.waitJob(job, (j) => {
    bar.firstChild.style.width = `${j.progress * 100}%`;
    msg.textContent = j.message || "";
    eta.textContent = [j.elapsed_seconds ? `${duration(j.elapsed_seconds)} elapsed` : "", j.eta_seconds ? `about ${duration(j.eta_seconds)} left` : ""].filter(Boolean).join(" · ");
  }).then(async () => {
    await ctx.refresh();
    toast("All images classified");
    ctx.navigate("results");
  }).catch(async (e) => {
    await ctx.refresh();
    if (e.message !== "Cancelled") errorToast(e);
    ctx.navigate("results");
  });
}

function renderDashboard(root, ctx, res) {
  const st = ctx.store.state;
  const p = st.project;
  const cats = p.categories;
  root.innerHTML = "";
  const outdated = st.classifier && p.batch.classifier_hash && st.classifier.hash !== p.batch.classifier_hash;

  const copy = h("button", { class: "btn", type: "button" }, icon("copy"), "Copy folder path");
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(res.folder); toast("Folder path copied"); } catch (e) { toast(res.folder); }
  });
  const dl = h("a", { class: "btn primary", href: "/api/results/excel", download: res.excel_name }, icon("download", 16, { width: 2 }), "Download Excel");

  const unitWord = res.unit === "organoid" ? "organoid" : "image";
  const tiles = h("div", { class: "tiles" },
    tile("Images", fmt(res.n_images), res.unit === "organoid" ? `${res.n_units} organoid${res.n_units > 1 ? "s" : ""}` : ""),
    tile("Nuclei", fmt(res.n_nuclei), "segmented and classified"),
    tile("Living cells", fmt(res.n_living), res.n_nuclei ? `${((100 * res.n_living) / res.n_nuclei).toFixed(1)}% of nuclei · the rest are Dead` : ""),
    tile("Kept for statistics", `${res.n_units_kept} of ${res.n_units}`, res.unit === "organoid" ? `${unitWord}s with ≥ ${res.min_slices} slices` : "images"),
    st.test
      ? h("a", { class: "card tile", href: "#/test/report", style: { color: "inherit", textDecoration: "none" } },
        h("span", { class: "l" }, st.test.stale ? "Test accuracy (earlier classifier)" : "Test accuracy"),
        h("span", { class: "v" }, `${(100 * st.test.balanced_accuracy).toFixed(0)}%`),
        h("span", { class: "s" }, `balanced · 95 % CI ${(100 * st.test.balanced_accuracy_ci[0]).toFixed(0)}–${(100 * st.test.balanced_accuracy_ci[1]).toFixed(0)} % · ${st.test.n} cells`))
      : h("a", { class: "card tile", href: "#/test", style: { color: "inherit", textDecoration: "none" } },
        h("span", { class: "l" }, "Test accuracy"), h("span", { class: "v", style: { color: "#80868E" } }, "–"),
        h("span", { class: "s" }, "not measured yet · open Test")));

  // ---- proportions chart (interactive: the user chooses what makes 100 %)
  const refKey = `nq:${p.dir}:reference`;
  const presets = res.references.filter((r) => r.preset);
  const living = presets.find((r) => r.id === "living") || res.references[0];
  let refCats = (() => {
    try {
      const saved = JSON.parse(localStorage.getItem(refKey) || "null");
      if (saved && saved.every((c) => cats.some((k) => k.id === c)) && saved.length) return saved;
    } catch (e) { /* no storage */ }
    return living.categories.slice();
  })();
  let view = null;

  const chart = h("section", { class: "card pad", style: { flex: "1", minWidth: "0", display: "flex", flexDirection: "column", gap: "14px" } });
  const statsCard = h("section", { class: "card pad", style: { width: "360px", flexShrink: "0", display: "flex", flexDirection: "column", gap: "12px" } });

  const loadView = async () => {
    try { localStorage.setItem(refKey, JSON.stringify(refCats)); } catch (e) { /* no storage */ }
    try {
      view = await api.post("/api/results/view", { categories: refCats });
      drawChart();
      drawStats();
    } catch (e) { errorToast(e); }
  };

  const drawChart = () => {
    chart.innerHTML = "";
    const ref = view.reference;
    const segG = res.groups.length ? h("div", { class: "seg small" },
      h("button", { type: "button", class: groupMode === "organoid" ? "on" : "", onclick: () => { groupMode = "organoid"; drawChart(); } }, res.unit === "organoid" ? "Organoid" : "Image"),
      h("button", { type: "button", class: groupMode === "group" ? "on" : "", onclick: () => { groupMode = "group"; drawChart(); } }, res.group_col || "Group")) : null;
    const svgBtn = h("button", { class: "btn small", type: "button", title: "Download this chart (SVG, white background)" }, icon("download", 14), "SVG");
    chart.append(h("div", { style: { display: "flex", alignItems: "center", gap: "12px" } },
      h("div", { style: { flex: "1", display: "flex", flexDirection: "column", gap: "3px" } },
        h("h2", { class: "card-title" }, "Proportions"),
        h("span", { class: "faint", style: { fontSize: "12.5px" } }, `100 % = ${ref.name}`)),
      segG, svgBtn));

    // 100 % selector: category chips + presets + save
    const chips = h("div", { style: { display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" } },
      h("span", { class: "muted", style: { fontSize: "12.5px", marginRight: "4px" } }, "100 % ="),
      ...cats.map((c) => {
        const on = refCats.includes(c.id);
        const b = h("button", { type: "button", class: `ref-chip ${on ? "on" : ""}`, "aria-pressed": on ? "true" : "false", title: on ? `Leave ${c.name} out of the 100 %` : `Include ${c.name} in the 100 %` },
          h("span", { class: "chip-color", style: { background: on ? c.color : "transparent", borderColor: c.color } }), c.name);
        b.addEventListener("click", () => {
          const next = on ? refCats.filter((x) => x !== c.id) : cats.map((k) => k.id).filter((x) => x === c.id || refCats.includes(x));
          if (!next.length) { toast("Keep at least one category in the 100 %."); return; }
          refCats = next;
          loadView();
        });
        return b;
      }));
    const presetRow = h("div", { style: { display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" } },
      h("span", { class: "faint", style: { fontSize: "12px", marginRight: "4px" } }, "Quick:"),
      ...res.references.map((r) => {
        const on = r.categories.length === refCats.length && r.categories.every((c) => refCats.includes(c));
        return h("button", { type: "button", class: `btn small ${on ? "" : "ghost"}`, style: on ? { borderColor: "#F2C94C", color: "#F2C94C" } : {},
          onclick: () => { refCats = r.categories.slice(); loadView(); } }, r.preset ? r.name[0].toUpperCase() + r.name.slice(1) : r.name);
      }),
      h("span", { style: { flex: "1" } }),
      ref.saved
        ? h("span", { class: "faint", style: { fontSize: "12px", display: "flex", alignItems: "center", gap: "6px" } }, icon("tick", 12, { color: "#5BD68A", width: 2.5 }), "In the Excel file",
          !ref.preset ? h("button", { class: "link", type: "button", style: { fontSize: "12px", marginLeft: "6px" }, onclick: () => removeReference(ref) }, "Remove") : null)
        : h("button", { class: "btn small primary", type: "button", onclick: () => saveReference(ref) }, icon("plus", 14, { width: 2 }), "Save in Excel"));
    chart.append(chips, presetRow);

    const holder = h("div", { style: { width: "100%" } });
    chart.append(holder);
    requestAnimationFrame(() => {
      holder.append(barChart(view, cats, groupMode, holder.clientWidth || 700, DARK, res));
    });
    svgBtn.addEventListener("click", () => {
      const svgEl = barChart(view, cats, groupMode, 900, LIGHT, res, true);
      const blob = new Blob([new XMLSerializer().serializeToString(svgEl)], { type: "image/svg+xml" });
      const a = h("a", { href: URL.createObjectURL(blob), download: `proportions_${ref.name.replace(/[^A-Za-z0-9]+/g, "_")}.svg` });
      document.body.append(a); a.click(); a.remove();
    });
  };

  const saveReference = (ref) => {
    const input = h("input", { class: "input", value: ref.name, "aria-label": "Name of this 100 %" });
    const m = modal({
      title: "Save this 100 % in the Excel file",
      text: "The Excel file and the plots get proportions and statistics for it, next to all nuclei, living cells and stained cells.",
      body: h("label", { class: "field" }, "Name", input),
      actions: [
        { label: "Cancel" },
        { label: "Save", kind: "primary", onClick: async (btn) => {
          btn.disabled = true;
          try {
            const r = await api.post("/api/results/references", { name: input.value, categories: refCats });
            res.references = r.references;
            toast("Added to the Excel file");
            await loadView();
          } catch (e) { errorToast(e); btn.disabled = false; return true; }
        } },
      ],
    });
    setTimeout(() => { input.focus(); input.select(); }, 50);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") m.actions[1].el.click(); });
  };

  const removeReference = async (ref) => {
    if (!(await confirm(`Remove “${ref.name}” from the Excel file?`, "Its proportions, statistics and plots are removed; you can add it again at any time.", "Remove"))) return;
    try {
      const r = await api.del(`/api/results/references/${ref.id}`);
      res.references = r.references;
      await loadView();
    } catch (e) { errorToast(e); }
  };

  // ---- statistics (for the chosen 100 %)
  const drawStats = () => {
    statsCard.innerHTML = "";
    statsCard.append(h("h2", { class: "card-title" }, "Statistics"));
    const rows = view.stats;
    if (rows.length) {
      statsCard.append(h("div", { class: "muted", style: { fontSize: "12.5px", lineHeight: "1.5" } },
        `${rows[0].Test} between ${view.group_col === "Genotype" ? "genotypes" : "clones"}, one value per ${unitWord}, % of ${view.reference.name}, Holm-corrected.`));
      statsCard.append(h("div", { class: "table" },
        h("div", { class: "tr head", style: { padding: "0", display: "grid", gridTemplateColumns: "1fr 90px 50px" } }, h("span", {}, "Category"), h("span", { style: { textAlign: "right" } }, "p (Holm)"), h("span", {})),
        ...rows.map((r) => h("div", { class: "tr", style: { padding: "0", display: "grid", gridTemplateColumns: "1fr 90px 50px" }, title: `${r["n per group"]} · medians ${r["Median per group"]}${r["Dunn (Holm)"] ? " · " + r["Dunn (Holm)"] : ""}` },
          h("span", {}, r.Category), h("span", { class: "mono", style: { textAlign: "right" } }, r["p (Holm)"] == null ? "–" : r["p (Holm)"] < 0.001 ? r["p (Holm)"].toExponential(1) : r["p (Holm)"].toFixed(3)),
          h("span", { style: { textAlign: "right", color: r.Significance && r.Significance !== "ns" ? "#F2C94C" : "#80868E" } }, r.Significance || "")))),
        h("div", { class: "faint", style: { fontSize: "12px" } }, "Hover a row for n and medians. All details are in the Excel file, sheet “statistics”."));
    } else {
      statsCard.append(h("div", { class: "empty" },
        h("div", { class: "ic" }, icon("chart", 20, { color: "#A3A9B1" })),
        h("div", { style: { fontSize: "15px", fontWeight: "600" } }, "Only one group"),
        h("p", { class: "muted", style: { fontSize: "13.5px", lineHeight: "1.55" } },
          `${res.groups.length === 1 ? `Every ${unitWord} here is ${res.groups[0]}. ` : ""}Add images from another genotype and NucleiQuant compares them ${unitWord} by ${unitWord}: Mann-Whitney for two groups, Kruskal-Wallis then Dunn for more, Holm-corrected.`)));
    }
    for (const w of view.warnings.filter((w) => !w.startsWith("Only one group"))) statsCard.append(h("div", { class: "banner" }, w));
    statsCard.append(h("button", { class: "link", type: "button", style: { alignSelf: "flex-start", fontSize: "13px" }, onclick: async () => {
      try { await api.post("/api/results/refresh"); toast("Excel file and plots updated"); ctx.navigate("results"); } catch (e) { errorToast(e); }
    } }, "Recalculate after editing genotypes or settings"));
  };
  chart.append(h("div", { class: "muted", style: { fontSize: "13px" } }, "Loading…"));
  loadView();

  // ---- per image
  const cols = `2fr repeat(${cats.length + 1}, minmax(0, 1fr)) 64px`;
  const rows = showAll ? res.per_image : res.per_image.slice(0, 6);
  const fieldsOf = (r) => ({ organoid: r.Organoid, slice: r.Slice });
  const table = h("section", { class: "card", style: { overflow: "hidden" } },
    h("div", { style: { display: "flex", alignItems: "center", height: "46px", padding: "0 20px" } }, h("h2", { class: "card-title" }, "Per image")),
    h("div", { class: "table" },
      h("div", { class: "tr head", style: { display: "grid", gridTemplateColumns: cols, borderTop: "1px solid #1F2328" } },
        h("span", {}, "Image"), ...cats.map((c) => h("span", { style: { textAlign: "right" } }, c.name)), h("span", { style: { textAlign: "right" } }, "Total"), h("span", {})),
      ...rows.map((r, i) => h("div", { class: `tr ${i % 2 ? "alt" : ""}`, style: { display: "grid", gridTemplateColumns: cols } },
        h("span", { title: r.Image_name, style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, shortName(r.Image_name, r.Organoid ? fieldsOf(r) : null)),
        ...cats.map((c) => h("span", { class: "mono", style: { textAlign: "right", color: c.id === "dead" || c.id === "unstained" ? "#A3A9B1" : "#EDEEF0" } }, fmt(r[c.name]))),
        h("span", { class: "mono", style: { textAlign: "right" } }, fmt(r.Total)),
        h("span", { style: { textAlign: "right" } }, h("a", { href: `#/view/${encodeURIComponent(r.Image_name)}`, style: { fontSize: "13px" } }, "View"))))),
    res.per_image.length > 6 ? h("button", { class: "btn ghost", type: "button", style: { width: "100%", borderRadius: "0", borderTop: "1px solid #1F2328" }, onclick: () => { showAll = !showAll; renderDashboard(root, ctx, res); } },
      showAll ? "Show fewer" : `Show all ${res.per_image.length} images`) : null);

  root.append(
    header("Results", `${res.n_images} images classified. Everything is saved in ${res.folder}`, copy, dl),
    h("div", { class: "content" },
      outdated ? h("div", { class: "banner", style: { flexDirection: "row", alignItems: "center" } },
        h("span", { style: { flex: "1" } }, "You retrained the classifier after these results were made. Classify again to update them (segmentations are reused, so it's faster)."),
        h("button", { class: "btn small primary", type: "button", onclick: async () => { try { await api.post("/api/classifier/validate"); await api.post("/api/batch"); ctx.navigate("results"); } catch (e) { errorToast(e); } } }, "Classify again")) : null,
      tiles,
      h("div", { style: { display: "flex", gap: "20px", alignItems: "flex-start" } }, chart, statsCard),
      table,
      h("div", { class: "faint", style: { fontSize: "12.5px", lineHeight: "1.6" } },
        "In the results folder: the Excel file, plots (PNG and SVG), one table per image with every nucleus (objects/), label images (labels/), Fiji ROI sets coloured by category (rois/) and a quick-look picture of each image (overlays/).")));
}

// ---- vertical stacked bar chart --------------------------------------------------------
const DARK = { text: "#A3A9B1", strong: "#EDEEF0", grid: "#22262B", axis: "#2B3036", bg: null, font: "Geist, system-ui, sans-serif" };
const LIGHT = { text: "#333333", strong: "#000000", grid: "#E3E3E3", axis: "#999999", bg: "#FFFFFF", font: "Helvetica, Arial, sans-serif" };

function luminance(hex) {
  const c = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(c.slice(i, i + 2), 16) / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function barChart(view, allCats, mode, width, theme, res, standalone = false) {
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs = {}, text) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== null && v !== undefined) e.setAttribute(k, v);
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const cats = allCats.filter((c) => view.reference.categories.includes(c.id));
  const grouped = mode === "group" && view.group_bars.length;
  const bars = grouped
    ? view.group_bars.map((g) => ({ label: g.label, group: "", values: g.values, sd: g.sd, sub: `${g.n_units} ${res.unit}${g.n_units > 1 ? "s" : ""}`, n: g.n, excluded: false }))
    : view.bars.map((b) => ({ ...b, sub: b.excluded ? "excluded" : `${b.slices} sl.` }));
  const groups = [];
  for (const b of bars) {
    if (!groups.length || groups[groups.length - 1].name !== b.group) groups.push({ name: b.group, bars: [] });
    groups[groups.length - 1].bars.push(b);
  }
  const H = 360, top = 16, left = 52, right = 12;
  const rotate = !grouped && bars.length > 14;
  const bottom = grouped ? 46 : rotate ? 96 : 70;
  const plotW = width - left - right, plotH = H - top - bottom;
  const gap = groups.length > 1 ? 24 : 0;
  const slot = (plotW - gap * (groups.length - 1)) / Math.max(bars.length, 1);
  const bw = Math.min(64, slot * 0.72);
  const y = (v) => top + plotH * (1 - v / 100);
  const svg = el("svg", { xmlns: NS, width, height: H + (standalone ? 40 : 0), viewBox: `0 0 ${width} ${H + (standalone ? 40 : 0)}`, "font-family": theme.font, role: "img", "aria-label": `Proportions, 100 % = ${view.reference.name}` });
  if (theme.bg) svg.append(el("rect", { x: 0, y: 0, width, height: H + 40, fill: theme.bg }));
  const tip = document.querySelector(".tooltip") || (() => { const t = document.createElement("div"); t.className = "tooltip hidden"; document.body.append(t); return t; })();
  for (const v of [0, 25, 50, 75, 100]) {
    svg.append(el("line", { x1: left, x2: width - right, y1: y(v), y2: y(v), stroke: v === 0 ? theme.axis : theme.grid, "stroke-width": 1 }));
    svg.append(el("text", { x: left - 8, y: y(v) + 4, "font-size": 11, fill: theme.text, "text-anchor": "end" }, `${v}%`));
  }
  svg.append(el("text", { x: 14, y: top + plotH / 2, "font-size": 11.5, fill: theme.text, "text-anchor": "middle", transform: `rotate(-90 14 ${top + plotH / 2})` }, `% of ${view.reference.name}`));
  let x = left;
  groups.forEach((g, gi) => {
    const gx0 = x;
    for (const b of g.bars) {
      const cx = x + slot / 2;
      let acc = 0;
      const gEl = el("g", { opacity: b.excluded ? 0.35 : 1 });
      for (const c of cats) {
        const v = b.values[c.id];
        if (!v) continue;
        const y0 = y(acc + v), hgt = y(acc) - y(acc + v);
        const rect = el("rect", { x: cx - bw / 2, y: y0, width: bw, height: Math.max(hgt, 0.5), fill: c.color });
        if (!standalone) {
          const count = b.counts ? ` · ${b.counts[c.id].toLocaleString()} of ${b.n.toLocaleString()} cells` : "";
          const extra = b.sd && b.sd[c.id] != null ? ` ± ${b.sd[c.id].toFixed(1)} (SD, ${b.sub})` : count;
          rect.addEventListener("mousemove", (e) => { tip.textContent = `${b.label} · ${c.name}: ${v.toFixed(1)}%${extra}`; tip.classList.remove("hidden"); tip.style.left = `${e.clientX + 14}px`; tip.style.top = `${e.clientY + 14}px`; });
          rect.addEventListener("mouseleave", () => tip.classList.add("hidden"));
        }
        gEl.append(rect);
        if (hgt >= 15 && bw >= 26) {
          gEl.append(el("text", { x: cx, y: y0 + hgt / 2 + 4, "font-size": 10.5, "text-anchor": "middle", fill: luminance(c.color) > 0.55 ? "#0B0C0E" : "#FFFFFF", "pointer-events": "none" }, `${Math.round(v)}%`));
        }
        acc += v;
      }
      svg.append(gEl);
      const ly = H - bottom + 16;
      if (rotate) {
        svg.append(el("text", { x: cx, y: ly, "font-size": 11, fill: theme.strong, "text-anchor": "end", transform: `rotate(-45 ${cx} ${ly})` }, b.label));
      } else {
        svg.append(el("text", { x: cx, y: ly, "font-size": 11.5, fill: theme.strong, "text-anchor": "middle" }, b.label));
        svg.append(el("text", { x: cx, y: ly + 14, "font-size": 10, fill: theme.text, "text-anchor": "middle" }, b.sub));
      }
      x += slot;
    }
    if (g.name) {
      const gy = H - 14;
      svg.append(el("line", { x1: gx0 + 4, x2: x - 4, y1: gy - 12, y2: gy - 12, stroke: theme.axis }));
      svg.append(el("text", { x: (gx0 + x) / 2, y: gy, "font-size": 11.5, "font-weight": 600, fill: theme.strong, "text-anchor": "middle" }, g.name));
    }
    if (gi < groups.length - 1) x += gap;
  });
  if (standalone) {
    let lx = left;
    for (const c of cats) {
      svg.append(el("rect", { x: lx, y: H + 14, width: 10, height: 10, rx: 2, fill: c.color }));
      const t = el("text", { x: lx + 14, y: H + 23, "font-size": 11, fill: theme.strong }, c.name);
      svg.append(t);
      lx += 24 + c.name.length * 6.5;
    }
  }
  return svg;
}

function tile(label, value, sub) {
  return h("div", { class: "card tile" }, h("span", { class: "l" }, label), h("span", { class: "v" }, value), h("span", { class: "s" }, sub));
}

// ---- QC view of one classified image -------------------------------------------------
async function renderView(root, ctx, image) {
  const st = ctx.store.state;
  const p = st.project;
  const cats = p.categories;
  const res = await api.get("/api/results");
  const names = res ? res.per_image.map((r) => r.Image_name) : [];
  const idx = names.indexOf(image);
  const row = res ? res.per_image[idx] : null;
  root.innerHTML = "";
  const go = (k) => ctx.navigate(`view/${encodeURIComponent(names[(idx + k + names.length) % names.length])}`);
  root.append(header(row && row.Organoid ? `${row.Organoid} · ${row.Slice}` : image.replace(/\.tiff?$/i, ""), image,
    h("button", { class: "btn", type: "button", onclick: () => go(-1), "aria-label": "Previous image" }, icon("back")),
    h("button", { class: "btn", type: "button", onclick: () => go(1), "aria-label": "Next image" }, icon("arrow")),
    h("a", { class: "btn", href: "#/results" }, "Back to results")));
  const viewerEl = h("div", { class: "viewer" });
  const loading = h("div", { class: "float center" }, h("div", { class: "spinner" }), h("span", { class: "muted" }, "Loading image…"));
  const legend = h("div", { class: "float tr" }, ...cats.map((c) => h("span", { class: "legend-item" }, h("span", { class: "sq", style: { borderColor: c.color } }), c.name)));
  viewerEl.append(loading, legend);
  const inspector = h("aside", { class: "inspector" });
  root.append(h("div", { class: "workspace" }, h("div", { class: "stage" }, viewerEl), inspector));
  const display = { uncertain: false };
  try {
    const enc = encodeURIComponent(image);
    const [raw, labels, outlines, pred] = await Promise.all([
      api.binary(`/api/images/${enc}/raw`), api.binary(`/api/images/${enc}/labels`),
      api.binary(`/api/images/${enc}/outlines`), api.get(`/api/images/${enc}/predictions`)]);
    const [C, H, W] = raw.shape;
    const map = new Map();
    pred.labels.forEach((l, i) => map.set(l, { cat: pred.category[i], prob: pred.probability[i] }));
    viewer = new Viewer(viewerEl, {});
    const thr = p.settings.uncertain_threshold;
    viewer.style = (lab) => {
      const pr = map.get(lab);
      if (!pr) return null;
      if (display.uncertain && pr.prob >= thr) return null;
      const c = cats[pr.cat];
      return { stroke: c ? c.color : "#FFF", weight: 1, halo: true };
    };
    viewer.setData({ raw: new Uint16Array(raw.buffer), C, H, W, labels: new Uint32Array(labels.buffer), outlines: api.parseOutlines(outlines.buffer) });
    viewer.setChannels(p.channels.map((c, i) => ({ ...c, visible: true, ...viewer.autoRange(i) })));
    loading.remove();

    const counts = new Array(cats.length).fill(0);
    for (const v of map.values()) if (v.cat >= 0) counts[v.cat]++;
    const total = map.size;
    const sec = h("section", { class: "insp-section", style: { gap: "10px", padding: "0 4px" } },
      h("div", { style: { display: "flex", alignItems: "baseline" } }, h("h2", { class: "eyebrow", style: { flex: "1", fontSize: "12px" } }, "This image"),
        h("span", { class: "mono faint", style: { fontSize: "12px" } }, `${fmt(total)} nuclei`)));
    cats.forEach((c, i) => {
      const pct = total ? (100 * counts[i]) / total : 0;
      sec.append(h("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } },
        h("div", { style: { display: "flex", alignItems: "center", gap: "10px", fontSize: "13.5px" } },
          h("span", { class: "swatch", style: { width: "10px", height: "10px", borderRadius: "3px", background: c.color } }), h("span", { style: { flex: "1" } }, c.name),
          h("span", { class: "mono", style: { fontSize: "12.5px" } }, fmt(counts[i])),
          h("span", { class: "mono faint", style: { fontSize: "12.5px", width: "48px", textAlign: "right" } }, `${pct.toFixed(1)}%`)),
        h("div", { class: "bar" }, h("span", { style: { width: `${pct}%`, background: c.color } }))));
    });
    const disp = h("section", { class: "insp-section" }, h("div", { class: "insp-head" }, h("h2", {}, "Display")),
      h("div", { class: "row-toggle", style: { padding: "0 4px" } }, h("span", {}, `Uncertain cells only (< ${Math.round(thr * 100)}%)`),
        switchEl(false, (v) => { display.uncertain = v; viewer.draw(); }, "Uncertain cells only")),
      h("div", { class: "row-toggle", style: { padding: "0 4px" } }, h("span", {}, "Outlines"), switchEl(true, (v) => { viewer.showOutlines = v; viewer.draw(); }, "Outlines")),
      h("div", { class: "faint", style: { fontSize: "12.5px", padding: "4px", lineHeight: "1.5" } }, "Large images are shown at reduced resolution. The full-resolution labels and Fiji ROIs are in the results folder."));
    inspector.append(sec, disp);
    keyHandler = (e) => {
      if (e.key === "ArrowRight" || e.key === "]") go(1);
      else if (e.key === "ArrowLeft" || e.key === "[") go(-1);
      else if (e.key.toLowerCase() === "f") viewer.fit();
    };
    document.addEventListener("keydown", keyHandler);
  } catch (e) {
    loading.remove();
    errorToast(e);
  }
}

export function destroy() {
  clearTimeout(timer);
  if (viewer) { viewer.destroy(); viewer = null; }
  if (keyHandler) { document.removeEventListener("keydown", keyHandler); keyHandler = null; }
}
