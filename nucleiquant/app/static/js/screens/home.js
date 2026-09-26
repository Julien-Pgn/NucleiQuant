// Home: new project, open project, recent projects, reuse a classifier.
import * as api from "../api.js";
import { h, icon, modal, pickFolder, errorToast } from "../ui.js";

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const today = new Date();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return `Today ${time}`;
  return d.toLocaleDateString([], { day: "numeric", month: "short", year: d.getFullYear() === today.getFullYear() ? undefined : "numeric" });
}

export async function render(root, ctx) {
  const st = ctx.store.state;
  const dev = st.system.device;
  const devText = dev.device === "GPU" ? `GPU ready · ${dev.name}` : dev.device === "CPU" ? "CPU mode · no GPU found" : dev.device === "none" ? "Segmentation unavailable" : "Detecting GPU…";
  let recent = [];
  try { recent = await api.get("/api/recent"); } catch (e) { /* first run */ }

  const newProject = async (reuse = null) => {
    const folder = await pickFolder({ title: "Choose your images", text: "Pick the folder that contains your TIFF images. NucleiQuant never changes them; results go in a NucleiQuant_projects sub-folder." });
    if (!folder) return;
    let suggested = "project";
    try { suggested = (await api.get(`/api/suggest-name?images_dir=${encodeURIComponent(folder)}`)).name; } catch (e) { /* keep default */ }
    const input = h("input", { class: "input", value: suggested, "aria-label": "Project name" });
    let source = reuse;
    const reuseBox = h("div", { class: "field" });
    if (reuse !== null) {
      const choices = recent.filter((r) => r.stage === "Results ready" || r.stage === "Ready to classify all images");
      const sel = h("select", { class: "input" }, ...choices.map((r) => h("option", { value: r.path }, `${r.name} — ${r.images}`)));
      source = choices.length ? choices[0].path : null;
      sel.addEventListener("change", () => { source = sel.value; });
      reuseBox.append("Reuse the classifier of", choices.length ? sel : h("span", { class: "faint" }, "No project with a validated classifier yet."));
    }
    const m = modal({
      title: reuse !== null ? "Apply a saved classifier" : "New project",
      text: reuse !== null ? "The categories, channels and classifier are copied from the chosen project; you go straight to classifying all images." : "Give the project a name. You can have several projects on the same images.",
      body: h("div", { style: { display: "flex", flexDirection: "column", gap: "14px" } },
        h("div", { class: "field" }, "Images", h("div", { class: "picker-path" }, icon("folder"), h("span", {}, folder))),
        h("label", { class: "field" }, "Project name", input),
        reuse !== null ? reuseBox : null),
      actions: [
        { label: "Cancel" },
        {
          label: "Create project", kind: "primary",
          onClick: async (btn) => {
            btn.disabled = true;
            try {
              await api.post("/api/projects", { images_dir: folder, name: input.value });
              if (reuse !== null) {
                if (!source) throw new Error("Choose a project to reuse the classifier from.");
                await api.post("/api/classifier/import", { path: source });
                ctx.navigate("results");
              } else {
                ctx.navigate("project");
              }
            } catch (e) { errorToast(e); btn.disabled = false; return true; }
          },
        },
      ],
    });
    setTimeout(() => { input.focus(); input.select(); }, 50);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") m.actions[1].el.click(); });
  };

  const openProject = async (path) => {
    try {
      if (!path) path = await pickFolder({ title: "Open a project", text: "Projects live in a NucleiQuant_projects folder inside your images folder.", mode: "project" });
      if (!path) return;
      const s = await api.post("/api/projects/open", { path });
      const steps = ctx.stepInfo(s);
      const order = ["results", "preview", "label", "crops", "survey", "project"];
      const target = s.project.batch.done ? "results" : order.find((k) => steps.available[k] && !steps.done[k]) || "project";
      ctx.navigate(target);
    } catch (e) { errorToast(e); }
  };

  const recentList = recent.length ? h("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } },
    h("div", { class: "eyebrow", style: { fontSize: "12px" } }, "Recent"),
    ...recent.slice(0, 5).map((r) => h("button", { class: "recent-item", type: "button", onclick: () => openProject(r.path) },
      h("span", { style: { display: "flex", flexDirection: "column", gap: "3px", flex: "1", minWidth: "0" } },
        h("span", { style: { fontSize: "15px", fontWeight: "500" } }, r.name),
        h("span", { class: "mono faint", style: { fontSize: "12.5px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, r.images)),
      h("span", { class: "muted", style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", whiteSpace: "nowrap" } },
        h("span", { class: `dot ${r.stage === "Results ready" ? "" : "warn"}` }), r.stage),
      h("span", { class: "faint", style: { fontSize: "12.5px", width: "84px", textAlign: "right" } }, when(r.modified)),
      icon("chevron", 18, { color: "#80868E" })))) : null;

  root.append(h("div", { class: "home" },
    h("div", { class: "home-top" },
      h("div", { class: "muted", style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "13px" } },
        h("span", { class: `dot ${dev.device === "GPU" ? "" : dev.device === "CPU" ? "warn" : "off"}` }), devText),
      h("button", { class: "btn ghost small", type: "button", onclick: () => ctx.openHelp() }, icon("help"), "Help"),
      h("button", { class: "btn small", type: "button", onclick: ctx.quit }, icon("power"), "Quit")),
    h("div", { class: "home-center" }, h("div", { class: "home-col" },
      h("div", { style: { display: "flex", flexDirection: "column", gap: "16px" } },
        h("div", { style: { display: "flex", alignItems: "center", gap: "14px" } }, icon("logo", 40), h("h1", {}, "NucleiQuant")),
        h("p", { class: "tagline" }, "Count cell types in fluorescence images. Segment every nucleus, teach the classifier with a few clicks, and get your counts in Excel.")),
      h("div", { class: "home-actions" },
        h("button", { class: "action-card primary", type: "button", onclick: () => newProject() },
          icon("plus", 22, { width: 2 }),
          h("span", { style: { display: "flex", flexDirection: "column", gap: "4px" } }, h("span", { class: "t" }, "New project"), h("span", { class: "d" }, "Start from a folder of TIFF images"))),
        h("button", { class: "action-card", type: "button", onclick: () => openProject() },
          icon("folder", 22),
          h("span", { style: { display: "flex", flexDirection: "column", gap: "4px" } }, h("span", { class: "t" }, "Open project"), h("span", { class: "d" }, "Continue where you left off")))),
      recentList,
      h("button", { class: "link", type: "button", style: { alignSelf: "flex-start", display: "flex", alignItems: "center", gap: "6px", fontSize: "14px" }, onclick: () => newProject("reuse") },
        "Apply a saved classifier to new images", icon("arrow")))),
    h("div", { class: "home-foot" }, `NucleiQuant ${st.system.version} · stardist_haug2 model · Pigeon et al., bioRxiv 2025`)));
}
