// Step 1 — Project: images, file names, channels, genotypes, advanced settings.
import * as api from "../api.js";
import { h, icon, errorToast, colorPopover, switchEl, confirm, toast } from "../ui.js";

const FIELD_LABELS = { diff: "diff.", immuno: "staining" };
let advOpen = false;

export async function render(root, ctx) {
  const draw = () => {
    const st = ctx.store.state;
    const p = st.project;
    const f = st.files;
    root.innerHTML = "";

    const okNames = f.n_ok === f.n && f.n > 0;
    const cont = h("button", { class: "btn primary", type: "button", disabled: !okNames }, "Continue", icon("arrow", 16, { width: 2 }));
    cont.addEventListener("click", async () => {
      try {
        if (!p.survey_done) await api.post("/api/survey");
        ctx.navigate("survey");
      } catch (e) { errorToast(e); }
    });

    const save = async (changes, quiet = true) => {
      try {
        ctx.store.state = await api.patch("/api/project", changes);
        await ctx.refresh();
        if (!quiet) toast("Saved");
      } catch (e) { errorToast(e); }
      draw();
    };

    // ---- images
    const px = f.pixel_size ? ` · ${f.pixel_size.toFixed(2)} µm per pixel` : "";
    const images = h("section", { class: "section" },
      h("h2", {}, "Images"),
      h("div", { class: "picker-path", style: { height: "42px", color: "#EDEEF0", fontSize: "13.5px" } }, icon("folder", 16, { color: "#80868E" }), h("span", {}, p.images_dir_display)),
      h("div", { class: "status" }, icon(f.n ? "check" : "info", 16, { color: f.n ? "#5BD68A" : "#FF6B6B", width: 2 }),
        `${f.n} TIFF image${f.n === 1 ? "" : "s"} · ${f.channels || "?"} channel${f.channels === 1 ? "" : "s"}${px}`));

    // ---- file names
    const example = f.example && f.example.fields ? f.example : null;
    const chips = h("div", { class: "card", style: { display: "flex", alignItems: "flex-end", gap: "4px", padding: "16px", flexWrap: "wrap" } });
    if (example) {
      const names = Object.keys(example.fields);
      names.forEach((k, i) => {
        const key = k === "organoid" || k === "slice";
        chips.append(h("div", { style: { display: "flex", flexDirection: "column", gap: "6px" } },
          h("span", { class: "chip", style: key ? { background: "#2A2616", color: "#F2C94C" } : {} }, example.fields[k]),
          h("span", { class: "faint", style: { fontSize: "11.5px", paddingLeft: "2px" } }, FIELD_LABELS[k] || k)));
        if (i < names.length - 1) chips.append(h("span", { class: "faint mono", style: { paddingBottom: "27px" } }, "_"));
      });
      chips.append(h("span", { class: "faint mono", style: { padding: "5px 0 27px 4px" } }, example.image.slice(example.image.lastIndexOf("."))));
    } else {
      chips.append(h("span", { class: "muted" }, "No file name matches the pattern yet."));
    }
    const patternInput = h("input", { class: "input small mono", style: { flex: "1" }, value: p.filename_template, "aria-label": "File name pattern" });
    const patternEditor = h("div", { class: "hidden", style: { display: "flex", flexDirection: "column", gap: "8px" } },
      h("div", { class: "muted", style: { fontSize: "13px", lineHeight: "1.5" } },
        "Name each part of your file names, separated by _ . Include ", h("b", {}, "organoid"), " and ", h("b", {}, "slice"),
        " to add up slices per organoid, and ", h("b", {}, "clone"), " for genotypes."),
      h("div", { style: { display: "flex", gap: "8px" } }, patternInput,
        h("button", { class: "btn small primary", type: "button", onclick: () => save({ filename_template: patternInput.value }) }, "Apply"),
        h("button", { class: "btn small", type: "button", onclick: () => patternEditor.classList.add("hidden") }, "Cancel")));
    const nameStatus = okNames
      ? h("div", { class: "status" }, icon("check", 16, { color: "#5BD68A", width: 2 }),
        `All ${f.n} names match` + (f.n_organoids ? ` · ${f.n_organoids} organoid${f.n_organoids > 1 ? "s" : ""}, ${f.slices_min === f.slices_max ? f.slices_min : `${f.slices_min}–${f.slices_max}`} slices each` : ""),
        h("button", { class: "link", type: "button", style: { marginLeft: "auto" }, onclick: () => patternEditor.classList.toggle("hidden") }, "Edit pattern"))
      : h("div", { class: "status error", style: { alignItems: "flex-start" } }, icon("info", 16),
        h("span", { style: { flex: "1" } }, `${f.n - f.n_ok} of ${f.n} names don't match the pattern: `, h("span", { class: "mono" }, f.errors.slice(0, 3).join(", ")), f.errors.length > 3 ? "…" : ""),
        h("button", { class: "link", type: "button", onclick: () => patternEditor.classList.toggle("hidden") }, "Edit pattern"));
    if (!okNames) patternEditor.classList.remove("hidden");
    const names = h("section", { class: "section" },
      h("div", { class: "section-head" }, h("h2", {}, "File names"), h("span", {}, "Experiment details are read from each name.")),
      chips, nameStatus, patternEditor);

    // ---- channels
    const chanRows = h("div", { class: "card", style: { display: "flex", flexDirection: "column" } });
    p.channels.forEach((c, i) => {
      const sw = h("button", { type: "button", "aria-label": `Channel ${i + 1} colour`, style: { width: "22px", height: "22px", borderRadius: "6px", border: "1px solid #2B3036", background: c.color, padding: "0", cursor: "pointer" } });
      sw.addEventListener("click", () => colorPopover(sw, st.channel_colors, (col) => {
        const chans = p.channels.map((x, j) => ({ name: x.name, color: j === i ? col : x.color }));
        save({ channels: chans });
      }));
      const name = h("input", { class: "input bare", style: { flex: "1" }, value: c.name, "aria-label": `Channel ${i + 1} name` });
      name.addEventListener("change", () => {
        const chans = p.channels.map((x, j) => ({ name: j === i ? name.value : x.name, color: x.color }));
        save({ channels: chans });
      });
      const radio = h("input", { type: "radio", name: "nuclear", checked: p.nuclear_channel === i });
      radio.addEventListener("change", async () => {
        if (p.crops.length && !(await confirm("Change the nuclear channel?", "Nuclei are segmented on this channel: your crops will be segmented again and their labels removed.", "Change", true))) { draw(); return; }
        save({ nuclear_channel: i });
      });
      chanRows.append(h("div", { style: { display: "flex", alignItems: "center", gap: "14px", height: "52px", padding: "0 16px", borderBottom: i < p.channels.length - 1 ? "1px solid #1F2328" : "0" } },
        h("span", { class: "mono faint", style: { width: "22px", fontSize: "12.5px" } }, i + 1), sw, name,
        h("label", { style: { display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", color: p.nuclear_channel === i ? "#EDEEF0" : "#A3A9B1", cursor: "pointer" } },
          radio, p.nuclear_channel === i ? "Nuclei · used for segmentation" : "Nuclei")));
    });
    const channels = h("section", { class: "section" }, h("h2", {}, "Channels"), chanRows);

    // ---- genotypes
    let genotypes = null;
    if (f.clones && f.clones.length) {
      const rows = h("div", { class: "card", style: { display: "flex", flexDirection: "column" } });
      f.clones.forEach((clone, i) => {
        const inp = h("input", { class: "input small", style: { width: "220px", background: "#0B0C0E" }, value: p.genotypes[clone] || "", placeholder: "e.g. WT/WT", "aria-label": `Genotype of clone ${clone}` });
        inp.addEventListener("change", () => save({ genotypes: { ...p.genotypes, [clone]: inp.value } }));
        rows.append(h("div", { style: { display: "flex", alignItems: "center", gap: "14px", height: "52px", padding: "0 16px", borderBottom: i < f.clones.length - 1 ? "1px solid #1F2328" : "0" } },
          h("span", { class: "mono", style: { width: "120px" } }, clone), icon("arrow", 16, { color: "#80868E" }), inp));
      });
      genotypes = h("section", { class: "section" },
        h("div", { class: "section-head" }, h("h2", {}, "Genotypes"), h("span", {}, "Organoids are grouped by genotype in plots and statistics.")), rows);
    }

    // ---- advanced
    const s = p.settings;
    const num = (key, label, opts = {}) => {
      const scale = opts.scale || 1;
      const inp = h("input", { class: "input small", type: "number", value: +(s[key] * scale).toFixed(4), min: opts.min, max: opts.max, step: opts.step || 1, "aria-label": label });
      inp.addEventListener("change", async () => {
        if (opts.resegment && p.crops.length && !(await confirm("Change this setting?", "Your crops will be measured again and their labels removed.", "Change", true))) { draw(); return; }
        save({ settings: { [key]: Number(inp.value) / scale } });
      });
      return h("label", { class: "field" }, label, inp);
    };
    const groupSeg = h("div", { class: "seg small" },
      ...["genotype", "clone"].map((g) => h("button", { type: "button", class: s.group_by === g ? "on" : "", onclick: () => save({ settings: { group_by: g } }) }, g === "genotype" ? "Genotype" : "Clone")));
    const adv = h("div", { class: `card pad ${advOpen ? "" : "hidden"}`, style: { display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "16px 20px" } },
      num("label_target", "Labels per category", { min: 5, max: 1000 }),
      num("min_slices", "Min. slices per organoid", { min: 1, max: 100 }),
      h("div", { class: "field" }, "Compare groups by", groupSeg),
      num("crop_fraction", "Crop size (% of image side)", { scale: 100, min: 10, max: 100, resegment: true }),
      num("ring_radius", "Neighbourhood ring (px)", { min: 2, max: 100, resegment: true }),
      num("perinuclear_radius", "Perinuclear ring (px)", { min: 1, max: 20, resegment: true }),
      num("n_trees", "Trees in the forest", { min: 10, max: 1000, step: 10 }),
      num("uncertain_threshold", "“Uncertain” below probability", { min: 0.3, max: 0.99, step: 0.05 }),
      h("div"),
      num("norm_low", "Segmentation: low percentile", { min: 0, max: 20, step: 0.1, resegment: true }),
      num("norm_high", "Segmentation: high percentile", { min: 80, max: 100, step: 0.1, resegment: true }),
      h("div", { class: "field" }, "Save every feature of every nucleus",
        h("div", { style: { display: "flex", alignItems: "center", gap: "10px", height: "32px" } },
          switchEl(s.save_all_features, (v) => save({ settings: { save_all_features: v } }), "Save every feature"),
          h("span", { class: "faint", style: { fontSize: "12.5px" } }, "large files"))));
    const advBtn = h("button", { class: "link", type: "button", style: { color: "#A3A9B1", display: "flex", alignItems: "center", gap: "8px", fontSize: "14px" } },
      icon(advOpen ? "down" : "chevron"), "Advanced settings", h("span", { class: "faint" }, "· segmentation, rings, label target, slices per organoid"));
    advBtn.addEventListener("click", () => {
      adv.classList.toggle("hidden");
      advOpen = !adv.classList.contains("hidden");
      advBtn.firstChild.replaceWith(icon(adv.classList.contains("hidden") ? "chevron" : "down"));
    });

    const steps = [
      ["Project.", "Point to your images."],
      ["Survey.", "Pick dim, typical and bright images for training."],
      ["Crops.", "Small regions are cut and their nuclei segmented."],
      ["Label.", "Click 50–60 cells for each category."],
      ["Preview.", "Check the result, correct mistakes."],
      ["Results.", "Every image is classified; you get Excel, plots and statistics."],
    ];
    const how = h("aside", { class: "card", style: { width: "330px", flexShrink: "0", alignSelf: "flex-start", padding: "22px", display: "flex", flexDirection: "column", gap: "16px" } },
      h("h2", { style: { fontSize: "14px", fontWeight: "600" } }, "How it works"),
      h("ol", { style: { margin: "0", padding: "0", listStyle: "none", display: "flex", flexDirection: "column", gap: "14px" } },
        ...steps.map(([t, d], i) => h("li", { style: { display: "flex", gap: "12px" } },
          h("span", { style: { flexShrink: "0", width: "22px", height: "22px", borderRadius: "50%", background: i === 0 ? "#2A2616" : "#1B1F24", color: i === 0 ? "#F2C94C" : "#A3A9B1", fontSize: "12px", fontWeight: "600", display: "flex", alignItems: "center", justifyContent: "center" } }, i + 1),
          h("span", { style: { fontSize: "13.5px", lineHeight: "1.5", color: "#A3A9B1" } }, h("span", { style: { color: "#EDEEF0", fontWeight: "500" } }, t), " ", d)))),
      h("button", { class: "link", type: "button", style: { alignSelf: "flex-start" }, onclick: () => ctx.openHelp() }, "Read the user guide"));

    root.append(
      h("header", { class: "header" },
        h("div", { class: "titles" }, h("h1", {}, "Project"), h("p", {}, "Tell NucleiQuant where your images are and what each channel shows.")),
        cont),
      h("div", { class: "content" }, h("div", { style: { display: "flex", gap: "48px" } },
        h("div", { style: { width: "720px", maxWidth: "100%", display: "flex", flexDirection: "column", gap: "30px" } },
          images, names, channels, genotypes, h("div", { style: { display: "flex", flexDirection: "column", gap: "14px" } }, advBtn, adv)),
        how)));
  };
  draw();
}
