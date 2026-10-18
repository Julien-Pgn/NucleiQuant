"""Build the version canvas: every screen of the app, version by version, side by side.

The screenshots of each version are taken from git (docs/images/ at the version's
commit), downscaled to JPEG and written with a self-contained page to docs/versions/.
Run after each version (host Python with Pillow, or the Docker image):

    python3 scripts/version_canvas.py
    ./run_container.sh exec_cpu python scripts/version_canvas.py

Then publish docs/versions/index.html (with docs/versions/img/) as the claude.ai
artifact noted in PROJECT.md, so the canvas also lives outside this folder.
Add one entry to VERSIONS for each version logged in PROJECT.md.
"""

import io
import json
import os
import subprocess

from PIL import Image, ImageChops

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "docs", "versions")
WIDTH = 960  # px, enough to read the UI; keeps the page under the artifact size limit

# One entry per version: the commit whose docs/images/ shows that version
VERSIONS = [
    {"tag": "V2.0", "commit": "5a5e62b", "date": "2026-09-25", "title": "All-in-one browser app",
     "notes": ["Six steps in one local app: Project, Survey, Crops, Label, Preview, Results",
               "Docker image with the StarDist model; GPU or CPU",
               "Validated against V1 (ilastik): 93.6 % per-nucleus agreement, κ 0.89"]},
    {"tag": "V2.1–2.2", "commit": "cd72f2a", "date": "2026-09-26", "title": "Per-crop labeling, colours, 100 %, test set",
     "notes": ["10 labels of each category per crop (recommended, not enforced); shortfall dialog",
               "Category colours from the channel colours; interactive stacked bars with a chosen 100 %",
               "Optional Test step: blind labels on unseen images, balanced accuracy, κ, 95 % CIs, methods text",
               "Automatic port forwarding for SSH use"]},
    {"tag": "V2.3", "commit": "4495e59", "date": "2026-10-18", "title": "Clearer flow and numbers",
     "notes": ["Rename categories, channel names as quick picks, replace a crop's image",
               "15 labels per category per crop; Dead dark grey, Unstained DAPI-blue",
               "Preview: show/hide a category, what the classifier measures",
               "Test crops built with the training crops; Preview → Test decision → Results",
               "Macro F1 and plain-language explanations in the test report; version shown in the app"]},
]

# Screens in workflow order: file stem -> label. Unknown files are appended as they come.
SCREENS = [
    ("01-home", "Home"),
    ("01b-folder-picker", "Choose the images folder"),
    ("02-project", "1 · Project"),
    ("03-survey", "2 · Survey"),
    ("04a-crops-running", "3 · Crops, segmenting"),
    ("04-crops", "3 · Crops"),
    ("04b-replace-dialog", "3 · Replace a crop's image"),
    ("05a-label-empty", "4 · Label, start"),
    ("05c-colour-picker", "4 · Category colour"),
    ("05-label", "4 · Label, labeling"),
    ("05b-unused-warning", "4 · Missing labels dialog"),
    ("06-preview", "5 · Preview"),
    ("06b-preview-confusion", "5 · Where it gets confused"),
    ("06c-test-decide", "6 · Test the classifier?"),
    ("10b-test-intro", "6 · Test intro"),
    ("10c-test-labels", "6 · Blind test labeling"),
    ("11-test-report", "6 · Test report"),
    ("07-running", "7 · Classifying all images"),
    ("08-results", "7 · Results"),
    ("08b-results-stained", "7 · Results, 100 % = stained"),
    ("08c-results-custom", "7 · Results, custom 100 %"),
    ("09-image-view", "7 · Image view"),
    ("10-help", "Help"),
]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def images_at(commit):
    names = git("ls-tree", "--name-only", commit, "docs/images/").decode().split()
    return [os.path.basename(n)[:-4] for n in names if n.endswith(".png") and "failure" not in n]


def load(commit, stem):
    return Image.open(io.BytesIO(git("show", f"{commit}:docs/images/{stem}.png"))).convert("RGB")


def difference(a, b):
    """Fraction of pixels that differ clearly (> 24 grey levels) between two screenshots.

    Calibrated on the walkthrough screenshots: unchanged screens stay below 0.08 %,
    small UI changes (an icon, a number) are above 0.2 %.
    """
    ga, gb = a.convert("L"), b.convert("L")
    if gb.size != ga.size:
        gb = gb.resize(ga.size)
    hist = ImageChops.difference(ga, gb).histogram()
    return sum(hist[25:]) / sum(hist)


