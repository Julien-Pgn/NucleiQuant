# AGENTS.md — working on NucleiQuant

Guide for coding agents (Claude Code, Codex, Cursor, Gemini CLI…) and developers who
modify this project. Users of the app should read `Readme.md` and `docs/user_guide.md`.

## What the project is

NucleiQuant counts cell types in 2D multichannel fluorescence images (immunostainings of
1–4 markers + a nuclear stain), the way QuPath + StarDist + an object classifier would,
in one browser app launched by a double-click. It is the V2 of the pipeline published in
Pigeon et al., bioRxiv 2025 (doi 10.1101/2025.10.27.684791). V1 (StarDist script →
notebooks → ilastik → notebook) is kept in `scripts/01_segmentation.py` and `notebooks/`.

The workflow, one screen per step:

1. **Project**: images folder, filename pattern (metadata lives in file names), channel
   names/colours, nuclear channel, clone → genotype table.
2. **Survey**: segmentation-free intensity measurement of every image; picks the images
   nearest the 10th/50th/90th percentile of a chosen channel per clone for training.
3. **Crops**: a window per training image (auto-placed on marker-positive tissue,
   draggable), segmented with `stardist_haug2` using the full image's normalisation range.
4. **Label**: the user clicks nuclei into categories. `Dead` and `Unstained` always exist;
   the user adds the others. ≥ `label_target` (50) labels per used category.
5. **Preview**: random forest trained on the labels, tested leave-one-crop-out, every crop
   recoloured by prediction; the user corrects and retrains, then validates.
6. **Results**: every image segmented, measured, classified; Excel workbook, plots,
   Mann-Whitney / Kruskal-Wallis + Dunn statistics (organoid = unit), Fiji ROIs.

Audience: biologists, not programmers. Everything must be doable from the GUI.

## Commands

There is no local Python stack: everything runs in the Docker image (`nucleiquant:v2`).

```bash
./start-nucleiquant.sh                 # what users run: build once, detect GPU, open the app
./run_container.sh build               # rebuild the image after changing pyproject.toml/Dockerfile
./run_container.sh app                 # dev: app on http://localhost:8765, repo mounted live
./run_container.sh test                # pytest (tests/), ~5 s
./run_container.sh exec python -m nucleiquant batch <project folder>        # headless batch
./run_container.sh exec python scripts/validation/compare_with_v1.py --fresh # full pipeline vs V1
tests/e2e/run_walkthrough.sh           # drives the real UI in headless Chromium, saves docs/images/*.png
```

The repo is mounted at `/workspace`; Python code changes need no rebuild (editable install),
just restart the app. Frontend changes need only a browser reload.

## Architecture

```
nucleiquant/
  api.py           Session: every step as a plain function. The ONLY place with workflow logic.
  app/server.py    FastAPI routes -> api.Session (thin). Binary endpoints for the viewer.
  app/static/      Frontend: plain ES modules + CSS, no build step, no npm.
    js/main.js       router (#/project, #/survey, …), sidebar, help drawer, quit
    js/viewer.js     canvas viewer: 16-bit composite in the browser, vector outlines, pan/zoom, hit-test
    js/screens/*.js  one module per screen (label.js serves Label and Preview)
    css/app.css      design tokens (dark theme, accent #F2C94C = ImageJ ROI yellow), components
    fonts/           Geist + Geist Mono (OFL), bundled so the app works offline
  __main__.py      CLI: `serve`, `batch`
  project.py       project folder + project.json (atomic writes), defaults, recent projects
  metadata.py      filename -> fields (V1 regex by default; templates like clone_day_organoid_slice)
  io.py            TIFF read as (C,Y,X), write with ImageJ metadata; labels as .tif + .h5
  survey.py        Otsu-on-DAPI survey, per-image reference intensities, Q10/Q50/Q90 picks
  segmentation.py  stardist_haug2 wrapper (lazy TF import, GPU memory growth, tiling)
  crops.py         crop placement, cutting, segmentation, caches (features, outlines, thumbnails)
  features.py      ~300 features per nucleus (numba kernels) — see "Features"
  contours.py      outline polygons (numba Moore tracing) for viewer and ROIs
  classifier.py    RandomForest (sklearn), leave-one-crop-out CV, save/load
  batch.py         per-image pipeline (resumable), objects CSV, ROIs, overlays, summaries
  quantify.py      tables, proportions, Excel workbook, plots
  stats.py         Mann-Whitney, Kruskal-Wallis, Dunn, Holm
  rois.py          Fiji ROI sets named/coloured by category (roifile, deflate zip)
  render.py        colour composites for thumbnails/overlays
  jobs.py          one background worker thread with progress/cancel
```

Data flow: `api.Session` methods are called by `app/server.py` (HTTP), `__main__.py` (CLI)
and the validation scripts. Long steps run as jobs (`jobs.JobManager`, one worker because
jobs share the GPU and project files); the frontend polls `/api/jobs/{id}`.

## Project folder (what is written where)

Input images are never modified. A project lives in
`<images folder>/NucleiQuant_projects/<name>/`:

