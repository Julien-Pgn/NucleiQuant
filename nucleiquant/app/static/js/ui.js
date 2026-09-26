// Small DOM helpers, icons, modals, toasts and the folder picker.
import * as api from "./api.js";

export function h(tag, attrs = {}, ...children) {
  const el = tag === "svg" || attrs.svg ? document.createElementNS("http://www.w3.org/2000/svg", tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false || k === "svg") continue;
    if (k === "class") el.setAttribute("class", v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") el.innerHTML = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const ICONS = {
  logo: '<path d="M12 3.5c4.9 0 8.5 3.4 8.5 8.2 0 4.9-3.9 8.8-8.9 8.8-4.8 0-8.1-3.6-8.1-8.3 0-4.9 3.7-8.7 8.5-8.7z" stroke="#F2C94C" stroke-width="1.8" fill="none"/><circle cx="12.4" cy="12" r="4.2" fill="#EDEEF0" stroke="none"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12.3 2.4 2.4 4.8-5"/>',
  tick: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  current: '<circle cx="12" cy="12" r="9" stroke="#F2C94C" stroke-width="2"/><circle cx="12" cy="12" r="3.5" fill="#F2C94C" stroke="none"/>',
  todo: '<circle cx="12" cy="12" r="9"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 0 1 4.9.8c0 1.7-2.4 2.2-2.4 3.7"/><path d="M12 17h.01"/>',
  power: '<path d="M12 3v9"/><path d="M6.4 6.6a8 8 0 1 0 11.2 0"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  arrow: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
  back: '<path d="M19 12H5"/><path d="m11 6-6 6 6 6"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  up: '<path d="m6 15 6-6 6 6"/>',
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeoff: '<path d="M3 3l18 18"/><path d="M10.6 5.1A10.8 10.8 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6A17.4 17.4 0 0 0 2 12s3.6 7 10 7a10 10 0 0 0 5.4-1.6"/>',
  fit: '<path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  download: '<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5h.01"/>',
  chart: '<path d="M4 20h16"/><path d="M7 16v-5"/><path d="M12 16V7"/><path d="M17 16v-8"/>',
  trash: '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 17-5-5-9 8"/>',
  project: '<path d="M4 4h16v16H4z"/><path d="M4 9h16"/><path d="M9 20V9"/>',
};

export function icon(name, size = 16, opts = {}) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", opts.color || "currentColor");
  svg.setAttribute("stroke-width", opts.width || 1.8);
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("icon");
  svg.innerHTML = ICONS[name] || "";
  return svg;
}