def main():
    os.makedirs(os.path.join(OUT, "img"), exist_ok=True)
    order = [s for s, _ in SCREENS]
    labels = dict(SCREENS)
    manifest = {"versions": [], "screens": [], "cells": {}}
    previous = {}
    for v in VERSIONS:
        stems = images_at(v["commit"])
        for s in stems:
            if s not in order:
                order.append(s)
                labels[s] = s
        folder = os.path.join(OUT, "img", v["tag"].replace("–", "-"))
        os.makedirs(folder, exist_ok=True)
        current = {}
        for s in stems:
            im = load(v["commit"], s)
            current[s] = im
            w, h = im.size
            small = im.resize((WIDTH, round(h * WIDTH / w)), Image.LANCZOS)
            rel = f"img/{os.path.basename(folder)}/{s}.jpg"
            small.save(os.path.join(OUT, rel), "JPEG", quality=82, optimize=True)
            status = "new" if s not in previous else ("changed" if difference(previous[s], im) > 0.001 else "same")
            manifest["cells"][f"{v['tag']}|{s}"] = {"src": rel, "w": small.size[0], "h": small.size[1], "status": status}
        previous = current
        manifest["versions"].append({k: v[k] for k in ("tag", "commit", "date", "title", "notes")})
        print(f"{v['tag']}: {len(stems)} screens")
    manifest["screens"] = [{"id": s, "label": labels[s]} for s in order]
    fragment = TEMPLATE.replace("__MANIFEST__", json.dumps(manifest, ensure_ascii=False))
    # Local copy: a complete document. The claude.ai artifact takes the bare fragment
    # (it adds its own document skeleton): --fragment PATH writes that.
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1">\n' + fragment + "\n</html>\n")
    import sys
    if "--fragment" in sys.argv:
        with open(sys.argv[sys.argv.index("--fragment") + 1], "w", encoding="utf-8") as f:
            f.write(fragment)
    total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(OUT) for f in fs)
    print(f"written {OUT} ({total / 1e6:.1f} MB)")