| Path | Content |
|---|---|
| `project.json` | all settings and state; `images_dir` is stored *relative* (so folders can move and Docker mount points can differ) |
| `survey.json`, `survey.csv` | per-image survey (means in nuclei, reference intensities, segmentation range) |
| `training/crops/<crop>.tif` | crop images (ImageJ hyperstack, pixel size kept) |
| `training/labels/<crop>_labels.tif/.h5` | crop segmentations |
| `training/annotations.csv` | user labels: `crop_id,label,category` — the source of truth for training |
| `training/cache/` | per-crop features (`.pkl`), outlines (`.npz`), thumbnails — regenerable |
| `classifier/` | `model.joblib`, `classifier.json` (metrics, top features, hash), `training_set.csv.gz` |
| `results/labels/` | full-image segmentations + `_labels.json` (segmentation key: reused if unchanged) |
| `results/objects/<image>_objects.csv` | one row per nucleus: centroid, area, category, probabilities, mean per channel |
| `results/rois/`, `results/overlays/` | Fiji ROI sets, QC JPEGs |
| `results/summaries/<image>.json` | counts per category + classifier hash (resume/skip logic) |
| `results/<Diff_Day_Immuno>_counts.xlsx` | sheets: per_image, per_organoid, per_organoid_curated, proportions, statistics, classifier, settings |
| `results/plots/` | PNG + SVG |

App-wide state (recent projects, numba cache) goes to `$NQ_STATE_DIR` (default
`~/.nucleiquant`).

## Features (features.py)

Per nucleus, per channel `cN` unless noted. Superset of the ilastik set used in V1:

- `shape_*`: area, perimeter (skimage estimator), convex area, solidity, extent,
  eccentricity, axes, Feret max/min, circularity, roundness, Hu moments (log), inertia eigenvalues.
- `int_*`: mean, std, CV, skewness, kurtosis, min, max, sum, quantiles 5–95, IQR.
- `norm_*`: intensities relative to the image's survey references `(x - bg) / (nuc - bg)`,
  identical for a crop and its full image — this is what makes crops and full images comparable.
