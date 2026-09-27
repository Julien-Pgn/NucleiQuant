# NucleiQuant — project log

The running record of what was asked, what was built, **why**, and **what could go wrong**,
version by version. It exists so that anyone (the author, a collaborator, or a coding agent)
can understand a decision before changing it, and go back to an earlier version if
something breaks.

**How to use it**
- One section per version (newest at the bottom). Each lists the request, the decisions with
  their reasons and weaknesses, what was measured, and the files touched.
- Git is managed by the author: each version corresponds to the author's commit (hash noted
  when known). Coding agents never commit.
- When you change behaviour, add an entry here *and* update `AGENTS.md` (for developers and
  agents) and `Readme.md` / `docs/user_guide.md` (for users).

| Version | Date | Commit | In one line |
|---|---|---|---|
| V1 | 2025 | `6411d5a`…`73d4eec` | StarDist script → notebooks → ilastik → notebook, as published |
| V1.1 | 2026-09 | `e6a8bd1`, `3637aae` | Docker environment, filename-parsing fixes, .h5 crop masks |
| V2.0 | 2026-09-25 | `5a5e62b` | All-in-one browser app |
| V2.1 | 2026-09-26 | *(not committed yet — together with V2.2)* | Per-crop labeling, category colours, choice of the 100 %, this log |
| V2.2 | 2026-09-26 | *(not committed yet)* | Independent test set (blind), automatic port forwarding over SSH |

---

## Before V2

**V1** (Pigeon et al., bioRxiv 2025, doi 10.1101/2025.10.27.684791): StarDist model
`stardist_haug2` fine-tuned on 134 annotated organoid images → `scripts/01_segmentation.py`
→ `notebooks/02_image_selection.ipynb` (intensity survey, 3 images per clone at Q10/Q50/Q90,
crop) → **ilastik** object classification (Dead, Unstained + marker categories) →
`notebooks/03_quantifications.ipynb` (counts, Excel) → proportions and statistics in R.

**Code audit (2026-09-13 → 22).** ~40 findings in six sections.
- Section 1 (filename parsing silently shifting fields) — **fixed**: shared
  `nucleiquant/metadata.py` raising on malformed names.
- Section 2 (scientific validity) — **reviewed with the author**: threshold tuned on the
  validation split = StarDist's own recipe (not a flaw); truncated boundary cells were
  excluded by hand in ilastik (not a flaw); validation leakage from offline augmentation
  before the split is real but the published split was kept; normalisation percentile
  0.2 (vs 1 in training) kept on purpose (pmin = 1 oversegments dark images; 38,838 vs
  38,840 nuclei — negligible); slice-count confound handled downstream in R.