TEMPLATE = r"""<title>NucleiQuant Version Canvas</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500&display=swap">
<style>
:root {
  color-scheme: dark;
  --bg: #111316; --panel: #1B1F24; --panel-2: #22272E; --line: #2B3036; --line-2: #3A4049;
  --text: #EDEEF0; --text-2: #A3A9B1; --text-3: #80868E; --accent: #F2C94C; --accent-bg: rgba(242,201,76,0.14);
  --new: #5BD68A; --changed: #F2C94C; --same: #5A6068;
  --sans: "Geist", "Helvetica Neue", Arial, sans-serif; --mono: "Geist Mono", "SFMono-Regular", Menlo, monospace;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.5 var(--sans); padding-block: 0 48px; }
.wrap { padding-inline: 24px; }
header.top { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 12px 24px; padding-block: 28px 18px; border-bottom: 1px solid var(--line); }
header.top h1 { margin: 0; font-size: 24px; font-weight: 600; letter-spacing: -0.01em; display: flex; align-items: center; gap: 10px; text-wrap: balance; }
header.top p { margin: 0; color: var(--text-2); max-width: 64ch; }
.legend { display: flex; gap: 14px; align-items: center; color: var(--text-3); font-size: 12.5px; margin-left: auto; }
.legend i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: 1px; }
.timeline { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; padding-block: 20px; }
.ver { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 16px 18px; display: flex; flex-direction: column; gap: 8px; }
.ver .tag { font: 500 13px var(--mono); color: var(--accent); display: flex; gap: 10px; align-items: baseline; }
.ver .tag span { color: var(--text-3); font-weight: 400; }
.ver h2 { margin: 0; font-size: 16px; font-weight: 600; }
.ver ul { margin: 0; padding-left: 18px; color: var(--text-2); font-size: 13px; display: flex; flex-direction: column; gap: 3px; }
.ver .n { color: var(--text-3); font: 12px var(--mono); }
.grid-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 10px; background: var(--panel); }
table.grid { border-collapse: separate; border-spacing: 0; min-width: 100%; }
table.grid th, table.grid td { padding: 10px 12px; border-bottom: 1px solid var(--line); vertical-align: top; text-align: left; }
table.grid thead th { position: sticky; top: 0; background: var(--panel-2); z-index: 2; font: 500 13px var(--mono); color: var(--accent); }
table.grid thead th small { display: block; color: var(--text-3); font-weight: 400; font-size: 11.5px; }
table.grid th.screen { position: sticky; left: 0; background: var(--panel); z-index: 1; width: 200px; min-width: 160px; font-weight: 500; font-size: 13px; }
table.grid thead th.screen { z-index: 3; background: var(--panel-2); color: var(--text-3); font: 500 11px var(--sans); letter-spacing: 0.06em; text-transform: uppercase; }
table.grid tr:last-child td, table.grid tr:last-child th { border-bottom: none; }
.cell { position: relative; width: 300px; max-width: 42vw; }
.cell button { display: block; width: 100%; padding: 0; border: 1px solid var(--line-2); border-radius: 6px; background: #000; cursor: pointer; overflow: hidden; }
.cell button:hover, .cell button:focus-visible { border-color: var(--accent); outline: none; }
.cell img { display: block; width: 100%; height: auto; }
.cell .st { position: absolute; top: 6px; left: 6px; font: 500 11px var(--mono); padding: 2px 7px; border-radius: 999px; background: rgba(0,0,0,0.7); border: 1px solid transparent; }
.st.new { color: var(--new); border-color: var(--new); }
.st.changed { color: var(--changed); border-color: var(--changed); }
.st.same { color: var(--text-3); }
.none { color: var(--text-3); font-size: 12.5px; padding: 8px 2px; font-style: italic; }
.foot { color: var(--text-3); font-size: 12.5px; margin-top: 14px; max-width: 80ch; }
/* lightbox */
.lb { position: fixed; inset: 0; background: rgba(0,0,0,0.88); display: none; flex-direction: column; z-index: 10; }
.lb.on { display: flex; }
.lb .bar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; padding: 12px 20px; padding-top: calc(12px + env(safe-area-inset-top, 0px)); color: var(--text); }
.lb .bar .name { font-weight: 600; font-size: 15px; margin-right: 6px; }
.lb .tabs { display: flex; gap: 6px; }
.lb .tabs button { font: 500 12.5px var(--mono); padding: 5px 10px; border-radius: 6px; border: 1px solid var(--line-2); background: var(--panel); color: var(--text-2); cursor: pointer; }
.lb .tabs button[aria-pressed="true"] { background: var(--accent-bg); color: var(--accent); border-color: var(--accent); }
.lb .tabs button:disabled { opacity: 0.35; cursor: default; }
.lb .bar .hint { color: var(--text-3); font-size: 12.5px; }
.lb .bar .close { margin-left: auto; width: 36px; height: 36px; border-radius: 8px; border: 1px solid var(--line-2); background: var(--panel); color: var(--text); cursor: pointer; font-size: 18px; }
.lb .view { flex: 1; display: flex; align-items: center; justify-content: center; padding: 0 20px 20px; min-height: 0; }
.lb .view img { max-width: 100%; max-height: 100%; border: 1px solid var(--line-2); border-radius: 6px; background: #000; }
@media (max-width: 700px) { .wrap { padding-inline: 16px; } .cell { width: 220px; } .legend { margin-left: 0; } }
@media (prefers-reduced-motion: no-preference) { .cell button { transition: border-color 0.15s; } }
</style>
<div class="wrap">
  <header class="top">
    <div style="display:flex;flex-direction:column;gap:6px">
      <h1><svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 3.5c4.9 0 8.5 3.4 8.5 8.2 0 4.9-3.9 8.8-8.9 8.8-4.8 0-8.1-3.6-8.1-8.3 0-4.9 3.7-8.7 8.5-8.7z" stroke="#F2C94C" stroke-width="1.8"/><circle cx="12.4" cy="12" r="4.2" fill="#EDEEF0"/></svg>NucleiQuant Version Canvas</h1>
      <p>Every screen of the app, version by version. Click a screenshot to see it large and flip between versions of the same screen.</p>
    </div>
    <div class="legend"><span><i style="background:var(--new)"></i>new screen</span><span><i style="background:var(--changed)"></i>looks different from the previous version</span><span><i style="background:var(--same)"></i>same</span></div>
  </header>
  <section class="timeline" id="timeline" aria-label="Versions"></section>
  <div class="grid-wrap"><table class="grid" id="grid"><thead></thead><tbody></tbody></table></div>
  <p class="foot">Screenshots are the ones taken by the automated walkthrough of each version (docs/images at that version's commit); "looks different" compares the pixels of the previous version's screenshot, so a different image or label count also counts. Regenerate with scripts/version_canvas.py.</p>
</div>
<div class="lb" id="lb" role="dialog" aria-modal="true" aria-label="Screenshot">
  <div class="bar"><span class="name" id="lbName"></span><div class="tabs" id="lbTabs"></div><span class="hint">← → switch version · Esc close</span><button class="close" id="lbClose" aria-label="Close">×</button></div>
  <div class="view"><img id="lbImg" alt=""></div>
</div>
<script>
const M = __MANIFEST__;
const cell = (v, s) => M.cells[`${v}|${s}`];
const el = (tag, attrs = {}, ...kids) => { const e = document.createElement(tag); for (const [k, val] of Object.entries(attrs)) { if (k === "class") e.className = val; else if (k.startsWith("on")) e.addEventListener(k.slice(2), val); else if (val != null) e.setAttribute(k, val); } for (const k of kids.flat()) if (k != null) e.append(k); return e; };

const tl = document.getElementById("timeline");
for (const v of M.versions) {
  const n = M.screens.filter((s) => cell(v.tag, s.id)).length;
  tl.append(el("article", { class: "ver" },
    el("div", { class: "tag" }, v.tag, el("span", {}, v.date)),
    el("h2", {}, v.title),
    el("ul", {}, ...v.notes.map((t) => el("li", {}, t))),
    el("div", { class: "n" }, `${n} screens · commit ${v.commit}`)));
}

const thead = document.querySelector("#grid thead"), tbody = document.querySelector("#grid tbody");
thead.append(el("tr", {}, el("th", { class: "screen" }, "Screen"), ...M.versions.map((v) => el("th", {}, v.tag, el("small", {}, `${v.date} · ${v.title}`)))));
for (const s of M.screens) {
  const tr = el("tr", {}, el("th", { class: "screen", scope: "row" }, s.label));
  for (const v of M.versions) {
    const c = cell(v.tag, s.id);
    tr.append(el("td", {}, c
      ? el("div", { class: "cell" },
          el("button", { type: "button", "aria-label": `${s.label}, ${v.tag}`, onclick: () => open(s.id, v.tag) },
            el("img", { src: c.src, width: c.w, height: c.h, loading: "lazy", alt: "" })),
          el("span", { class: `st ${c.status}` }, c.status === "new" ? "new" : c.status === "changed" ? "different" : "same"))
      : el("div", { class: "none" }, "not in this version")));
  }
  tbody.append(tr);
}

// Lightbox: one screen, switch versions
const lb = document.getElementById("lb"), lbImg = document.getElementById("lbImg"), lbName = document.getElementById("lbName"), lbTabs = document.getElementById("lbTabs");
let cur = null;
function open(sid, tag) {
  cur = { sid, tag };
  const s = M.screens.find((x) => x.id === sid);
  lbName.textContent = s.label;
  lbTabs.innerHTML = "";
  for (const v of M.versions) {
    const c = cell(v.tag, sid);
    lbTabs.append(el("button", { type: "button", disabled: c ? null : "", "aria-pressed": v.tag === tag ? "true" : "false", onclick: () => open(sid, v.tag) }, v.tag));
  }
  const c = cell(tag, sid);
  lbImg.src = c.src; lbImg.alt = `${s.label}, ${tag}`;
  lb.classList.add("on");
}
function close() { lb.classList.remove("on"); cur = null; }
function step(d) {
  if (!cur) return;
  const tags = M.versions.map((v) => v.tag).filter((t) => cell(t, cur.sid));
  const i = tags.indexOf(cur.tag);
  const j = i + d;
  if (j >= 0 && j < tags.length) open(cur.sid, tags[j]);
}
document.getElementById("lbClose").addEventListener("click", close);
lb.addEventListener("click", (e) => { if (e.target === lb || e.target.classList.contains("view")) close(); });
document.addEventListener("keydown", (e) => {
  if (!cur) return;
  if (e.key === "Escape") close();
  if (e.key === "ArrowRight") step(1);
  if (e.key === "ArrowLeft") step(-1);
});
</script>
"""


if __name__ == "__main__":
    main()