- `rad_*`: core vs rim mean and ratio, off-centring of the stain.
- `ring_*`: ilastik "in neighborhood": pixels at Euclidean distance < `ring_radius` (30)
  from the nucleus, nucleus excluded, neighbours included (as in ilastik's `make_bboxes`).
- `peri_*`: pixels < `perinuclear_radius` (4) outside every nucleus (cytoplasmic signal).
- `ctr_*`: log2 contrasts nucleus/ring, nucleus/perinuclear, perinuclear/ring.
- `xch_*`: covariance and correlation between channels (inside and ring), marker/nuclear ratios.
- `tex_*`: Haralick descriptors from a 16-level GLCM (4 directions summed).
- `lbp_*`: uniform LBP (P=8, R=1) histogram. `grad_*`: Sobel edge strength, difference-of-Gaussians spots.
- `ctx_*`: nearest-neighbour distance, neighbours within the ring radius.

Deliberately excluded: orientation (eigenvectors) and position (centroid, bbox) — they
encode where a nucleus is, not what it is. Metadata columns are listed in `META_COLUMNS`.

Validated (tests/test_features.py): rings equal a slow distance-transform reference;
means equal ilastik's exported values for nuclei ilastik and StarDist agree on; shape
equals scikit-image's regionprops.

## Invariants — do not break

- **numpy stays 1.26.4** (pinned in pyproject.toml): the NGC TensorFlow build breaks with numpy 2.
  Never add an unpinned dependency that upgrades numpy. Check with `uv pip install --dry-run`.
- **Segmentation normalisation**: percentiles 0.2–99.8 of the *whole image's* nuclear channel;
  crops use their full image's range (`survey.json: seg_lo/seg_hi`). Changing it changes
  every count; bump `segmentation.SEGMENTATION_VERSION` if you change segmentation output.
- **Features**: bump `features.FEATURE_VERSION` when features change; a classifier is only
  valid with the features it was trained on (the hash in `classifier.json` tracks this).
- **Built-in categories** have ids `dead` and `unstained` (`project.DEFAULT_CATEGORIES`);
  `Living = Total − Dead` everywhere. They can't be deleted.
- **All workflow logic lives in `api.py`** (and the modules it calls). The server, CLI and
  any future MCP server stay thin wrappers.
- **Frontend has no build step**: plain ES modules. Keep it that way (users and agents edit it directly).
- **User-facing text is plain language** (the audience is biologists); keep screens to one
  primary action. Code comments are short and descriptive.
- The images folder is read-only except for `NucleiQuant_projects/`.
- **`TF_ENABLE_ONEDNN_OPTS=0`** (set in `segmentation.py` and the Dockerfile): with oneDNN on,
  this TensorFlow build runs StarDist ~350x slower on CPU (173 s vs 0.5 s for 1024x1024).
  With it off, CPU-only segmentation of a 3156x3141 image takes 8 s and gives the same nuclei.
- Statistics use the organoid (or image when there is no organoid field) as the unit, never cells.

## How to extend (recipes)

**Other filename convention** — no code: Project screen › Edit pattern (template of field
names separated by `_`). For formats that aren't `_`-separated, add a regex path in
`metadata.pattern_from_template` and keep named groups `clone`, `organoid`, `slice` when they
exist (used for genotypes, per-organoid sums and statistics).

**More or fewer channels** — works for 1–N channels (features loop over channels; UI lists
them). Only the default channel names/colours (`project.CHANNEL_COLORS`) assume ≤ 6.

**Add a feature** — in `features.compute_features`, add columns named `<group>_c{c}_<name>`
(vectorise with `np.add.reduceat` over `starts`, or add a numba kernel). Bump
`FEATURE_VERSION`. Add a check in `tests/test_features.py`. Crops are re-measured when the
user rebuilds them; existing classifiers must be retrained.

**Another classifier** (e.g. gradient boosting) — change `classifier._forest`/`train`;
keep `predict_proba` semantics. Everything else (CV, UI, Excel) follows.

**Another segmentation model** (e.g. Cellpose, another StarDist model) — implement
`segment(nuclear, lo, hi) -> int32 labels` in `segmentation.py` (keep the lock and lazy
import), bump `SEGMENTATION_VERSION`. Add the package to pyproject.toml without breaking
the numpy pin (Cellpose needs PyTorch: that means a different base image).

**Another statistical test** — add it to `stats.compare_groups`; results flow into the
`statistics` sheet and the Results screen table.

**New export** — write it in `quantify.write_outputs` (tables are pandas DataFrames).

**MCP server (planned)** — wrap `api.Session` methods as tools: `create_project`,
`update_project`, `start_survey`, `survey_data`, `set_selection`, `start_crops`,
`set_label`, `start_training`, `classifier_info`, `validate_classifier`, `start_batch`,
`results`; poll jobs with `jobs.get`. Put it in `nucleiquant/mcp_server.py` using the
official Python MCP SDK; no workflow logic in it.

**V3 — per-marker (QuPath-style composite) classification (planned)** — one +/−
classifier per marker plus one Dead classifier, phenotype = combination. Suggested shape:
a project `mode` flag; categories become markers; `annotations.csv` gains a marker column;
`Classifier` becomes a dict of binary forests; `quantify` counts phenotype combinations.

## What V2 can't do (tell users; say what would need changing)

- 2D only: z-stacks must be projected first (Fiji) — 3D would need a 3D segmentation model.
- Nuclei only: no whole-cell segmentation; cytoplasmic markers are captured only through
  the ring/perinuclear features.
- TIFF input only (convert CZI/ND2/LIF with Fiji/bfconvert) — a reader could be added in `io.read_image`.
- Metadata only from file names + the clone → genotype table (no sample sheet import yet).
- One category per cell (double positives = explicit categories) until V3.
- The segmentation model is tuned on DAPI in human cortical organoids at 20× (~0.43 µm/px);
  other tissues/magnifications need checking, maybe retraining (`notebooks/00_training.ipynb`,
  not in the app). Features are in pixels: a classifier doesn't transfer across
  magnifications, staining panels or acquisition settings.
- Not bit-identical to ilastik (different forest implementation, extended features).
- No region annotation (e.g. excluding a necrotic core) and no spatial analysis.
- Single user, local only, no login. No whole-slide tiling (images are held in memory;
  the viewer downsamples images larger than ~2000 px for QC).
- Statistics are simple non-parametric tests; mixed models (clone within genotype) need R.
- Large batches take time: ~15 s per image on a 28-core workstation (CPU or GPU), more on laptops.
- Windows/macOS launchers are untested on real machines (written for Docker Desktop).

## Testing and validation

- `tests/`: unit tests (`./run_container.sh test`). Real-data tests skip when
  `img_test_pipeline/` is absent.
- `scripts/validation/compare_with_v1.py`: whole pipeline on `img_test_pipeline/` with labels
  sampled from V1's ilastik predictions; reports per-nucleus agreement and Cohen's κ with V1
  (2026-09-25: 93.6 % per-nucleus agreement, κ = 0.89, leave-one-crop-out accuracy 93.6 %,
  12 images in 158 s on an RTX 5070 Ti).
- `tests/e2e/run_walkthrough.sh`: real browser (Playwright container) clicks through all six
  steps and regenerates the documentation screenshots.

## Environment notes

- Base image `nvcr.io/nvidia/tensorflow:25.02-tf2-py3` (TF 2.17, CUDA 12.8; amd64 + arm64).
  Chosen because older TF builds hang on Blackwell GPUs; it reproduces the shipped model's
  label counts to within 3 nuclei out of 38,841.
- Env vars: `NQ_ROOTS` (folders the picker may open, `:`-separated), `NQ_PATH_MAP`
  (`/container/prefix=Host\prefix;…`, Windows display), `NQ_HOME` (shown as `~`),
  `NQ_STATE_DIR`, `NQ_MODEL_DIR`, `NUMBA_CACHE_DIR`.
- A pre-built image can be published to GHCR by pushing a `v*` tag
  (`.github/workflows/docker-image.yml`); the launchers try it before building locally.