- Sections 3–6 (can't-run bugs, reproducibility, fragile assumptions, hygiene) — not started.

**Environment.** The model was trained with TF 2.4, but TF 2.4 / cuDNN 8.1 hang on Blackwell
GPUs (RTX 5070 Ti). The NGC image `tensorflow:25.02-tf2-py3` (TF 2.17, CUDA 12.8) runs it
and reproduces the shipped label image to within 3 nuclei out of 38,841. numpy is pinned
to 1.26.4 (numpy 2 breaks that TensorFlow build).

---

## V2.0 — all-in-one app (2026-09-25)

**Request.** Do everything in one place, like QuPath + StarDist + object classification:
intensity survey and choice of training images (as in V1), crops, segmentation with
stardist_haug2, labeling on top of the image like ImageJ ROIs, user-defined categories plus
Dead and Unstained, 50–60 labels per category, preview, then classify everything, one
Excel file with counts, proportions and statistics from the metadata in the file names.
For the general public: launched with a double-click, used entirely from a GUI; simple,
minimalist, modern design; documentation for users and for coding agents (what it can and
can't do). QuPath-style per-marker classification postponed to V3; an MCP server later.

**Decisions**

| Decision | Why | Weaknesses |
|---|---|---|
| Browser app (FastAPI + plain JS, no build step) served from the Docker image | One tested environment on every OS; nothing to install besides Docker; usable from a laptop against a GPU workstation; agents can edit plain JS | We maintain our own viewer; no whole-slide tiling; single user, no login |
| Own random forest (scikit-learn), not ilastik headless | Headless ilastik can't be trained without its GUI and clashes with the TF image's numpy; in-process forest retrains in ~1 s | Not bit-identical to ilastik; a saved model is tied to the scikit-learn version (labels + features are saved so it can be rebuilt) |
| ~300 features per nucleus (ilastik set + texture, radial, perinuclear, normalised, context); no orientation or position | The author asked for as much information as possible; normalised intensities make crops and full images comparable | Features are in pixels (magnification-specific); many correlated features; context features can learn "region" rather than "cell type" |
| Segmentation-free survey (Otsu on DAPI) | Lets the user start labeling without segmenting every image first | Ranks images like V1 (ρ 0.94–0.99) but picks can differ among near-ties |
| Crops segmented on their own, with the full image's normalisation range (author's choice) | Fast; same scaling as the full image | Nuclei cut by the crop edge can't be labeled |
| Crop auto-placed on marker-positive tissue | "Most tissue" landed in necrotic cores (all dead cells) | Heuristic; the user may need to drag the frame |
| Exclusive categories; Dead and Unstained always present | Matches V1/ilastik and the request | Double positives must be explicit categories (V3 will address) |
| Proportions + Mann-Whitney / Kruskal-Wallis + Dunn, Holm, organoid = unit | Few organoids per group; cells are not independent | No mixed models (clone within genotype) — use R with the exported counts |
| Double-click launchers + in-app folder picker; projects in `<images>/NucleiQuant_projects/` | General public, no terminal | Windows/macOS launchers untested on real machines |
| `AGENTS.md` (+ `CLAUDE.md` importing it) | One source of truth for any coding agent | Must be kept up to date by hand |

**Found while building**
- oneDNN makes this TF build's CPU inference ~350× slower (173 s vs 0.5 s per 1024²):
  disabled (`TF_ENABLE_ONEDNN_OPTS=0`); CPU-only segmentation of a full image now takes 8 s.
- V1's ilastik never predicted "Unstained" on the test data → a category may be left
  without labels (with a warning).
- ROI sets were as large as V1's (~20 MB/image): written with deflate compression (−43 %).
- On macOS, git ignores case: a `NucleiQuant/` ignore rule would also hit the `nucleiquant/`
  package → projects live in `NucleiQuant_projects/`.
- The author works over SSH from a Mac: local links need port forwarding (the launcher now
  prints how).

**Validation (12 test images, ~600,000 nuclei; labels sampled from V1's ilastik output,
55 per category over all crops).** Held-out (leave-one-crop-out) accuracy 93.6 %; per-nucleus
agreement with V1 93.6 %, Cohen's κ 0.89; mean intensities equal ilastik's to 1e-4;
segmentation 38,840 vs 38,841 shipped nuclei; 12 images in 158 s (RTX 5070 Ti). This
measures agreement with V1, not ground truth.

---

## V2.1 — per-crop labeling, category colours, choice of the 100 % (2026-09-26)

**Request (author, after a first real project).** (1) Fewer mandatory labels: 10 per
category **per crop**, so labeling is homogeneous across crops, with 3 crops per clone;
recommended, not mandatory, because a crop may not contain 10 cells of every category.
(2) Change the colour of a category while labeling (e.g. PAX6+ in green like its channel).
(3) Results as vertical bar plots, with an interactive choice of what makes 100 % (e.g.
proportions among stained cells only). (4) Keep documentation and this log up to date;
always say why and name weaknesses.

**What the author's first real project showed** (`dM_ J140_PBC`: PAX6/BRN2/SATB2, clones H9
and PA, 82 images, 6 crops, 258 labels):
- Labels were very uneven: two crops (one per clone) had **no labels**; others lacked whole
  categories (crop01: no BRN2/Unstained; crop04: no PAX6/Dead).
