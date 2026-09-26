// App shell: routing, sidebar, shared state, help and quit.
import * as api from "./api.js";
import { h, icon, confirm, errorToast, fmt, shortPath } from "./ui.js";
import * as home from "./screens/home.js";
import * as project from "./screens/project.js";
import * as survey from "./screens/survey.js";
import * as crops from "./screens/crops.js";
import * as label from "./screens/label.js";
import * as results from "./screens/results.js";

const app = document.getElementById("app");

export const store = { state: null, screen: null, route: "", params: [] };

const STEPS = [
  { key: "project", title: "Project", screen: project },
  { key: "survey", title: "Survey", screen: survey },
  { key: "crops", title: "Crops", screen: crops },
  { key: "label", title: "Label", screen: label },
  { key: "preview", title: "Preview", screen: label },
  { key: "results", title: "Results", screen: results },
];

export async function refresh() {
  store.state = await api.get("/api/state");
  renderSidebar();
  return store.state;
}

export function navigate(route) {
  const target = `#/${route}`;
  if (location.hash === target) render();
  else location.hash = target;
}

// Which steps can be opened, and their status
export function stepInfo(state) {
  const s = state.steps;
  const p = state.project;
  const imported = p.imported_classifier;
  const trained = !!state.classifier;
  const available = {
    project: true,
    survey: !imported && s.project,
    crops: !imported && s.survey,
    label: !imported && s.crops,
    preview: !imported && trained && s.crops,
    results: (p.classifier.validated && trained) || p.batch.done,
  };
  const meta = {
    project: `${state.files.n} images`,
    survey: p.survey_done ? `${p.selection.length} picked` : "",
    crops: p.crops.length ? `${p.crops.filter((c) => c.status === "ready").length} / ${p.crops.length}` : "",
    label: state.labels.total ? (!state.labels.ready ? `${state.labels.needed || ""} to go`.trim() : `${state.labels.total} labels`) : "",
    preview: trained && state.classifier.cross_validation.accuracy != null ? `${Math.round(state.classifier.cross_validation.accuracy * 100)}%` : "",
    results: p.batch.done ? "ready" : "",
  };
  if (imported) {
    for (const k of ["survey", "crops", "label", "preview"]) meta[k] = "reused";
  }
  return { available, meta, done: s, imported };
}

function stepIcon(status) {
  if (status === "current") return icon("current", 18, { width: 2 });
  if (status === "done") return icon("check", 18, { color: "#5BD68A", width: 2 });
  if (status === "locked") return icon("lock", 18, { color: "#5A6068" });
  return icon("todo", 18, { color: "#80868E", width: 2 });
}

let jobTimer = null;

function renderSidebar() {
  const side = document.querySelector(".sidebar");
  if (!side || !store.state || !store.state.project) return;
  const st = store.state;
  const info = stepInfo(st);
  side.innerHTML = "";
  side.append(
    h("a", { class: "brand", href: "#/" }, icon("logo", 24), "NucleiQuant"),
    h("div", { class: "proj" },
      h("div", { class: "eyebrow" }, "Project"),
      h("div", { class: "proj-name", title: st.project.name }, st.project.name),
      h("div", { class: "proj-path", title: st.project.images_dir_display }, shortPath(st.project.images_dir_display))),
  );
  const nav = h("nav", { class: "nav", "aria-label": "Steps" });
  for (const step of STEPS) {
    const isCurrent = store.route === step.key || (store.route === "view" && step.key === "results");
    const avail = info.available[step.key];
    const status = isCurrent ? "current" : info.done[step.key] ? "done" : avail ? "todo" : "locked";
    const item = h("button", {
      class: `nav-item ${isCurrent ? "current" : ""} ${!avail && !isCurrent ? "locked" : ""}`,
      type: "button", "aria-current": isCurrent ? "step" : null, disabled: !avail && !isCurrent,
    }, stepIcon(status), step.title, info.meta[step.key] ? h("span", { class: "meta" }, info.meta[step.key]) : null);
    if (avail) item.addEventListener("click", () => navigate(step.key));
    nav.append(item);
  }
  side.append(nav);

  const foot = h("div", { class: "side-foot" });
  for (const job of st.jobs || []) {
    const bar = h("span", { style: { width: `${Math.round(job.progress * 100)}%` } });
    foot.append(h("div", { class: "side-job", onclick: () => jobRoute(job) },
      h("div", { style: { display: "flex", alignItems: "center", gap: "8px" } }, h("div", { class: "spinner" }), h("span", {}, job.title)),
      h("div", { class: "progress" }, bar)));
  }
  const dev = st.system.device;
  const devText = dev.device === "GPU" ? `GPU · ${dev.name}` : dev.device === "CPU" ? "CPU mode (no GPU found)" : dev.device === "none" ? "Segmentation unavailable" : "Detecting GPU…";
  foot.append(
    h("div", { class: "device", title: dev.name }, h("span", { class: `dot ${dev.device === "GPU" ? "" : dev.device === "CPU" ? "warn" : "off"}` }), devText),
    h("div", { class: "side-buttons" },
      h("button", { class: "btn ghost small", style: { flex: "1" }, type: "button", onclick: openHelp }, icon("help"), "Help"),
      h("button", { class: "btn ghost small", style: { flex: "1" }, type: "button", onclick: quit }, icon("power"), "Quit")));
  side.append(foot);

  clearTimeout(jobTimer);
  if ((st.jobs && st.jobs.length) || dev.device === "detecting") {
    jobTimer = setTimeout(() => refresh().catch(() => {}), 1500);
  }
}

