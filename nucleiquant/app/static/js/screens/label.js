// Steps 4 and 5 — Label cells, then preview the classification.
import * as api from "../api.js";
import { Viewer } from "../viewer.js";
import { h, icon, errorToast, toast, confirm, modal, colorPopover, switchEl, fmt, shortName, progressBar } from "../ui.js";

let viewer = null;
let keyHandlers = null;
let current = { cropId: null, category: null };
const cache = new Map();

function storageKey(ctx) { return `nq:${ctx.store.state.project.dir}:channels`; }
function loadChannelPrefs(ctx) {
  try { return JSON.parse(localStorage.getItem(storageKey(ctx)) || "null"); } catch (e) { return null; }
}
function saveChannelPrefs(ctx, chans) {
  try { localStorage.setItem(storageKey(ctx), JSON.stringify(chans.map(({ visible, lo, hi }) => ({ visible, lo, hi })))); } catch (e) { /* private mode */ }
}

export function featureLabel(name, channels) {
  const chName = (i) => (channels[+i] ? channels[+i].name : `ch${+i + 1}`);
  const groups = { int: "intensity", norm: "normalised", rad: "radial", ring: "30 px ring", peri: "perinuclear", ctr: "contrast", tex: "texture", lbp: "LBP", grad: "gradient", xch: "channels", shape: "shape", ctx: "density" };
  const m = name.match(/^([a-z]+)_(?:c(\d+)(?:c(\d+))?_)?(.*)$/);
  if (!m) return name;
  const [, g, a, b, rest] = m;
  const what = `${groups[g] || g} ${rest.replace(/c(\d+)/g, (_, i) => chName(i)).replace(/_/g, " ")}`.trim();
  if (a === undefined) return what;
  return `${b !== undefined ? `${chName(a)}×${chName(b)}` : chName(a)} · ${what}`;
}

async function loadCrop(ctx, cropId, withPredictions) {
  const pr = ctx.store.state.project;
  const crop = [...pr.crops, ...(pr.test_crops || [])].find((c) => c.id === cropId);
  const key = `${ctx.store.state.project.dir}|${cropId}|${crop ? crop.built : ""}`;
  let d = cache.get(key);
  if (!d) {
    const [raw, labels, outlines, objects, annotations] = await Promise.all([
      api.binary(`/api/crops/${cropId}/raw`),
      api.binary(`/api/crops/${cropId}/labels`),
      api.binary(`/api/crops/${cropId}/outlines`),
      api.get(`/api/crops/${cropId}/objects`),
      api.get(`/api/crops/${cropId}/annotations`),
    ]);
    const [C, H, W] = raw.shape;
    const edge = new Set();
    objects.labels.forEach((l, i) => { if (objects.edge[i]) edge.add(l); });
    d = {
      C, H, W,
      raw: new Uint16Array(raw.buffer),
      labels: new Uint32Array(labels.buffer),
      outlines: api.parseOutlines(outlines.buffer),
      edge,
      annotations: new Map(Object.entries(annotations).map(([k, v]) => [Number(k), v])),
      predictions: null,
    };
    cache.set(key, d);
  }
  if (withPredictions && !d.predictions) {
    const p = await api.get(`/api/crops/${cropId}/predictions`);
    const map = new Map();
    p.labels.forEach((l, i) => map.set(l, { cat: p.category[i], prob: p.probability[i] }));
    d.predictions = map;
  }
  return d;
}