export function fmt(n, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(n)) return "–";
  return Number(n).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function duration(s) {
  if (s === null || s === undefined) return "";
  s = Math.round(s);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ${s % 60 ? (s % 60) + " s" : ""}`.trim();
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

// Keep the end of a long path: "…/Experiments/img_test_pipeline"
export function shortPath(path, max = 28) {
  if (!path || path.length <= max) return path || "";
  const sep = path.includes("\\") && !path.includes("/") ? "\\" : "/";
  const parts = path.split(sep).filter(Boolean);
  let out = parts.pop();
  while (parts.length && out.length + parts[parts.length - 1].length + 1 <= max - 2) out = parts.pop() + sep + out;
  return `…${sep}${out}`;
}

export function shortName(image, fields) {
  if (fields && fields.organoid && fields.slice) return `${fields.organoid} · ${fields.slice}`;
  return image.replace(/\.tiff?$/i, "");
}

// ---- toasts ------------------------------------------------------------------
export function toast(message, kind = "") {
  const box = document.getElementById("toasts");
  const el = h("div", { class: `toast ${kind}` }, message);
  box.append(el);
  setTimeout(() => el.remove(), kind === "error" ? 6000 : 3200);
}

export function errorToast(e) {
  toast(e && e.message ? e.message : String(e), "error");
}

// ---- modals ------------------------------------------------------------------
export function modal({ title, text, body, actions = [], wide = false, onClose }) {
  const overlay = h("div", { class: "overlay" });
  const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey); if (onClose) onClose(); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  const foot = h("div", { class: "modal-foot" });
  for (const a of actions) {
    const b = h("button", { class: `btn ${a.kind || ""}`, type: "button" }, a.label);
    b.addEventListener("click", async () => {
      if (a.onClick) {
        const keep = await a.onClick(b);
        if (keep === true) return;
      }
      close();
    });
    if (a.disabled) b.disabled = true;
    a.el = b;
    foot.append(b);
  }
  const box = h("div", { class: `modal ${wide ? "wide" : ""}`, role: "dialog", "aria-modal": "true" },
    h("div", { class: "modal-head" }, h("h2", {}, title), text ? h("p", {}, text) : null),
    body ? h("div", { class: "modal-body" }, body) : null,
    foot);
  overlay.append(box);
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  document.body.append(overlay);
  return { close, overlay, actions };
}

export function confirm(title, text, confirmLabel = "Continue", danger = false) {
  return new Promise((resolve) => {
    let done = false;
    modal({
      title, text,
      actions: [
        { label: "Cancel", onClick: () => { done = true; resolve(false); } },
        { label: confirmLabel, kind: danger ? "danger solid" : "primary", onClick: () => { done = true; resolve(true); } },
      ],
      onClose: () => { if (!done) resolve(false); },
    });
  });
}

// ---- folder picker -------------------------------------------------------------
// mode "images": pick a folder that contains TIFFs. mode "project": pick a project folder.
export function pickFolder({ title, text, mode = "images", start = null }) {
  return new Promise((resolve) => {
    let current = null;
    let picked = false;
    const pathEl = h("span", {}, "");
    const list = h("div", { class: "picker-list" });
    const status = h("div", { class: "status" });
    const upBtn = h("button", { class: "icon-btn", type: "button", "aria-label": "Up one folder" }, icon("up"));
    let m;

    async function load(path) {
      try {
        const r = await api.get(`/api/browse?path=${encodeURIComponent(path || "")}`);
        current = r;
        pathEl.textContent = r.display || "Choose a location";
        upBtn.disabled = !r.parent && !r.path;
        list.innerHTML = "";
        for (const d of r.dirs) {
          list.append(h("button", { class: "picker-item", type: "button", onclick: () => load(d.path) },
            icon(d.is_project ? "project" : "folder", 16, { color: d.is_project ? "#F2C94C" : "#80868E" }),
            h("span", {}, d.name),
            d.is_project ? h("span", { class: "faint" }, "project") : null));
        }
        if (!r.dirs.length) list.append(h("div", { class: "picker-item faint", style: { cursor: "default" } }, "No sub-folders"));
        let ok = false;
        if (!r.path) status.textContent = "";
        else if (mode === "images") {
          ok = r.n_tiffs > 0;
          status.innerHTML = "";
          status.append(ok ? icon("check", 16, { color: "#5BD68A", width: 2 }) : icon("info", 16), ok ? `${r.n_tiffs} TIFF image${r.n_tiffs > 1 ? "s" : ""} here` : "No TIFF images in this folder");
        } else {
          ok = r.is_project;
          status.innerHTML = "";
          status.append(ok ? icon("check", 16, { color: "#5BD68A", width: 2 }) : icon("info", 16), ok ? "NucleiQuant project" : "Open a project folder (images folder › NucleiQuant_projects › project)");
        }
        if (m) m.actions[1].el.disabled = !ok;
      } catch (e) { errorToast(e); }
    }
    upBtn.addEventListener("click", () => load(current && current.parent ? current.parent : ""));
    const body = h("div", { style: { display: "flex", flexDirection: "column", gap: "10px" } },
      h("div", { style: { display: "flex", gap: "8px", alignItems: "center" } }, upBtn, h("div", { class: "picker-path", style: { flex: "1" } }, icon("folder", 16), pathEl)),
      list, status);
    m = modal({
      title, text, body, wide: true,
      actions: [
        { label: "Cancel" },
        { label: mode === "images" ? "Use this folder" : "Open project", kind: "primary", disabled: true, onClick: () => { picked = true; resolve(current.path); } },
      ],
      onClose: () => { if (!picked) resolve(null); },
    });
    load(start);
  });
}

// ---- colour palette popover -----------------------------------------------------
export function colorPopover(anchor, colors, onPick) {
  document.querySelectorAll(".palette").forEach((p) => p.remove());
  const rect = anchor.getBoundingClientRect();
  const pal = h("div", { class: "palette", style: { left: `${rect.left}px`, top: `${rect.bottom + 6}px`, position: "fixed" } });
  for (const c of colors) pal.append(h("button", { type: "button", style: { background: c }, "aria-label": c, onclick: () => { onPick(c); pal.remove(); } }));
  const custom = h("input", { type: "color", "aria-label": "Custom colour" });
  custom.addEventListener("change", () => { onPick(custom.value.toUpperCase()); pal.remove(); });
  pal.append(custom);
  document.body.append(pal);
  setTimeout(() => document.addEventListener("mousedown", function off(e) {
    if (!pal.contains(e.target)) { pal.remove(); document.removeEventListener("mousedown", off); }
  }), 0);
}

export function switchEl(on, onChange, label) {
  const b = h("button", { class: "switch", type: "button", role: "switch", "aria-checked": on ? "true" : "false", "aria-label": label }, h("span"));
  b.addEventListener("click", () => {
    const v = b.getAttribute("aria-checked") !== "true";
    b.setAttribute("aria-checked", v ? "true" : "false");
    onChange(v);
  });
  return b;
}

export function progressBar(frac, big = false) {
  const inner = h("span", { style: { width: `${Math.round((frac || 0) * 100)}%` } });
  return h("div", { class: `progress ${big ? "big" : ""}` }, inner);
}

export function tooltip() {
  let el = document.querySelector(".tooltip");
  if (!el) { el = h("div", { class: "tooltip hidden" }); document.body.append(el); }
  return {
    show(text, x, y) { el.textContent = text; el.classList.remove("hidden"); el.style.left = `${x + 14}px`; el.style.top = `${y + 14}px`; },
    hide() { el.classList.add("hidden"); },
  };
}
