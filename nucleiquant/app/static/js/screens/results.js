// Step 6 — Classify all images, then counts, proportions, statistics and QC views.
import * as api from "../api.js";
import { Viewer } from "../viewer.js";
import { h, icon, errorToast, toast, confirm, fmt, duration, progressBar, switchEl, shortName } from "../ui.js";

let timer = null;
let viewer = null;
let keyHandler = null;
let showAll = false;
let measure = "living";
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
    tile("Kept for statistics", `${res.n_units_kept} of ${res.n_units}`, res.unit === "organoid" ? `${unitWord}s with ≥ ${res.min_slices} slices` : "images"));

  // ---- proportions chart
  const chart = h("section", { class: "card pad", style: { flex: "1", minWidth: "0", display: "flex", flexDirection: "column", gap: "18px" } });
  const drawChart = () => {
    chart.innerHTML = "";
    const shown = cats.filter((c) => measure === "all" || c.id !== "dead");
    const segM = h("div", { class: "seg small" },
      h("button", { type: "button", class: measure === "living" ? "on" : "", onclick: () => { measure = "living"; drawChart(); } }, "% living"),
      h("button", { type: "button", class: measure === "all" ? "on" : "", onclick: () => { measure = "all"; drawChart(); } }, "% all nuclei"));
    const segG = res.groups.length ? h("div", { class: "seg small" },
      h("button", { type: "button", class: groupMode === "organoid" ? "on" : "", onclick: () => { groupMode = "organoid"; drawChart(); } }, res.unit === "organoid" ? "Organoid" : "Image"),
      h("button", { type: "button", class: groupMode === "group" ? "on" : "", onclick: () => { groupMode = "group"; drawChart(); } }, res.group_col || "Group")) : null;
    chart.append(h("div", { style: { display: "flex", alignItems: "center", gap: "12px" } },
      h("h2", { class: "card-title", style: { flex: "1" } }, measure === "living" ? "Cell types among living cells" : "Cell types among all nuclei"), segM, segG));
    let rows = res.bars;
    if (groupMode === "group" && res.groups.length) {
      rows = res.groups.map((g) => {
        const members = res.bars.filter((b) => b.group === g && !b.excluded);
        const avg = {};
        for (const c of cats) {
          const v = members.map((b) => b[measure][c.id]).filter((x) => x != null);
          avg[c.id] = v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
        }
        return { label: g, slices: null, n: members.length, excluded: false, [measure]: avg };
      });
    }
    const list = h("div", { style: { display: "flex", flexDirection: "column", gap: "12px" } });
    for (const b of rows) {
      const vals = b[measure];
      const stack = h("span", { class: "stack" });
      for (const c of shown) {
        const v = vals[c.id];
        if (!v) continue;
        stack.append(h("span", { style: { flexGrow: v, background: c.color }, title: `${c.name}: ${v.toFixed(1)}%` }, v >= 7 ? `${v.toFixed(1)}%` : ""));
      }
      list.append(h("div", { class: "stack-row", style: { opacity: b.excluded ? "0.45" : "1" } },
        h("span", { class: "lab" }, h("span", { style: { fontSize: "13.5px", fontWeight: "500" } }, b.label),
          h("span", { class: "faint", style: { fontSize: "12px" } },
            b.n != null ? `mean of ${b.n} ${unitWord}${b.n > 1 ? "s" : ""}` : `${b.slices} slice${b.slices > 1 ? "s" : ""}${b.excluded ? " · excluded" : ""}${b.group ? ` · ${b.group}` : ""}`)),
        stack));
    }
    chart.append(list, h("div", { style: { display: "flex", flexWrap: "wrap", gap: "16px", paddingLeft: "136px", fontSize: "12.5px", color: "#A3A9B1" } },
      ...shown.map((c) => h("span", { class: "legend-item" }, h("span", { class: "swatch", style: { width: "10px", height: "10px", borderRadius: "3px", background: c.color } }), c.name))));
  };
  drawChart();

  // ---- statistics
  const stats = h("section", { class: "card pad", style: { width: "380px", flexShrink: "0", display: "flex", flexDirection: "column", gap: "12px" } },
    h("h2", { class: "card-title" }, "Statistics"));
  if (res.stats.length) {
    const living = res.stats.filter((r) => r.Measure === "% of living cells");
    stats.append(h("div", { class: "muted", style: { fontSize: "12.5px", lineHeight: "1.5" } },
      `${living[0] ? living[0].Test : ""} between ${res.group_col === "Genotype" ? "genotypes" : "clones"}, per ${unitWord}, % of living cells, Holm-corrected.`));
    const tbl = h("div", { class: "table" },
      h("div", { class: "tr head", style: { padding: "0", display: "grid", gridTemplateColumns: "1fr 90px 50px" } }, h("span", {}, "Category"), h("span", { style: { textAlign: "right" } }, "p (Holm)"), h("span", {})),
      ...living.map((r) => h("div", { class: "tr", style: { padding: "0", display: "grid", gridTemplateColumns: "1fr 90px 50px" }, title: `${r["n per group"]} · medians ${r["Median per group"]}${r["Dunn (Holm)"] ? " · " + r["Dunn (Holm)"] : ""}` },
        h("span", {}, r.Category), h("span", { class: "mono", style: { textAlign: "right" } }, r["p (Holm)"] == null ? "–" : r["p (Holm)"] < 0.001 ? r["p (Holm)"].toExponential(1) : r["p (Holm)"].toFixed(3)),
        h("span", { style: { textAlign: "right", color: r.Significance && r.Significance !== "ns" ? "#F2C94C" : "#80868E" } }, r.Significance || ""))));
    stats.append(tbl, h("div", { class: "faint", style: { fontSize: "12px" } }, "Details (n, medians, pairwise Dunn tests) are in the Excel file, sheet “statistics”."));
  } else {
    stats.append(h("div", { class: "empty" },
      h("div", { class: "ic" }, icon("chart", 20, { color: "#A3A9B1" })),
      h("div", { style: { fontSize: "15px", fontWeight: "600" } }, "Only one group"),
      h("p", { class: "muted", style: { fontSize: "13.5px", lineHeight: "1.55" } },
        `${res.groups.length === 1 ? `Every ${unitWord} here is ${res.groups[0]}. ` : ""}Add images from another genotype and NucleiQuant compares them ${unitWord} by ${unitWord}: Mann-Whitney for two groups, Kruskal-Wallis then Dunn for more, Holm-corrected.`)));
  }
  for (const w of res.stat_warnings.filter((w) => !w.startsWith("Only one group"))) stats.append(h("div", { class: "banner" }, w));
  stats.append(h("button", { class: "link", type: "button", style: { alignSelf: "flex-start", fontSize: "13px" }, onclick: async () => {
    try { await api.post("/api/results/refresh"); toast("Excel file and plots updated"); ctx.navigate("results"); } catch (e) { errorToast(e); }
  } }, "Recalculate after editing genotypes or settings"));

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
      h("div", { style: { display: "flex", gap: "20px", alignItems: "flex-start" } }, chart, stats),
      table,
      h("div", { class: "faint", style: { fontSize: "12.5px", lineHeight: "1.6" } },
        "In the results folder: the Excel file, plots (PNG and SVG), one table per image with every nucleus (objects/), label images (labels/), Fiji ROI sets coloured by category (rois/) and a quick-look picture of each image (overlays/).")));
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