- Held-out accuracy was **74 %** (vs 94 % on the test data). Leave-one-crop-out testing
  punishes exactly this: a crop whose categories are missing from the others is predicted
  badly. → per-crop balance is the right fix.
- Channels kept their default names ("Channel 2…") and categories got default colours
  (PAX6 in orange) → colours should be easy to match to channels.
- File names contain a space (`dM_ J140`) → the Day field read `" J140"`.

**Changes**

| Change | Why | Weaknesses / risks |
|---|---|---|
| Recommendation of `labels_per_crop` = 10 of each category **in each crop** (replaces "50 per category in total"); counters show this crop's count and the total; each crop shows its progress; header shows what is left in this crop | Equal weight for dim, typical and bright images; directly addresses the unbalanced real project | With 5 categories × 6 crops that is 300 labels (more than 5 × 50 = 250); crops lacking a category will always show a shortfall |
| Escape hatch: "Preview classification" works as soon as **two categories** have labels; if crops are short, a dialog lists what is missing where, with **Keep labeling** / **Preview anyway** | The author asked for a recommendation, not a rule | Users can still train on very unbalanced labels; the held-out accuracy on the Preview screen is the signal to watch |
| Category colours: picker offers the **channel colours by name**, other colours and a custom colour; the "Add" row has its own colour button | Match a category to its marker's channel colour (e.g. PAX6+ green) | A colour identical to its channel can be hard to see on bright cells (dark halo mitigates; hold H); no colour-blind check |
| Fix: the new-category draft (name, colour) survives redraws of the panel | Found by the automated walkthrough: a colour picked while the crop was loading was lost | — |
| Results: **vertical stacked bars** per organoid (or mean per genotype, ± SD in tooltips), hover shows % and cell counts, **SVG download** (white background) | Requested; figure-ready | Stacked means hide the spread (see tooltips, box plots in `plots/`, and the statistics) |
| **Choice of the 100 %** ("reference"): tick categories, or presets All nuclei / Living cells / **Stained cells** (all but Dead and Unstained); bars and statistics update instantly; **Save in Excel** keeps a custom reference | Proportions among stained cells (or any subset) were asked for; computed from saved per-image counts, so no reclassification | Proportions among stained cells depend on how well *Unstained* was trained (if it has few labels, stained proportions are inflated); Holm correction is within one reference, not across the several references you may report |
| Excel: `proportions` and `statistics` for every reference (all, living, stained + saved); one plot set per reference | Keeps the file consistent with the screen | More columns/sheets rows; column names changed from V2.0 (`S (% all)` → `S (% all nuclei)`, `S (% living)` → `S (% living cells)`) — update any script that read V2.0 files |
| File-name parts are trimmed (`" J140"` → `"J140"`) | Seen in the author's files | Two names differing only by spaces now group together (intended) |
| `PROJECT.md` (this file); `AGENTS.md` / `CLAUDE.md` / user docs updated; rule: agents never commit | Requested: transparency and the ability to navigate versions | This log is maintained by hand |
| `tests/e2e/check_modules.py` (JS syntax check in Chromium, no Node.js needed) | A syntax error in one module blocks the whole app | Needs a running app |

**Compatibility.** Existing V2.0 projects open unchanged (checked read-only on
`dM_ J140_PBC`): old settings are kept, the new counters and references work, and the Results
screen computes any 100 % from the existing per-image summaries. Click **Recalculate** on the
Results screen to regenerate the Excel file with the new sheets.

**Validation.** 30 unit tests pass (new: per-crop progress, references and 100 % views,
Excel columns, filename trimming). The browser walkthrough passes end to end (colour chosen
from a channel, per-crop counters, shortfall dialog, stained-cells view, custom 100 % saved
in Excel). V1 comparison with the new protocol (18 labels per category per crop, V1 labels):
see the numbers below.