function jobRoute(job) {
  const r = { survey: "survey", crops: "crops", crop: "crops", train: "preview", batch: "results" }[job.kind];
  if (r) navigate(r);
}

// ---- help & quit --------------------------------------------------------------------
export async function openHelp(anchor) {
  document.querySelectorAll(".drawer").forEach((d) => d.remove());
  const body = h("div", { class: "drawer-body prose" }, h("p", { class: "muted" }, "Loading…"));
  const drawer = h("aside", { class: "drawer", "aria-label": "Help" },
    h("div", { class: "drawer-head" }, icon("help", 18), h("h2", { style: { flex: "1", fontSize: "15px" } }, "User guide"),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Close help", onclick: () => drawer.remove() }, icon("close"))),
    body);
  document.body.append(drawer);
  const onKey = (e) => { if (e.key === "Escape") { drawer.remove(); document.removeEventListener("keydown", onKey); } };
  document.addEventListener("keydown", onKey);
  try {
    body.innerHTML = await api.get("/api/help");
    body.querySelectorAll("img").forEach((img) => { img.src = `/api/help/${img.getAttribute("src").split("/").pop()}`; });
    // In-guide links scroll inside the drawer (they must not change the app's route)
    body.querySelectorAll('a[href^="#"]').forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault();
      const target = body.querySelector(`[id="${a.getAttribute("href").slice(1)}"]`);
      if (target) target.scrollIntoView({ behavior: "smooth" });
    }));
    if (typeof anchor === "string") {
      const el = body.querySelector(`#${anchor}`);
      if (el) el.scrollIntoView();
    }
  } catch (e) { body.textContent = e.message; }
}

export async function quit() {
  const running = (store.state && store.state.jobs) || [];
  const ok = await confirm("Quit NucleiQuant?",
    running.length ? "A task is still running. It will stop, and can be resumed next time." : "Everything is saved. You can reopen your project from the home screen next time.",
    "Quit", running.length > 0);
  if (!ok) return;
  try { await api.post("/api/quit"); } catch (e) { /* server is going away */ }
  document.body.innerHTML = "";
  document.body.append(h("div", { style: { height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", flexDirection: "column", gap: "12px" } },
    icon("logo", 40), h("h1", { style: { fontSize: "20px" } }, "NucleiQuant has stopped"),
    h("p", { class: "muted" }, "You can close this tab.")));
}

// ---- routing ------------------------------------------------------------------------------
async function render() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const route = parts[0] || "";
  if (store.screen && store.screen.destroy) store.screen.destroy();
  store.screen = null;
  try {
    await refresh();
  } catch (e) {
    app.innerHTML = "";
    app.append(h("div", { style: { margin: "auto" }, class: "muted" }, "Can't reach NucleiQuant. Is it still running?"));
    return;
  }
  if (!store.state.project && route !== "") { location.hash = "#/"; return; }
  store.route = route;
  store.params = parts.slice(1);
  app.innerHTML = "";
  if (route === "") {
    store.screen = home;
    await home.render(app, ctx);
    return;
  }
  const step = STEPS.find((s) => s.key === route) || (route === "view" ? { screen: results } : null);
  if (!step) { navigate(""); return; }
  const side = h("aside", { class: "sidebar" });
  const main = h("div", { class: "main" });
  app.append(side, main);
  renderSidebar();
  store.screen = step.screen;
  try {
    await step.screen.render(main, ctx, route, store.params);
  } catch (e) {
    errorToast(e);
  }
}

export const ctx = { store, refresh, navigate, stepInfo, openHelp, quit, fmt };

window.addEventListener("hashchange", render);
render();