export async function render(root, ctx, route) {
  const preview = route === "preview";
  // Test mode: labeling of the independent test crops, blind to predictions
  const test = route === "test";
  const CK = test ? "testCropId" : "cropId";
  const LB = () => (test ? ctx.store.state.test_labels : ctx.store.state.labels);
  let st = ctx.store.state;
  const p = () => ctx.store.state.project;
  const readyCrops = () => (test ? p().test_crops : p().crops).filter((c) => c.status === "ready");
  if (!readyCrops().length) { ctx.navigate("crops"); return; }
  if (!readyCrops().some((c) => c.id === current[CK])) current[CK] = readyCrops()[0].id;
  const cats = () => p().categories;
  if (!cats().some((c) => c.id === current.category)) current.category = (cats().find((c) => !c.builtin) || cats()[0]).id;

  // Preview needs a trained classifier (train now if needed)
  if (preview && (!st.classifier || st.project.classifier.stale)) {
    const ok = await train(root, ctx);
    if (!ok) { ctx.navigate("label"); return; }
    st = ctx.store.state;
    cache.forEach((d) => { d.predictions = null; });
  }

  const display = { outlines: true, fill: true, uncertain: false, highlight: false, erase: false };
  let channels = null;
  let data = null;
  const threshold = () => p().settings.uncertain_threshold;

  // ---- layout
  root.innerHTML = "";
  const header = h("header", { class: "header" });
  const viewerEl = h("div", { class: "viewer", tabindex: "0", "aria-label": "Image viewer" });
  const chip = h("div", { class: "float tl" });
  const legend = h("div", { class: "float tr hidden" });
  const zoomText = h("span", { class: "mono", style: { width: "52px", textAlign: "center", fontSize: "12.5px" } }, "100%");
  const zoomBox = h("div", { class: "float bl" },
    h("button", { class: "icon-btn", type: "button", "aria-label": "Zoom out", onclick: () => viewer.zoomBy(1 / 1.4) }, icon("minus", 16, { width: 2 })),
    zoomText,
    h("button", { class: "icon-btn", type: "button", "aria-label": "Zoom in", onclick: () => viewer.zoomBy(1.4) }, icon("plus", 16, { width: 2 })),
    h("span", { style: { width: "1px", height: "18px", background: "rgba(255,255,255,0.12)", margin: "0 4px" } }),
    h("button", { class: "icon-btn", type: "button", "aria-label": "Fit to window", onclick: () => viewer.fit() }, icon("fit")));
  const eraseChip = h("div", { class: "float br hidden", style: { color: "#FF6B6B" } }, "Erase mode · click a nucleus to remove its label · E to stop");
  const zoomHint = h("div", { class: "float br hidden" }, "Scroll to zoom in, then click nuclei");
  const loading = h("div", { class: "float center hidden" }, h("div", { class: "spinner" }), h("span", { class: "muted" }, "Loading crop…"));
  viewerEl.append(chip, legend, zoomBox, eraseChip, zoomHint, loading);
  const film = h("div", { class: "filmstrip" });
  const inspector = h("aside", { class: "inspector" });
  root.append(header, h("div", { class: "workspace" }, h("div", { class: "stage" }, viewerEl, film), inspector));

  // ---- header
  const drawHeader = () => {
    st = ctx.store.state;
    header.innerHTML = "";
    const lbl = LB();
    if (test) {
      const go = h("button", { class: "btn primary", type: "button", disabled: lbl.total < 2 }, "Evaluate accuracy", icon("arrow", 16, { width: 2 }));
      go.addEventListener("click", async () => {
        if (!lbl.complete && !(await shortfallDialog(lbl, "Evaluate anyway"))) return;
        go.disabled = true;
        try { await api.post("/api/test/evaluate"); await ctx.refresh(); ctx.navigate("test/report"); } catch (e) { errorToast(e); go.disabled = false; }
      });
      const hereLeft = lbl.needed_per_crop[current[CK]] || 0;
      header.append(
        h("div", { class: "titles" }, h("h1", {}, "Test set"),
          h("p", {}, `Label cells blind: the classifier's answers are hidden. Recommended: ${lbl.target} of each category in each test crop.`)),
        h("span", { class: "hint" }, lbl.complete ? "Every test crop is complete" : hereLeft ? `This crop: ${hereLeft} to go (recommended)` : "This crop is complete"),
        ...(st.test ? [h("a", { class: "btn", href: "#/test/report" }, "Report")] : []),
        go);
    } else if (!preview) {
      const go = h("button", { class: "btn primary", type: "button", disabled: !lbl.ready }, "Preview classification", icon("arrow", 16, { width: 2 }));
      go.addEventListener("click", async () => {
        if (!lbl.complete && !(await shortfallDialog(lbl))) return;
        ctx.navigate("preview");
      });
      const hereLeft = lbl.needed_per_crop[current[CK]] || 0;
      const hint = !lbl.ready ? "Label at least two categories"
        : lbl.complete ? "Every crop has enough labels"
          : hereLeft ? `This crop: ${hereLeft} to go (recommended)` : "This crop is complete · check the others";
      header.append(
        h("div", { class: "titles" }, h("h1", {}, "Label cells"),
          h("p", {}, `Choose a category, then click nuclei. Recommended: ${lbl.target} of each category in every crop — if a crop has fewer, label what it has.`)),
        h("span", { class: "hint" }, hint),
        go);
    } else {
      const stale = !!st.project.classifier.stale;
      const n = st.files.n;
      const go = h("button", { class: "btn primary", type: "button", disabled: stale }, `Classify all ${n} image${n > 1 ? "s" : ""}`, icon("arrow", 16, { width: 2 }));
      go.addEventListener("click", async () => {
        try {
          await api.post("/api/classifier/validate");
          await api.post("/api/batch");
          ctx.navigate("results");
        } catch (e) { errorToast(e); }
      });
      header.append(
        h("div", { class: "titles" }, h("h1", {}, "Preview"),
          h("p", {}, "Every nucleus is coloured by its predicted category. Click a wrong one to relabel it, then retrain.")),
        h("a", { class: "btn", href: "#/label" }, "Keep labeling"),
        go);
    }
  };

  // Recommended labels missing: list them, let the user continue anyway
  const shortfallDialog = (lbl, goLabel = "Preview anyway") => new Promise((resolve) => {
    const catName = (id) => (cats().find((c) => c.id === id) || { name: id }).name;
    const byCrop = new Map();
    for (const s of lbl.shortfalls) {
      if (lbl.unused.includes(s.category)) continue;
      if (!byCrop.has(s.crop_id)) byCrop.set(s.crop_id, []);
      byCrop.get(s.crop_id).push(`${catName(s.category)} ${s.n}/${lbl.target}`);
    }
    const lines = [];
    for (const [cropId, items] of byCrop) {
      const crop = readyCrops().find((c) => c.id === cropId);
      lines.push(h("div", { style: { display: "flex", gap: "10px", fontSize: "13px" } },
        h("span", { style: { width: "92px", flexShrink: "0", fontWeight: "500" } }, crop ? shortName(crop.image, crop.fields) : cropId),
        h("span", { class: "muted" }, items.join(" · "))));
    }
    const unused = lbl.unused.map(catName);
    let decided = false;
    modal({
      title: test ? "Some test crops have fewer labels than recommended" : "Some crops have fewer labels than recommended",
      text: test
        ? `${lbl.target} of each category per test crop gives every category a similar weight in the accuracy. Fewer test cells only make the confidence intervals wider.`
        : `${lbl.target} of each category per crop keeps the training balanced across dim, typical and bright images. If a crop simply doesn't contain that many cells of a category, it's fine to continue.`,
      body: h("div", { style: { display: "flex", flexDirection: "column", gap: "8px", maxHeight: "260px", overflow: "auto" } },
        ...lines,
        unused.length ? h("div", { class: "banner", style: { marginTop: "6px" } },
          test ? `${unused.join(", ")} ${unused.length > 1 ? "have" : "has"} no test cells: ${unused.length > 1 ? "their" : "its"} accuracy can't be measured.`
            : `${unused.join(", ")} ${unused.length > 1 ? "have" : "has"} no labels at all: the classifier won't be able to call any cell ${unused.join(" or ")}.`) : null),
      actions: [
        { label: "Keep labeling", onClick: () => { decided = true; resolve(false); } },
        { label: goLabel, kind: "primary", onClick: () => { decided = true; resolve(true); } },
      ],
      onClose: () => { if (!decided) resolve(false); },
    });
  });

  // ---- viewer
  const catIndex = () => new Map(cats().map((c, i) => [c.id, i]));
  const styleFn = (lab) => {
    const ann = data.annotations.get(lab);
    const cat = ann ? cats().find((c) => c.id === ann) : null;
    if (!preview) {
      if (data.edge.has(lab)) return { stroke: "#FFFFFF", alpha: 0.25, weight: 1 };
      if (cat) return { stroke: cat.color, fill: display.fill ? cat.color : null, weight: 2 };
      return { stroke: "#F2C94C", alpha: 0.6, weight: 1 };
    }
    const pr = data.predictions && data.predictions.get(lab);
    if (!pr) return null;
    if (display.uncertain && pr.prob >= threshold()) return null;
    const pc = cats()[pr.cat];
    return { stroke: pc ? pc.color : "#FFFFFF", fill: display.highlight && cat ? cat.color : null, weight: display.highlight && cat ? 2 : 1, halo: true };
  };

  viewer = new Viewer(viewerEl, {
    onClick: (lab) => clickLabel(lab, false),
    onRightClick: (lab) => clickLabel(lab, true),
    onView: (v) => {
      zoomText.textContent = `${Math.round(v.zoom * 100)}%`;
      zoomHint.classList.toggle("hidden", v.zoom >= 0.9 || display.erase);
    },
    onHover: (lab, e) => hoverInfo(lab, e),
    onHoverMove: (lab, e) => hoverInfo(lab, e),
  });
  viewer.style = styleFn;
  window.nqViewer = viewer;

  const hoverTip = h("div", { class: "tooltip hidden" });
  document.body.append(hoverTip);
  const hoverInfo = (lab, e) => {
    if (!lab || !e) { hoverTip.classList.add("hidden"); return; }
    const ann = data.annotations.get(lab);
    const cat = ann ? cats().find((c) => c.id === ann) : null;
    let text = cat ? `Labeled ${cat.name}` : data.edge.has(lab) ? "Cut by the crop edge" : "";
    if (preview && data.predictions) {
      const pr = data.predictions.get(lab);
      if (pr) text = `${cats()[pr.cat] ? cats()[pr.cat].name : "?"} · ${Math.round(pr.prob * 100)}%` + (cat ? ` · labeled ${cat.name}` : "");
    }
    if (!text) { hoverTip.classList.add("hidden"); return; }
    hoverTip.textContent = text;
    hoverTip.classList.remove("hidden");
    hoverTip.style.left = `${e.clientX + 14}px`;
    hoverTip.style.top = `${e.clientY + 14}px`;
  };

  async function clickLabel(lab, erase) {
    if (!lab || !data) return;
    if (data.edge.has(lab)) { toast("This nucleus is cut by the crop edge, so it can't be labeled."); return; }
    const prev = data.annotations.get(lab);
    const next = erase || display.erase || prev === current.category ? null : current.category;
    if (!prev && !next) return;
    if (next) data.annotations.set(lab, next); else data.annotations.delete(lab);
    viewer.draw();
    try {
      const counts = await api.post("/api/labels", { crop_id: current[CK], label: lab, category_id: next });
      ctx.store.state.labels = counts.labels;
      ctx.store.state.test_labels = counts.test_labels;
      if (ctx.store.state.classifier) ctx.store.state.project.classifier.stale = true;
      drawHeader();
      drawInspector();
      drawFilm();
      refreshSidebarSoon();
    } catch (e) {
      if (prev) data.annotations.set(lab, prev); else data.annotations.delete(lab);
      viewer.draw();
      errorToast(e);
    }
  }

  let sideTimer = null;
  const refreshSidebarSoon = () => { clearTimeout(sideTimer); sideTimer = setTimeout(() => ctx.refresh().catch(() => {}), 800); };

  // ---- channels
  const setupChannels = () => {
    const prefs = loadChannelPrefs(ctx);
    channels = p().channels.map((c, i) => {
      const auto = viewer.autoRange(i);
      const pref = prefs && prefs[i];
      return { name: c.name, color: c.color, visible: pref ? pref.visible : true, lo: pref ? pref.lo : auto.lo, hi: pref ? pref.hi : auto.hi, max: Math.max(auto.max, pref ? pref.hi : 0, 255) };
    });
    viewer.setChannels(channels);
  };

  // ---- crop switching
  async function showCrop(cropId) {
    current[CK] = cropId;
    loading.classList.remove("hidden");
    try {
      data = await loadCrop(ctx, cropId, preview);
      viewer.setData(data);
      if (!channels) setupChannels(); else viewer.setChannels(channels.map((c, i) => ({ ...c, max: Math.max(c.max, viewer.autoRange(i).max) })));
      const crop = readyCrops().find((c) => c.id === cropId);
      const all = readyCrops();
      chip.innerHTML = "";
      chip.append(h("span", { style: { fontWeight: "600" } }, shortName(crop.image, crop.fields)),
        h("span", { class: "faint" }, `${test ? "Test crop" : "Crop"} ${all.findIndex((c) => c.id === cropId) + 1} of ${all.length}`));
      drawLegend();
      drawFilm();
      drawInspector();
      drawHeader();
    } catch (e) { errorToast(e); }
    loading.classList.add("hidden");
  }

  const drawLegend = () => {
    legend.innerHTML = "";
    legend.classList.toggle("hidden", !preview);
    if (!preview) return;
    for (const c of cats()) legend.append(h("span", { class: "legend-item" }, h("span", { class: "sq", style: { borderColor: c.color } }), c.name));
  };

  const drawFilm = () => {
    st = ctx.store.state;
    film.innerHTML = "";
    const target = LB().target;
    for (const c of readyCrops()) {
      const per = LB().per_crop[c.id] || {};
      const done = cats().reduce((a, k) => a + Math.min(per[k.id] || 0, target), 0);
      const goal = cats().length * target;
      const bar = h("span", { class: "minibar" }, ...cats().map((k) => (per[k.id] ? h("span", { style: { flexGrow: Math.min(per[k.id], target), background: k.color } }) : null)),
        done < goal ? h("span", { style: { flexGrow: goal - done, background: "transparent" } }) : null);
      const item = h("button", { class: `film-item ${c.id === current[CK] ? "on" : ""}`, type: "button", "aria-current": c.id === current[CK] ? "true" : null, onclick: () => showCrop(c.id) },
        h("img", { src: `/api/crops/${c.id}/film`, alt: "" }),
        h("span", { class: "info" }, h("span", { class: "n" }, shortName(c.image, c.fields)),
          h("span", { class: "s", style: { display: "flex", alignItems: "center", gap: "5px" } },
            preview ? `${fmt(c.n_nuclei)} nuclei` : [done >= goal ? icon("tick", 12, { color: "#5BD68A", width: 2.5 }) : null, `${done} / ${goal}`]),
          !preview ? bar : null));
      film.append(item);
    }
    film.append(h("div", { class: "hints" },
      ...(preview
        ? [["1–9", "relabel"], ["R", "retrain"], ["U", "uncertain only"], ["H", "hide outlines"]]
        : [["1–9", "category"], ["E", "erase"], ["H", "hide outlines"], ["Scroll", "zoom"]]).map(([k, t]) => h("span", {}, h("b", {}, k), ` ${t}`))));
  };

  const colorChoices = () => [
    { title: "Same as a channel", items: p().channels.map((ch) => ({ color: ch.color, label: ch.name })) },
    { title: "Other colours", items: ctx.store.state.category_colors.map((col) => ({ color: col })) },
  ];

  // ---- inspector
  let adding = false;
  // The new-category draft survives redraws of the inspector (e.g. when a crop finishes loading)
  const draft = { name: "", color: null };
  let showConfusion = false;
  const drawInspector = () => {
    st = ctx.store.state;
    inspector.innerHTML = "";
    const target = LB().target;

    if (preview) inspector.append(classifierSection());

    // Categories
    const catSec = h("section", { class: "insp-section" },
      h("div", { class: "insp-head" }, h("h2", {}, preview ? "Correct with" : "Categories"),
        !preview && !test ? h("button", { class: "btn ghost small", type: "button", onclick: () => { adding = true; drawInspector(); } }, icon("plus", 14, { width: 2 }), "Add") : null));
    const here = LB().per_crop[current[CK]] || {};
    cats().forEach((c, i) => {
      const n = LB().per_category[c.id] || 0;
      const nHere = here[c.id] || 0;
      const on = c.id === current.category;
      const sw = h("span", { class: "swatch pick", style: { background: c.color }, title: "Change colour", role: "button", "aria-label": `Change the colour of ${c.name}` });
      sw.addEventListener("click", (e) => {
        e.stopPropagation();
        colorPopover(sw, colorChoices(), async (col) => {
          try { await api.patch(`/api/categories/${c.id}`, { color: col }); await ctx.refresh(); drawInspector(); drawLegend(); drawFilm(); viewer.draw(); } catch (err) { errorToast(err); }
        });
      });
      const name = h("span", { class: "name", title: c.builtin ? "Always included" : "Double-click to rename" }, c.name,
        c.builtin ? icon("lock", 12, { color: "#80868E", width: 2 }) : null);
      if (!c.builtin && !test) {
        name.addEventListener("dblclick", (e) => {
          e.stopPropagation();
          const inp = h("input", { class: "input small", value: c.name, style: { width: "130px" } });
          name.replaceWith(inp);
          inp.focus(); inp.select();
          const done = async () => {
            if (inp.value.trim() && inp.value.trim() !== c.name) {
              try { await api.patch(`/api/categories/${c.id}`, { name: inp.value }); await ctx.refresh(); } catch (err) { errorToast(err); }
            }
            drawInspector(); drawLegend();
          };
          inp.addEventListener("keydown", (ev) => { ev.stopPropagation(); if (ev.key === "Enter") inp.blur(); if (ev.key === "Escape") { inp.value = c.name; inp.blur(); } });
          inp.addEventListener("blur", done);
          inp.addEventListener("click", (ev) => ev.stopPropagation());
        });
      }
      const del = !c.builtin && !preview && !test ? h("button", { class: "icon-btn", type: "button", "aria-label": `Delete ${c.name}`, style: { width: "22px", height: "22px", opacity: "0.6" } }, icon("trash", 13)) : null;
      if (del) del.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!(await confirm(`Delete “${c.name}”?`, n ? `Its ${n} labels will be removed too.` : "", "Delete", true))) return;
        try {
          await api.del(`/api/categories/${c.id}`);
          cache.forEach((d) => { for (const [k, v] of d.annotations) if (v === c.id) d.annotations.delete(k); });
          await ctx.refresh(); drawInspector(); drawHeader(); drawFilm(); viewer.draw();
        } catch (err) { errorToast(err); }
      });
      const row = h("button", { class: `cat ${on ? "on" : ""}`, type: "button", "aria-pressed": on ? "true" : "false" },
        h("span", { class: "top" }, sw, name,
          !preview && nHere >= target ? icon("tick", 14, { color: "#5BD68A", width: 2.5 }) : null,
          h("span", { class: "count", title: preview ? "Labels in all crops" : "Labels in this crop / recommended" },
            preview ? `${n}` : [String(nHere), h("span", {}, ` / ${target}`)]),
          del,
          i < 9 ? h("kbd", {}, String(i + 1)) : null),
        !preview ? h("span", { class: "cat-sub" },
          h("span", { class: "bar", style: { flex: "1" } }, h("span", { style: { width: `${Math.min(100, (100 * nHere) / target)}%`, background: c.color } })),
          h("span", { class: "faint", title: "Labels in all crops" }, `${n} in all crops`)) : null);
      row.addEventListener("click", () => { current.category = c.id; display.erase = false; eraseChip.classList.add("hidden"); drawInspector(); });
      catSec.append(row);
    });
    if (adding) {
      const used = new Set(cats().map((c) => c.color));
      if (!draft.color) draft.color = st.category_colors.find((col) => !used.has(col)) || st.category_colors[0];
      const inp = h("input", { class: "input small", placeholder: "Category name, e.g. PAX6+", style: { flex: "1", minWidth: "0" }, value: draft.name });
      inp.addEventListener("input", () => { draft.name = inp.value; });
      const colBtn = h("button", { type: "button", class: "swatch-btn", title: "Colour of this category", "aria-label": "Choose a colour", style: { background: draft.color } });
      colBtn.addEventListener("click", () => colorPopover(colBtn, colorChoices(), (col) => { draft.color = col; colBtn.style.background = col; inp.focus(); }));
      const close = () => { adding = false; draft.name = ""; draft.color = null; drawInspector(); };
      const add = async () => {
        if (!inp.value.trim()) { close(); return; }
        try { await api.post("/api/categories", { name: inp.value, color: draft.color }); await ctx.refresh(); const nc = cats()[cats().length - 1]; current.category = nc.id; } catch (e) { errorToast(e); return; }
        close(); drawFilm(); drawHeader(); drawLegend();
      };
      inp.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") add(); if (e.key === "Escape") close(); });
      catSec.append(h("div", { class: "cat-edit" }, colBtn, inp, h("button", { class: "btn small primary", type: "button", onclick: add }, "Add")));
      setTimeout(() => inp.focus(), 0);
    }
    if (test) {
      const left = LB().needed_per_crop[current[CK]] || 0;
      catSec.append(h("div", { class: "faint", style: { fontSize: "12.5px", padding: "4px 4px 0", lineHeight: "1.5" } },
        `Test crops come from images the classifier never saw. Label what you are sure of, without looking for “hard” or “easy” cells. ${left ? `This crop: ${left} to go.` : "This crop is complete."} These labels are never used for training.`));
    } else if (!preview) {
      const left = LB().needed_per_crop[current[CK]] || 0;
      catSec.append(h("div", { class: "faint", style: { fontSize: "12.5px", padding: "4px 4px 0", lineHeight: "1.5" } },
        LB().total === 0
          ? `Click nuclei to label them with the selected category. Recommended: ${target} of each category in each crop. Click a colour square to change a category's colour.`
          : left > 0
            ? `This crop: ${left} to go. If it has fewer than ${target} cells of a category, label what you find and move on. Cells with two markers need their own category (e.g. “S+T”).`
            : `This crop has ${target} of each category. ${LB().complete ? "All crops are complete." : "Use ] to go to the next crop."}`));
    }
    inspector.append(catSec);

    if (preview && data && data.predictions) inspector.append(cropCountsSection());

    // Channels
    const chSec = h("section", { class: "insp-section" },
      h("div", { class: "insp-head" }, h("h2", {}, "Channels"),
        h("button", { class: "btn ghost small", type: "button", onclick: () => {
          channels = channels.map((c, i) => { const a = viewer.autoRange(i); return { ...c, lo: a.lo, hi: a.hi }; });
          viewer.setChannels(channels); saveChannelPrefs(ctx, channels); drawInspector();
        } }, "Auto contrast")));
    (channels || []).forEach((c, i) => {
      const rangeText = h("span", { class: "range" }, `${fmt(c.lo)} – ${fmt(c.hi)}`);
      const fill = h("span", { class: "fill", style: { background: c.color } });
      const max = Math.max(c.max, c.hi + 1);
      const loIn = h("input", { type: "range", min: 0, max, value: c.lo, "aria-label": `${c.name} minimum` });
      const hiIn = h("input", { type: "range", min: 0, max, value: c.hi, "aria-label": `${c.name} maximum` });
      const upd = () => {
        let lo = Number(loIn.value), hi = Number(hiIn.value);
        if (hi <= lo) { if (document.activeElement === loIn) lo = hi - 1; else hi = lo + 1; }
        channels[i] = { ...channels[i], lo, hi };
        rangeText.textContent = `${fmt(lo)} – ${fmt(hi)}`;
        fill.style.left = `${(lo / max) * 100}%`; fill.style.width = `${((hi - lo) / max) * 100}%`;
        viewer.setChannels(channels);
      };
      loIn.addEventListener("input", upd); hiIn.addEventListener("input", upd);
      loIn.addEventListener("change", () => saveChannelPrefs(ctx, channels)); hiIn.addEventListener("change", () => saveChannelPrefs(ctx, channels));
      fill.style.left = `${(c.lo / max) * 100}%`; fill.style.width = `${((c.hi - c.lo) / max) * 100}%`;
      const eye = h("button", { class: "icon-btn", type: "button", "aria-label": `${c.visible ? "Hide" : "Show"} ${c.name}` }, icon(c.visible ? "eye" : "eyeoff"));
      eye.addEventListener("click", () => { channels[i] = { ...channels[i], visible: !c.visible }; viewer.setChannels(channels); saveChannelPrefs(ctx, channels); drawInspector(); });
      chSec.append(h("div", { class: `channel ${c.visible ? "" : "off"}` },
        h("div", { class: "top" }, eye, h("span", { class: "swatch", style: { width: "10px", height: "10px", borderRadius: "3px", background: c.color } }), h("span", { class: "name" }, c.name), rangeText),
        h("div", { class: "dual" }, h("span", { class: "track" }), fill, loIn, hiIn)));
    });
    inspector.append(chSec);

    // Display
    const disp = h("section", { class: "insp-section" }, h("div", { class: "insp-head" }, h("h2", {}, "Display")));
    const toggleRow = (label, key, after) => h("div", { class: "row-toggle", style: { padding: "0 4px" } }, h("span", {}, label),
      switchEl(display[key], (v) => { display[key] = v; if (after) after(v); viewer.draw(); }, label));
    if (preview) {
      disp.append(toggleRow(`Uncertain cells only (< ${Math.round(threshold() * 100)}%)`, "uncertain"));
      disp.append(toggleRow("Highlight my labels", "highlight"));
    }
    disp.append(toggleRow("Outlines", "outlines", (v) => { viewer.showOutlines = v; }));
    if (!preview) disp.append(toggleRow("Fill labeled cells", "fill"));
    inspector.append(disp);
  };

  const classifierSection = () => {
    st = ctx.store.state;
    const info = st.classifier;
    const cv = info.cross_validation;
    const sec = h("section", { class: "insp-section", style: { gap: "12px", padding: "0 4px" } },
      h("div", { class: "insp-head", style: { padding: "0" } }, h("h2", {}, "Classifier")));
    if (st.project.classifier.stale) {
      sec.append(h("div", { class: "banner" }, "Your labels changed since the last training. Retrain to update the colours.",
        h("button", { class: "btn small primary", type: "button", onclick: retrain }, icon("refresh", 14), "Retrain")));
    }
    sec.append(h("div", { style: { display: "flex", flexDirection: "column", gap: "4px" } },
      h("div", { class: "big-number" }, cv.accuracy != null ? `${Math.round(cv.accuracy * 100)}%` : "–"),
      h("div", { class: "muted", style: { fontSize: "13px", lineHeight: "1.45" } },
        cv.scheme === "leave-one-crop-out" ? `correct on a crop it didn't train on, over the ${cv.per_fold.length} crops` : "correct on held-out labels (5-fold)")),
      h("div", { class: "muted", style: { fontSize: "13px" } }, `Trained on ${info.n_labels} labels · ${Object.keys(info.labels_per_category).length} categories · ${info.n_features} features`));
    if (!st.project.classifier.stale) {
      sec.append(h("button", { class: "btn block", type: "button", onclick: retrain }, icon("refresh"), "Retrain"));
    }
    const toggle = h("button", { class: "link", type: "button", style: { color: "#A3A9B1", display: "flex", alignItems: "center", gap: "8px", fontSize: "13.5px" } },
      icon(showConfusion ? "down" : "chevron"), "Where it gets confused");
    toggle.addEventListener("click", () => { showConfusion = !showConfusion; drawInspector(); });
    sec.append(toggle);
    if (showConfusion) {
      const names = cv.categories.map((id) => (cats().find((c) => c.id === id) || { name: id }).name);
      const tbl = h("table", { class: "confusion" },
        h("tr", {}, h("th", {}, "true ↓ / predicted →"), ...names.map((n) => h("th", {}, n.slice(0, 5)))),
        ...cv.confusion.map((row, i) => h("tr", {}, h("th", { style: { textAlign: "left" } }, names[i]),
          ...row.map((v, j) => h("td", { style: { color: i === j ? "#5BD68A" : v ? "#FFB4B4" : "#5A6068" } }, v)))));
      sec.append(h("div", { style: { overflowX: "auto" } }, tbl),
        h("div", { class: "faint", style: { fontSize: "12px", lineHeight: "1.5" } }, "Rows: your label. Columns: what the classifier said on a crop it didn't see. Off-diagonal numbers are the mistakes; label more cells like those."),
        h("div", { class: "eyebrow", style: { marginTop: "6px" } }, "Most useful features"),
        ...info.top_features.slice(0, 8).map((f) => h("div", { style: { display: "flex", gap: "8px", fontSize: "12.5px" } },
          h("span", { style: { flex: "1" }, class: "muted" }, featureLabel(f.feature, p().channels)),
          h("span", { class: "mono faint" }, f.importance.toFixed(3)))));
    }
    return sec;
  };

  const cropCountsSection = () => {
    const counts = new Array(cats().length).fill(0);
    let uncertain = 0;
    for (const v of data.predictions.values()) { if (v.cat >= 0) counts[v.cat]++; if (v.prob < threshold()) uncertain++; }
    const total = data.predictions.size;
    const sec = h("section", { class: "insp-section", style: { gap: "10px", padding: "0 4px" } },
      h("div", { style: { display: "flex", alignItems: "baseline" } }, h("h2", { class: "eyebrow", style: { flex: "1", fontSize: "12px" } }, "This crop"),
        h("span", { class: "mono faint", style: { fontSize: "12px" } }, `${fmt(total)} nuclei`)));
    cats().forEach((c, i) => {
      const pct = total ? (100 * counts[i]) / total : 0;
      sec.append(h("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } },
        h("div", { style: { display: "flex", alignItems: "center", gap: "10px", fontSize: "13.5px" } },
          h("span", { class: "swatch", style: { width: "10px", height: "10px", borderRadius: "3px", background: c.color } }), h("span", { style: { flex: "1" } }, c.name),
          h("span", { class: "mono", style: { fontSize: "12.5px" } }, fmt(counts[i])),
          h("span", { class: "mono faint", style: { fontSize: "12.5px", width: "48px", textAlign: "right" } }, `${pct.toFixed(1)}%`)),
        h("div", { class: "bar" }, h("span", { style: { width: `${pct}%`, background: c.color } }))));
    });
    sec.append(h("div", { class: "faint", style: { fontSize: "12.5px" } }, `${fmt(uncertain)} uncertain (below ${Math.round(threshold() * 100)}%)`));
    return sec;
  };

  async function retrain() {
    const ok = await train(null, ctx);
    if (!ok) return;
    cache.forEach((d) => { d.predictions = null; });
    await showCrop(current[CK]);
    drawHeader();
  }

  // ---- keyboard
  const onKey = (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA") return;
    if (document.querySelector(".overlay")) return;
    const k = e.key.toLowerCase();
    if (/^[1-9]$/.test(e.key)) {
      const c = cats()[Number(e.key) - 1];
      if (c) { current.category = c.id; display.erase = false; eraseChip.classList.add("hidden"); drawInspector(); }
    } else if (k === "e" && !preview) {
      display.erase = !display.erase; eraseChip.classList.toggle("hidden", !display.erase);
    } else if (k === "h") {
      viewer.showOutlines = false; viewer.draw();
    } else if (k === "f") {
      viewer.fit();
    } else if (k === "+" || k === "=") viewer.zoomBy(1.4);
    else if (k === "-") viewer.zoomBy(1 / 1.4);
    else if (k === "]" || k === "[") {
      const all = readyCrops();
      const i = all.findIndex((c) => c.id === current[CK]);
      const j = (i + (k === "]" ? 1 : -1) + all.length) % all.length;
      showCrop(all[j].id);
    } else if (k === "r" && preview) retrain();
    else if (k === "u" && preview) { display.uncertain = !display.uncertain; drawInspector(); viewer.draw(); }
    else return;
    e.preventDefault();
  };
  const onKeyUp = (e) => { if (e.key.toLowerCase() === "h") { viewer.showOutlines = display.outlines; viewer.draw(); } };
  document.addEventListener("keydown", onKey);
  document.addEventListener("keyup", onKeyUp);
  keyHandlers = { onKey, onKeyUp, hoverTip };

  drawHeader();
  drawInspector();
  await showCrop(current[CK]);
}