| Labeling protocol (labels copied from V1) | Held-out accuracy | Agreement with V1 (all ~600k nuclei) | Cohen's κ |
|---|---|---|---|
| V2.0: 55 per category, sampled anywhere | 93.6 % | 93.6 % | 0.89 |
| V2.1: 18 per category **in each crop** | 90.7 % | 93.7 % | 0.89 |

Reading: the classifier is as good as before (agreement with V1 on every nucleus is
unchanged). The *held-out accuracy* shown on the Preview screen is lower because it is now
measured on a harder, fairer set: each crop contributes the same number of labels per
category, including its rarer and more ambiguous cells, instead of mostly easy cells from
crops where a category is abundant. So **held-out accuracies of V2.0 and V2.1 projects are not
directly comparable**; compare within a version. N (the category V1 and V2 disagree on most)
still has the weakest per-image count correlation (0.56; Dead 0.99, S 0.96, T 0.98).
The batch took 228 s here vs 158 s in V2.0 because the app was running on the same GPU at
the same time (not a code slowdown).

**Files.** `nucleiquant/api.py` (`label_progress`, results views, saved references),
`quantify.py` (references, per-reference proportions/statistics/plots, `results_view`),
`project.py` (`labels_per_crop`), `metadata.py` (trim), `app/server.py` (3 endpoints),
`app/static/js/screens/label.js`, `results.js`, `project.js`, `js/ui.js` (colour picker),
`js/main.js`, `css/app.css`; `tests/test_labels_references.py`,
`tests/test_classifier_quantify.py`, `tests/e2e/*`; `scripts/validation/*`; docs.

---

## V2.2 — independent test set, automatic port forwarding (2026-09-26)

**Request.** (1) Forward the app's port automatically, so it works both on the workstation
and from the Mac over SSH without manual steps; document it in the README. (2) A **test
accuracy** to judge whether the labeling is good enough and to answer reviewers. The author
asked which strategy is best: other crops as test crops, smaller crops, sub-crops inside the
training crops with a second annotation, and whether 5 cells per label per crop is enough.

**Strategy chosen (and why)**

| Option | Decision | Reason |
|---|---|---|
| Test crops from **other images** | ✅ random images per clone, never used for training | Independence is what reviewers expect; random (not intensity-picked) so the test represents the whole experiment |
| **Smaller** test crops | ✅ 35 % of the image side (training: 50 %) | Only a few cells per category are needed; faster to build and to label |
| **Sub-crops of training crops** | ❌ | Same slice, same local staining, neighbouring cells: leakage, optimistic accuracy |
| **Second annotation** of the same cells | Not now | Measures annotator consistency (intra-rater κ), not the classifier — a possible later feature |
| **5 cells per category per crop** | ✅ with 2 test images per clone | 2 clones × 2 images × 5 categories × 5 = 100 test cells → overall accuracy known to about ±6 % (95 % CI at 90 %); each category (20 cells) to about ±15 %. The report always shows the intervals |
| Blind labeling, test labels never trained on, every evaluation logged | ✅ | The conditions that make a test accuracy credible; the log keeps repeated evaluations transparent |
| Headline = **balanced accuracy** | ✅ | Test cells are sampled per category, so plain accuracy reflects the test's balance, not the experiment's |

**Changes**

