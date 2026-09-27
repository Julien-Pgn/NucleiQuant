// Independent test set: create test crops, label them blind, report accuracy with CIs.
import * as api from "../api.js";
import { h, icon, errorToast, toast, fmt, shortName, progressBar } from "../ui.js";
import * as label from "./label.js";

let timer = null;
let delegated = false;

const pct = (v, d = 1) => (v == null ? "–" : `${(100 * v).toFixed(d)} %`);
const ci = (pair) => (!pair || pair[0] == null ? "" : `${(100 * pair[0]).toFixed(0)}–${(100 * pair[1]).toFixed(0)} %`);

export async function render(root, ctx, route, params) {
  delegated = false;
  if (params && params[0] === "report") return renderReport(root, ctx);
  const st = ctx.store.state;
  const tc = st.project.test_crops || [];
  const running = (st.jobs || []).some((j) => j.kind === "test");
  if (!tc.length && !running) return renderIntro(root, ctx);
  if (running || tc.some((c) => c.status !== "ready")) return renderProgress(root, ctx);
  delegated = true;
  return label.render(root, ctx, "test");
}

function header(title, sub, ...right) {
  return h("header", { class: "header" }, h("div", { class: "titles" }, h("h1", {}, title), sub ? h("p", {}, sub) : null), ...right);
}

function renderIntro(root, ctx) {
  const st = ctx.store.state;
  const s = st.project.settings;
  const clones = st.files.clones.length || 1;
  const nImg = s.test_images_per_clone * clones;
  const nCats = st.project.categories.length;
  const cells = nImg * nCats * s.test_labels_per_crop;
  root.innerHTML = "";
  const go = h("button", { class: "btn primary", type: "button" }, "Create test crops", icon("arrow", 16, { width: 2 }));
  go.addEventListener("click", async () => {
    go.disabled = true;
    try { await api.post("/api/test/crops"); await ctx.refresh(); ctx.navigate("test"); } catch (e) { errorToast(e); go.disabled = false; }
  });
  const point = (t, d) => h("li", { style: { display: "flex", gap: "12px" } },
    icon("check", 18, { color: "#5BD68A", width: 2 }), h("span", { class: "muted", style: { lineHeight: "1.55" } }, h("span", { style: { color: "#EDEEF0", fontWeight: "500" } }, t), " ", d));
  root.append(
    header("Test set", "Measure how accurate the classifier is on images it never saw — the number to report.", go),
    h("div", { class: "content" }, h("div", { style: { display: "flex", gap: "32px", alignItems: "flex-start" } },
      h("section", { class: "card pad", style: { flex: "1", maxWidth: "720px", display: "flex", flexDirection: "column", gap: "16px" } },
        h("h2", { class: "card-title" }, "How the test works"),
        h("ul", { style: { margin: "0", padding: "0", listStyle: "none", display: "flex", flexDirection: "column", gap: "12px", fontSize: "14px" } },
          point("Independent images.", `${s.test_images_per_clone} image${s.test_images_per_clone > 1 ? "s" : ""} per clone are drawn at random among the images not used for training, and a smaller crop is cut from each.`),
          point("Blind labeling.", "You label test cells exactly like training cells, but the classifier's answers are hidden, so they can't influence you."),
          point("A few cells per category.", `${s.test_labels_per_crop} of each category in each test crop is recommended — about ${cells} test cells here.`),
          point("Never used for training.", "Test labels are stored apart. Retraining never sees them."),
          point("A report for reviewers.", "Balanced accuracy, accuracy and Cohen's κ with 95 % confidence intervals, per category and per image, the confusion matrix, and a methods paragraph. Every evaluation is logged.")),
        h("div", { class: "banner" }, "Label the test crops once your training labels are final, and evaluate once. If you then change the training, evaluate again: the report keeps the history, so it stays transparent.")),
      h("aside", { class: "card pad", style: { width: "320px", display: "flex", flexDirection: "column", gap: "10px" } },
        h("h2", { class: "card-title" }, "Settings"),
        h("div", { class: "muted", style: { fontSize: "13.5px", lineHeight: "1.6" } },
          `Test images per clone: ${s.test_images_per_clone}`, h("br"),
          `Test crop size: ${Math.round(s.test_crop_fraction * 100)} % of the image side`, h("br"),
          `Recommended labels: ${s.test_labels_per_crop} per category per crop`),
        h("div", { class: "faint", style: { fontSize: "12.5px", lineHeight: "1.5" } }, "Change them in Project › Advanced settings before creating the test crops."),
        h("div", { class: "faint", style: { fontSize: "12.5px", lineHeight: "1.5" } },
          `Precision to expect: with 100 test cells and a true accuracy of 90 %, the 95 % interval is about ±6 %; with 20 cells of a category, its accuracy is known to about ±15 %.`)))));
}