// Train with a progress modal. Returns true when done.
async function train(root, ctx) {
  const bar = progressBar(0.02, true);
  const msg = h("div", { class: "muted", style: { fontSize: "13px" } }, "Starting…");
  const overlay = h("div", { class: "overlay" }, h("div", { class: "modal", style: { width: "440px" } },
    h("div", { class: "modal-head" }, h("h2", {}, "Training the classifier"), h("p", {}, "The forest is trained on your labels and tested on each crop in turn.")),
    h("div", { class: "modal-body", style: { paddingBottom: "22px" } }, bar, msg)));
  document.body.append(overlay);
  try {
    const job = await api.post("/api/train");
    await api.waitJob(job, (j) => { bar.firstChild.style.width = `${Math.max(2, j.progress * 100)}%`; msg.textContent = j.message || "Training…"; });
    await ctx.refresh();
    return true;
  } catch (e) {
    errorToast(e);
    return false;
  } finally {
    overlay.remove();
  }
}

export function destroy() {
  if (viewer) { viewer.destroy(); viewer = null; }
  if (keyHandlers) {
    document.removeEventListener("keydown", keyHandlers.onKey);
    document.removeEventListener("keyup", keyHandlers.onKeyUp);
    keyHandlers.hoverTip.remove();
    keyHandlers = null;
  }
}

export function clearCache() { cache.clear(); }
