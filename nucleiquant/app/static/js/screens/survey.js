// Step 2 — Intensity survey and choice of training images.
import * as api from "../api.js";
import { h, icon, errorToast, confirm, progressBar, tooltip, fmt, shortName } from "../ui.js";

const svg = (tag, attrs = {}, ...children) => h(tag, { ...attrs, svg: true }, ...children);

function quantile(sorted, q) {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

export async function render(root, ctx) {
  const tip = tooltip();

  async function waitForSurvey() {
    const st = ctx.store.state;
    const job = (st.jobs || []).find((j) => j.kind === "survey");
    root.innerHTML = "";
    const bar = progressBar(0, true);
    const msg = h("div", { class: "muted", style: { fontSize: "13px" } }, "Starting…");
    root.append(
      h("header", { class: "header" }, h("div", { class: "titles" }, h("h1", {}, "Intensity survey"), h("p", {}, "Measuring every image. This takes a few seconds per image."))),
      h("div", { class: "content" }, h("div", { class: "card pad", style: { maxWidth: "560px", display: "flex", flexDirection: "column", gap: "14px" } },
        h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, h("div", { class: "spinner" }), h("span", { class: "card-title" }, "Measuring image intensities")),
        bar, msg)));
    if (!job) {
      const j = await api.post("/api/survey");
      await api.waitJob(j, (x) => { bar.firstChild.style.width = `${x.progress * 100}%`; msg.textContent = x.message || "Measuring…"; });
    } else {
      await api.waitJob(job, (x) => { bar.firstChild.style.width = `${x.progress * 100}%`; msg.textContent = x.message || "Measuring…"; });
    }
    await ctx.refresh();
  }

  let st = ctx.store.state;
  if (!st.project.survey_done || (st.jobs || []).some((j) => j.kind === "survey")) {
    try { await waitForSurvey(); } catch (e) { errorToast(e); return; }
    st = ctx.store.state;
  }

  let data = await api.get("/api/survey");

  const draw = () => {
    st = ctx.store.state;
    const p = st.project;
    const ch = data.channel;
    const chName = p.channels[ch] ? p.channels[ch].name : `Channel ${ch + 1}`;
    const selected = new Map(data.selection.map((s) => [s.image, s.role]));
    const entries = data.entries.slice().sort((a, b) => a.values[ch] - b.values[ch]);
    root.innerHTML = "";

    const toggle = async (image) => {
      const sel = data.selection.filter((s) => s.image !== image);
      if (!selected.has(image)) sel.push({ image, role: "Manual" });
      else {
        const crop = p.crops.find((c) => c.image === image);
        const n = crop ? Object.values(st.labels.per_crop[crop.id] || {}).reduce((a, b) => a + b, 0) : 0;
        if (n && !(await confirm("Remove this training image?", `Its crop has ${n} labeled nuclei; they will be deleted when crops are updated.`, "Remove", true))) return;
      }
      try { data = await api.post("/api/survey/selection", { selection: sel }); await ctx.refresh(); draw(); } catch (e) { errorToast(e); }
    };

    // ---- plot: one row per clone
    const groups = [...new Set(entries.map((e) => e.group))].sort();
    const vals = entries.map((e) => e.values[ch]);
    let vmin = Math.min(...vals), vmax = Math.max(...vals);
    const pad = (vmax - vmin) * 0.08 || 1;
    vmin -= pad; vmax += pad;
    const W = 1060, rowH = 64, top = 34, left = 120;
    const Hh = top + rowH * groups.length + 34;
    const x = (v) => left + ((v - vmin) / (vmax - vmin)) * (W - left - 20);
    const plot = svg("svg", { width: "100%", viewBox: `0 0 ${W} ${Hh}`, role: "img", "aria-label": `Mean ${chName} intensity per image`, style: { display: "block", fontFamily: "var(--sans)", overflow: "visible" } });
    groups.forEach((g, gi) => {
      const cy = top + gi * rowH + rowH / 2;
      const gv = entries.filter((e) => e.group === g).map((e) => e.values[ch]).sort((a, b) => a - b);
      const q1 = quantile(gv, 0.25), q3 = quantile(gv, 0.75), med = quantile(gv, 0.5);
      plot.append(
        svg("text", { x: 0, y: cy - 2, "font-size": 14, "font-weight": 600, fill: "#EDEEF0" }, g || "All images"),
        svg("text", { x: 0, y: cy + 16, "font-size": 12, fill: "#80868E" }, `${data.genotypes[g] ? data.genotypes[g] + " · " : ""}${gv.length}`),
        svg("line", { x1: x(gv[0]), x2: x(gv[gv.length - 1]), y1: cy, y2: cy, stroke: "#2B3036", "stroke-width": 1.5 }),
        svg("rect", { x: x(q1), y: cy - 17, width: Math.max(2, x(q3) - x(q1)), height: 34, rx: 5, fill: "#1B1F24", stroke: "#2B3036" }),
        svg("line", { x1: x(med), x2: x(med), y1: cy - 17, y2: cy + 17, stroke: "#80868E", "stroke-width": 1.5 }));
      [["Q10 · dim", 0.1], ["Q50 · typical", 0.5], ["Q90 · bright", 0.9]].forEach(([label, q]) => {
        const qx = x(quantile(gv, q));
        plot.append(svg("line", { x1: qx, x2: qx, y1: cy - 28, y2: cy + 28, stroke: "#F2C94C", "stroke-opacity": 0.45, "stroke-dasharray": "3 4" }));
        if (gi === 0) plot.append(svg("text", { x: qx, y: 14, "font-size": 11.5, fill: "#F2C94C", "text-anchor": "middle" }, label));
      });
      // beeswarm: nudge overlapping points up/down
      const placed = [];
      entries.filter((e) => e.group === g).forEach((e) => {
        const px = x(e.values[ch]);
        let dy = 0;
        for (const offset of [0, -13, 13, -26, 26]) {
          if (placed.every((q) => Math.hypot(q.x - px, q.y - (cy + offset)) >= 13)) { dy = offset; break; }
        }
        placed.push({ x: px, y: cy + dy });
        const isSel = selected.has(e.image);
        const gEl = svg("g", { style: { cursor: "pointer" } },
          isSel ? svg("circle", { cx: px, cy: cy + dy, r: 11, fill: "none", stroke: "#F2C94C", "stroke-width": 2 }) : null,
          svg("circle", { cx: px, cy: cy + dy, r: 6.5, fill: isSel ? "#F2C94C" : "#6B7178", stroke: "#111316", "stroke-width": 1.5 }));
        gEl.addEventListener("mousemove", (ev) => tip.show(`${shortName(e.image, e.fields)} · ${fmt(e.values[ch], 1)}${isSel ? " · " + selected.get(e.image) : ""}`, ev.clientX, ev.clientY));
        gEl.addEventListener("mouseleave", () => tip.hide());
        gEl.addEventListener("click", () => { tip.hide(); toggle(e.image); });
        plot.append(gEl);
      });
    });
    const axisY = top + rowH * groups.length + 8;
    plot.append(svg("line", { x1: left, x2: W - 20, y1: axisY, y2: axisY, stroke: "#2B3036" }));
    const step = niceStep((vmax - vmin) / 6);
    for (let v = Math.ceil(vmin / step) * step; v <= vmax; v += step) {
      plot.append(svg("text", { x: x(v), y: axisY + 18, "font-size": 11.5, fill: "#80868E", "text-anchor": "middle" }, fmt(v)));
    }

    const seg = h("div", { class: "seg", role: "group", "aria-label": "Channel" },
      ...p.channels.map((c, i) => h("button", { type: "button", class: i === ch ? "on" : "", "aria-pressed": i === ch ? "true" : "false",
        onclick: async () => { try { data = await api.post("/api/survey/channel", { channel: i }); await ctx.refresh(); draw(); } catch (e) { errorToast(e); } } }, c.name)));

    // ---- table
    const table = h("div", { class: "card table", style: { overflow: "hidden" } },
      h("div", { class: "tr head" }, h("span", { style: { width: "28px" } }), h("span", { style: { width: "200px" } }, "Image"),
        h("span", { style: { width: "90px" } }, "Clone"), h("span", { style: { width: "90px" } }, "Organoid"), h("span", { style: { width: "70px" } }, "Slice"),
        h("span", { style: { width: "250px" } }, `Mean ${chName}`), h("span", { style: { flex: "1" } }, "Training"),
        h("button", { class: "link", type: "button", style: { fontSize: "12.5px", textTransform: "none", letterSpacing: "0" }, onclick: async () => {
          try { data = await api.post("/api/survey/reset"); await ctx.refresh(); draw(); } catch (e) { errorToast(e); }
        } }, "Reset to automatic")));
    const [lo, hi] = [Math.min(...vals), Math.max(...vals)];
    for (const e of entries) {
      const isSel = selected.has(e.image);
      const cb = h("input", { type: "checkbox", checked: isSel, "aria-label": `Use ${e.image} for training` });
      cb.addEventListener("change", () => toggle(e.image));
      const frac = hi > lo ? (e.values[ch] - lo) / (hi - lo) : 1;
      table.append(h("div", { class: `tr ${isSel ? "sel" : ""}` },
        h("span", { style: { width: "28px", display: "flex" } }, cb),
        h("span", { class: "mono", style: { width: "200px", color: isSel ? "#EDEEF0" : "#A3A9B1", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, title: e.image }, e.image.replace(/\.tiff?$/i, "")),
        h("span", { style: { width: "90px", color: "#A3A9B1" } }, e.fields.clone || "–"),
        h("span", { style: { width: "90px", color: "#A3A9B1" } }, e.fields.organoid || "–"),
        h("span", { style: { width: "70px", color: "#A3A9B1" } }, e.fields.slice || "–"),
        h("span", { style: { width: "250px", display: "flex", alignItems: "center", gap: "10px" } },
          h("span", { class: "bar", style: { width: "160px", height: "4px" } }, h("span", { style: { width: `${Math.max(2, frac * 100)}%`, background: isSel ? "#F2C94C" : "#5A6068" } })),
          h("span", { class: "mono", style: { color: isSel ? "#EDEEF0" : "#A3A9B1" } }, fmt(e.values[ch], 1))),
        h("span", { style: { flex: "1" } }, isSel ? h("span", { class: "pill" }, selected.get(e.image)) : null)));
    }

    const n = data.selection.length;
    const go = h("button", { class: "btn primary", type: "button", disabled: n === 0 }, `Create ${n} crop${n === 1 ? "" : "s"}`, icon("arrow", 16, { width: 2 }));
    go.addEventListener("click", async () => {
      const losing = p.crops.filter((c) => !selected.has(c.image));
      const nLost = losing.reduce((a, c) => a + Object.values(st.labels.per_crop[c.id] || {}).reduce((x, y) => x + y, 0), 0);
      if (nLost && !(await confirm("Update the crops?", `${losing.length} crop${losing.length > 1 ? "s" : ""} will be removed with ${nLost} labeled nuclei.`, "Update crops", true))) return;
      try { await api.post("/api/crops"); ctx.navigate("crops"); } catch (e) { errorToast(e); }
    });

    root.append(
      h("header", { class: "header" },
        h("div", { class: "titles" }, h("h1", {}, "Intensity survey"),
          h("p", {}, "Train on dim, typical and bright images so the classifier copes with staining variation. Three are picked per clone.")),
        go),
      h("div", { class: "content" },
        h("section", { class: "card pad", style: { display: "flex", flexDirection: "column", gap: "14px" } },
          h("div", { style: { display: "flex", alignItems: "center", gap: "16px" } },
            h("h2", { class: "card-title", style: { flex: "1" } }, "Mean intensity inside nuclei, per image"), seg),
          plot),
        table));
  };
  draw();
}

function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p;
}

export function destroy() {
  const t = document.querySelector(".tooltip");
  if (t) t.classList.add("hidden");
}