function renderProgress(root, ctx) {
  root.innerHTML = "";
  const bar = progressBar(0.02, true);
  const msg = h("div", { class: "muted", style: { fontSize: "13px" } }, "Starting…");
  root.append(header("Test set", "Cutting and segmenting the test crops."),
    h("div", { class: "content" }, h("div", { class: "card pad", style: { maxWidth: "560px", display: "flex", flexDirection: "column", gap: "14px" } },
      h("div", { style: { display: "flex", alignItems: "center", gap: "10px" } }, h("div", { class: "spinner" }), h("span", { class: "card-title" }, "Creating test crops")),
      bar, msg)));
  let retried = false;
  const poll = async () => {
    try {
      await ctx.refresh();
      const st = ctx.store.state;
      const job = (st.jobs || []).find((j) => j.kind === "test");
      if (job) {
        bar.firstChild.style.width = `${Math.max(2, job.progress * 100)}%`;
        msg.textContent = job.message || "Working…";
        timer = setTimeout(poll, 800);
        return;
      }
      const tc = st.project.test_crops || [];
      if (tc.length && tc.every((c) => c.status === "ready")) { ctx.navigate("test"); return; }
      if (tc.some((c) => c.status !== "ready") && !retried) {
        retried = true;
        await api.post("/api/test/crops");
        timer = setTimeout(poll, 800);
        return;
      }
      errorToast(new Error("Creating the test crops failed. See the log window."));
    } catch (e) { errorToast(e); }
  };
  poll();
}

