// Step 3 — Training crops: placement (draggable) and segmentation progress.
import * as api from "../api.js";
import { h, icon, errorToast, confirm, fmt, shortName, progressBar } from "../ui.js";

let timer = null;

export async function render(root, ctx) {
  let version = Date.now();

  const draw = () => {
    const st = ctx.store.state;
    const p = st.project;
    const jobs = (st.jobs || []).filter((j) => j.kind === "crops" || j.kind === "crop");
    const job = jobs[0];
    root.innerHTML = "";
    const ready = p.crops.length > 0 && p.crops.every((c) => c.status === "ready");
    const start = h("button", { class: "btn primary", type: "button", disabled: !ready }, "Start labeling", icon("arrow", 16, { width: 2 }));
    start.addEventListener("click", () => ctx.navigate("label"));

    const grid = h("div", { class: "crop-grid" });
    for (const c of p.crops) {
      const fields = c.fields;
      const nLabels = Object.values(st.labels.per_crop[c.id] || {}).reduce((a, b) => a + b, 0);
      const thumbBox = h("div", { class: "crop-thumb" });
      const body = h("div", { class: "crop-body" },
        h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, h("h2", {}, shortName(c.image, fields)), h("span", { class: "pill" }, c.role || "Manual")),
        h("div", { class: "muted", style: { fontSize: "13px" } },
          c.w ? `${fmt(c.w)} × ${fmt(c.h)} px` + (c.pixel_size ? ` · ${fmt(c.w * c.pixel_size)} × ${fmt(c.h * c.pixel_size)} µm` : "") : c.image));
      const isRunning = job && job.message && job.message.startsWith(c.image);
      if (c.status === "ready") {
        body.append(h("div", { class: "status", style: { fontSize: "13px" } }, icon("check", 16, { color: "#5BD68A", width: 2 }),
          h("span", { style: { color: "#EDEEF0" } }, `${fmt(c.n_nuclei)} nuclei`), `· ${fmt(c.n_edge)} on the edge` + (nLabels ? ` · ${nLabels} labeled` : "")));
      } else if (isRunning) {
        const frac = job.message.includes("Measuring") ? 0.7 : job.message.includes("Tracing") ? 0.92 : job.message.includes("Segmenting") ? 0.35 : 0.1;
        body.append(h("div", { style: { display: "flex", alignItems: "center", gap: "10px", fontSize: "13px", color: "#A3A9B1" } },
          h("span", { style: { flex: "1" } }, progressBar(frac)), job.message.split(": ").pop()));
      } else {
        body.append(h("div", { class: "status", style: { fontSize: "13px" } }, h("div", { class: "spinner" }), c.status === "stale" ? "Settings changed · waiting to be rebuilt" : "Waiting…"));
      }
      grid.append(h("article", { class: "card crop-card" }, thumbBox, body));

      if (c.status === "ready" || c.image_width) {
        const img = h("img", { src: `/api/crops/${c.id}/thumb?v=${version}`, alt: `Whole slice ${c.image} with the crop frame`, draggable: "false" });
        const wrap = h("div", { class: "wrap" }, img);
        const frame = h("div", { class: "crop-frame", title: "Drag to move the crop" });
        wrap.append(frame);
        thumbBox.append(wrap);
        requestAnimationFrame(() => {
          const W = c.image_width, H = c.image_height;
          const bw = thumbBox.clientWidth, bh = thumbBox.clientHeight;
          const s = Math.min(bw / W, bh / H);
          wrap.style.width = `${W * s}px`;
          wrap.style.height = `${H * s}px`;
          const place = (y, x) => {
            frame.style.left = `${(x / W) * 100}%`; frame.style.top = `${(y / H) * 100}%`;
            frame.style.width = `${(c.w / W) * 100}%`; frame.style.height = `${(c.h / H) * 100}%`;
          };
          place(c.y, c.x);
          if (job) return; // no moving while something is running
          frame.addEventListener("pointerdown", (e) => {
            e.preventDefault();
            frame.setPointerCapture(e.pointerId);
            const start = { mx: e.clientX, my: e.clientY, y: c.y, x: c.x };
            let ny = c.y, nx = c.x;
            const move = (ev) => {
              nx = Math.round(Math.min(Math.max(0, start.x + (ev.clientX - start.mx) / s), W - c.w));
              ny = Math.round(Math.min(Math.max(0, start.y + (ev.clientY - start.my) / s), H - c.h));
              place(ny, nx);
            };
            const up = async () => {
              frame.removeEventListener("pointermove", move);
              frame.removeEventListener("pointerup", up);
              if (Math.abs(ny - c.y) < 8 && Math.abs(nx - c.x) < 8) { place(c.y, c.x); return; }
              if (nLabels && !(await confirm("Move this crop?", `Its ${nLabels} labeled nuclei will be deleted, because the nuclei are segmented again.`, "Move crop", true))) { place(c.y, c.x); return; }
              try { await api.post(`/api/crops/${c.id}/move`, { y: ny, x: nx }); await ctx.refresh(); draw(); poll(); } catch (err) { errorToast(err); place(c.y, c.x); }
            };
            frame.addEventListener("pointermove", move);
            frame.addEventListener("pointerup", up);
          });
        });
      } else {
        thumbBox.append(h("div", { class: "spinner" }));
      }
    }

    root.append(
      h("header", { class: "header" },
        h("div", { class: "titles" }, h("h1", {}, "Training crops"),
          h("p", {}, "Each crop starts where marker-positive cells are densest. Drag a frame to move it; it is segmented again automatically.")),
        !ready ? h("span", { class: "hint" }, job ? "Ready when all crops are segmented" : "") : null,
        start),
      h("div", { class: "content" },
        !p.crops.length ? h("div", { class: "card pad muted" }, "No crops yet. Pick training images on the Survey screen.") : grid,
        h("div", { class: "status faint", style: { fontSize: "13px" } }, icon("info"),
          "Nuclei cut by a crop edge are shown greyed out and can't be labeled. They're counted normally in the full images.")));
  };

  const poll = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const before = JSON.stringify(ctx.store.state.project.crops.map((c) => c.status));
        await ctx.refresh();
        const st = ctx.store.state;
        const running = (st.jobs || []).some((j) => j.kind === "crops" || j.kind === "crop");
        const failed = st.project.crops.some((c) => c.status === "running") && !running;
        if (JSON.stringify(st.project.crops.map((c) => c.status)) !== before) version = Date.now();
        draw();
        if (running) poll();
        else if (failed) errorToast(new Error("Creating a crop failed. Check the log window, then try again from the Survey screen."));
      } catch (e) { errorToast(e); }
    }, 900);
  };

  const st = ctx.store.state;
  const needsBuild = st.project.crops.some((c) => c.status !== "ready") || st.project.crops.length !== st.project.selection.length;
  const running = (st.jobs || []).some((j) => j.kind === "crops" || j.kind === "crop");
  if (needsBuild && !running) {
    try { await api.post("/api/crops"); await ctx.refresh(); } catch (e) { errorToast(e); }
  }
  draw();
  if ((ctx.store.state.jobs || []).some((j) => j.kind === "crops" || j.kind === "crop")) poll();
}

export function destroy() {
  clearTimeout(timer);
}