| Change | Why | Weaknesses / risks |
|---|---|---|
| New optional step **Test** (sidebar between Preview and Results): intro → create test crops (job) → blind labeling (Label screen in test mode: no predictions, no category editing) → **Evaluate accuracy** → report | Requested; reviewer-ready | Optional: users may skip it; one more screen |
| Report: balanced accuracy (bootstrap CI), accuracy (Wilson CI), Cohen's κ (bootstrap CI), per category recall/precision/F1 (Wilson CIs), per test image, confusion matrix, every evaluation, **methods paragraph** (copy button); tile on Results; Excel sheet `test_set` | Everything a reviewer asks for, in one place | CIs treat cells as independent; cells from one image are correlated, so true uncertainty is somewhat larger (stated in the report). Precision is at the test set's category balance, not the experiment's prevalence. A category with no test cells is reported as "not tested" |
| Test data kept apart: `test/` folder, `test/annotations.csv`, test crops listed in `project.json → test_crops`; training never reads them | Prevents leakage by construction | If the user copies test cells into training by hand, the test is no longer independent (documented as good practice) |
| Settings: test images per clone (2), test crop size (35 %), test labels per category per crop (5) | Adjustable to the experiment | Changing them after creating the test crops has no effect on existing test crops |
| `.vscode/settings.json`: auto-forward port 8765 and open the browser once when VS Code is connected over SSH | "It should just work" from the Mac | **Not testable from the workstation**; relies on VS Code detecting the link printed by the launcher (started from VS Code's terminal) |
| README › *From another computer (SSH)*: one `LocalForward 127.0.0.1:8765 127.0.0.1:8765` line in the laptop's `~/.ssh/config` (always on, VS Code or plain ssh); launcher prints it when run over SSH | The permanent, editor-independent solution; VS Code documents that it honours `LocalForward` | Must be done once on each laptop (we can't edit the laptop from the workstation); a second simultaneous SSH session prints a harmless "Address already in use" |

**Validation.** 33 unit tests pass (new: Wilson intervals, metrics against hand-computed
values, reproducible test-image selection that never picks training images). Browser
walkthrough passes end to end in four parts, now including the test step (creation, blind
labeling with no prediction legend, evaluation, report, Results tile, Excel sheet). Demo
(one clone, labels copied from V1, 5 per category per test crop): balanced accuracy 92.5 %
(95 % CI 83–100 %) on 40 cells from 2 unseen images, κ 0.90 — wide intervals because
40 cells is few; a real 2-clone project would have ~100.

**Bugs found by the walkthrough and fixed:** test crops were looked up only among training
crops (crop label, strip and channel panel didn't draw); a stray "null" in the header; the
prediction legend was briefly visible before hiding (now hidden from the start).

**Files.** `nucleiquant/evaluation.py` (new), `api.py` (test set, routing of labels),
`survey.py` (`pick_test_images`), `crops.py` (folder/fraction), `project.py` (settings,
`is_test_crop`), `quantify.py` (`test_set` sheet), `app/server.py`,
`app/static/js/screens/test.js` (new), `label.js` (test mode), `results.js` (tile),
`project.js`, `main.js`, `css/app.css`; `.vscode/settings.json`; `start-nucleiquant.sh`;
tests and walkthrough; `Readme.md`, `docs/user_guide.md`, `AGENTS.md`.

---

## Roadmap and open questions

- **V3**: per-marker (QuPath-style composite) classification — one +/− classifier per marker
  plus Dead; phenotypes = combinations (see `AGENTS.md`).
- **MCP server** wrapping `nucleiquant/api.py`, so other agents can drive NucleiQuant.
- Publish the image to GHCR (workflow ready; runs on a `v*` tag pushed by the author).
- Test the Windows and macOS launchers on real machines.
- Audit sections 3–6.
- Optional: mixed models (clone within genotype) — today in R from the Excel counts.
- Optional: second annotation of the same cells (intra-/inter-rater agreement), as a
  complement to the test accuracy.

## How to go back to a version

The author commits each version. To look at or restore an earlier one:

```bash
git log --oneline                    # find the version's commit
git switch --detach 5a5e62b          # look at V2.0 (read-only); come back with: git switch dev
git restore --source 5a5e62b -- nucleiquant/quantify.py   # bring back one file from V2.0
```

Projects (in `NucleiQuant_projects/`) are not in git: they keep working across versions,
and `project.json` gains new settings with default values when opened by a newer version.