async function renderReport(root, ctx) {
  const st = ctx.store.state;
  const cats = st.project.categories;
  const name = (id) => (cats.find((c) => c.id === id) || { name: id }).name;
  const color = (id) => (cats.find((c) => c.id === id) || { color: "#888" }).color;
  const r = await api.get("/api/test/report");
  root.innerHTML = "";
  if (!r) { ctx.navigate("test"); return; }
  const m = r.metrics;
  const copy = h("button", { class: "btn", type: "button" }, icon("copy"), "Copy methods text");
  copy.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(r.methods_text); toast("Methods text copied"); } catch (e) { toast("Select the text below and copy it"); }
  });
  const again = h("button", { class: "btn primary", type: "button" }, icon("refresh", 16), "Evaluate again");
  again.addEventListener("click", async () => {
    again.disabled = true;
    try { await api.post("/api/test/evaluate"); await ctx.refresh(); ctx.navigate("test/report"); } catch (e) { errorToast(e); again.disabled = false; }
  });
  const tile = (l, v, s) => h("div", { class: "card tile" }, h("span", { class: "l" }, l), h("span", { class: "v" }, v), h("span", { class: "s" }, s));
  const perCat = h("section", { class: "card", style: { overflow: "hidden" } },
    h("div", { style: { padding: "16px 20px 8px" } }, h("h2", { class: "card-title" }, "Per category")),
    h("div", { class: "table" },
      h("div", { class: "tr head", style: { display: "grid", gridTemplateColumns: "1.4fr 0.8fr 1.6fr 1.6fr 0.8fr" } },
        h("span", {}, "Category"), h("span", { style: { textAlign: "right" } }, "Test cells"), h("span", { style: { textAlign: "right" } }, "Recall (95 % CI)"),
        h("span", { style: { textAlign: "right" } }, "Precision (95 % CI)"), h("span", { style: { textAlign: "right" } }, "F1")),
      ...m.per_category.map((c, i) => h("div", { class: `tr ${i % 2 ? "alt" : ""}`, style: { display: "grid", gridTemplateColumns: "1.4fr 0.8fr 1.6fr 1.6fr 0.8fr" } },
        h("span", { style: { display: "flex", alignItems: "center", gap: "8px" } }, h("span", { class: "swatch", style: { background: color(c.category) } }), name(c.category)),
        h("span", { class: "mono", style: { textAlign: "right" } }, c.n_test),
        h("span", { class: "mono", style: { textAlign: "right" } }, c.recall == null ? "not tested" : `${pct(c.recall, 0)}  ${ci(c.recall_ci)}`),
        h("span", { class: "mono", style: { textAlign: "right" } }, c.precision == null ? "–" : `${pct(c.precision, 0)}  ${ci(c.precision_ci)}`),
        h("span", { class: "mono", style: { textAlign: "right" } }, c.f1 == null ? "–" : c.f1.toFixed(2))))));
  const conf = h("section", { class: "card pad", style: { display: "flex", flexDirection: "column", gap: "10px" } },
    h("h2", { class: "card-title" }, "Confusion matrix"),
    h("div", { class: "faint", style: { fontSize: "12.5px" } }, "Rows: your label. Columns: the classifier's answer."),
    h("table", { class: "confusion", style: { fontSize: "12.5px" } },
      h("tr", {}, h("th", {}), ...m.categories.map((c) => h("th", {}, name(c)))),
      ...m.confusion.map((row, i) => h("tr", {}, h("th", { style: { textAlign: "left" } }, name(m.categories[i])),
        ...row.map((v, j) => h("td", { style: { color: i === j ? "#5BD68A" : v ? "#FFB4B4" : "#5A6068" } }, v))))));
  const perImg = h("section", { class: "card pad", style: { display: "flex", flexDirection: "column", gap: "10px" } },
    h("h2", { class: "card-title" }, "Per test image"),
    ...r.per_crop.map((c) => {
      const crop = (st.project.test_crops || []).find((x) => x.id === c.crop_id);
      return h("div", { style: { display: "flex", gap: "12px", fontSize: "13.5px" } },
        h("span", { style: { flex: "1" } }, crop ? shortName(crop.image, crop.fields) : c.image),
        h("span", { class: "mono muted" }, `${c.correct}/${c.n}`), h("span", { class: "mono", style: { width: "150px", textAlign: "right" } }, `${pct(c.accuracy, 0)}  ${ci(c.accuracy_ci)}`));
    }));
  const hist = h("section", { class: "card pad", style: { display: "flex", flexDirection: "column", gap: "8px" } },
    h("h2", { class: "card-title" }, "Every evaluation"),
    h("div", { class: "faint", style: { fontSize: "12.5px" } }, "Kept so that evaluating again after changing the training stays visible."),
    ...(r.history || []).map((x) => h("div", { style: { display: "flex", gap: "12px", fontSize: "13px" } },
      h("span", { class: "muted", style: { flex: "1" } }, new Date(x.date).toLocaleString()), h("span", { class: "mono faint" }, `classifier ${x.classifier_hash.slice(0, 8)}`),
      h("span", { class: "mono" }, `${x.n} cells`), h("span", { class: "mono", style: { width: "70px", textAlign: "right" } }, pct(x.balanced_accuracy)))));
  const methods = h("section", { class: "card pad", style: { display: "flex", flexDirection: "column", gap: "10px" } },
    h("div", { style: { display: "flex", alignItems: "center" } }, h("h2", { class: "card-title", style: { flex: "1" } }, "Methods text"), copy),
    h("p", { style: { fontSize: "13.5px", lineHeight: "1.65", color: "#A3A9B1", userSelect: "text" } }, r.methods_text),
    h("div", { class: "faint", style: { fontSize: "12px" } }, "A starting point: check the numbers and adapt the wording to your paper."));
  root.append(
    header("Test accuracy", `${m.n} test cells from ${r.n_images} image${r.n_images > 1 ? "s" : ""} never used for training · evaluated ${new Date(r.date).toLocaleString()}`,
      h("a", { class: "btn", href: "#/test" }, "Test labels"), again),
    h("div", { class: "content" },
      r.stale ? h("div", { class: "banner", style: { flexDirection: "row", alignItems: "center" } },
        h("span", { style: { flex: "1" } }, "The classifier changed since this evaluation. Evaluate again to measure the current one (the history keeps both)."), again.cloneNode(true)) : null,
      h("div", { class: "tiles" },
        tile("Balanced accuracy", pct(m.balanced_accuracy), `95 % CI ${ci(m.balanced_accuracy_ci)} · mean over categories`),
        tile("Accuracy on test cells", pct(m.accuracy), `95 % CI ${ci(m.accuracy_ci)}`),
        tile("Cohen's κ", m.kappa == null ? "–" : m.kappa.toFixed(2), m.kappa_ci && m.kappa_ci[0] != null ? `95 % CI ${m.kappa_ci[0].toFixed(2)}–${m.kappa_ci[1].toFixed(2)}` : ""),
        tile("Training (for comparison)", pct(r.cv_accuracy), `leave-one-crop-out on ${r.n_training_labels} training labels`)),
      h("div", { style: { display: "flex", gap: "20px", alignItems: "flex-start" } },
        h("div", { style: { flex: "1.4", display: "flex", flexDirection: "column", gap: "20px", minWidth: "0" } }, perCat, methods),
        h("div", { style: { flex: "1", display: "flex", flexDirection: "column", gap: "20px", minWidth: "0" } }, conf, perImg, hist)),
      h("div", { class: "faint", style: { fontSize: "12.5px", lineHeight: "1.6" } },
        "Test cells are picked per category, so the balanced accuracy is the fairest single number. Intervals treat cells as independent; cells from the same image are somewhat alike, so the true uncertainty is a little larger. Everything here is also in the Excel file, sheet “test_set”.")));
  const againClone = root.querySelector(".banner .btn.primary");
  if (againClone) againClone.addEventListener("click", () => again.click());
}

export function destroy() {
  clearTimeout(timer);
  if (delegated) label.destroy();
}
