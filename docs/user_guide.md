# NucleiQuant user guide

NucleiQuant counts cell types in fluorescence images in seven steps (the Test step is optional). You go through them
once per experiment; everything is saved as you go, so you can quit and come back at any
step.

- [Before you start](#before-you-start)
- [1. Project](#1-project)
- [2. Survey](#2-survey)
- [3. Crops](#3-crops)
- [4. Label](#4-label)
- [5. Preview](#5-preview)
- [6. Test](#6-test)
- [7. Results](#7-results)
- [Reusing a classifier](#reusing-a-classifier)
- [Settings](#settings)
- [Questions](#questions)

## Before you start

**Images.** One TIFF file per image, with all channels in the file, 2D (project z-stacks
first). Put all images of the experiment in one folder. They should come from the same
staining and the same microscope settings: a classifier learns intensities, so it is only
valid for one imaging setup.

**File names carry the experiment details**, parts separated by `_`. The default pattern
is:

```
clone_diff_day_immuno_objective_imaging_organoid_slice
Pa_dQ_J70_SNd2T_20Xa_g1dt08_OG1_s1.tif
```

You can describe any other pattern (see [Project](#1-project)). Three names matter:
`clone` (to group clones by genotype), `organoid` and `slice` (to add up the slices of each
organoid). Without `organoid`, each image counts as one sample.

**Starting the app**: double-click `Start NucleiQuant.bat` (Windows),
`Start NucleiQuant.command` (Mac) or `start-nucleiquant.sh` (Linux). Your browser opens
on the home screen.

![Home screen](images/01-home.png)

Click **New project**, choose your images folder and give the project a name. You can make
several projects on the same images (e.g. one per staining panel).

![Choosing the images folder](images/01b-folder-picker.png)

## 1. Project

![Project screen](images/02-project.png)

- **Images**: the folder, the number of images and channels, and the pixel size read from
  the files.
- **File names**: an example file name cut into its parts. If some names don't match, click
  **Edit pattern** and type the names of the parts in order, separated by `_`
  (e.g. `clone_day_organoid_slice`).
- **Channels**: name each channel (e.g. DAPI, SATB2, TBR1, CTIP2) and choose its display
  colour by clicking the square. Tick **Nuclei** on the nuclear stain: nuclei are found on
  that channel.
- **Genotypes**: type the genotype of each clone (e.g. WT/WT, KO/KO). Groups in plots and
  statistics use these. You can change them later and recalculate the results.

Click **Continue**.

## 2. Survey

![Survey screen](images/03-survey.png)

Staining brightness varies between organoids and slices. A classifier trained only on
bright images makes mistakes on dim ones, so NucleiQuant measures every image (mean
intensity inside the nuclei, estimated without segmenting) and picks three training images
per clone: the ones closest to the **10th (dim), 50th (typical) and 90th (bright)
percentile** of the chosen channel.

- Choose the channel of your main marker with the buttons above the plot.
- Each dot is an image; yellow rings are the images picked for training. Click a dot or a
  row to add or remove an image. **Reset to automatic** restores the picks.
- More training images mean more variety to learn from, but more to label.

Click **Create crops**.

## 3. Crops

![Crops screen](images/04-crops.png)

A region of each training image (a quarter of the image by default) is cut and its nuclei
are found with the stardist_haug2 model. The region starts where marker-positive cells are
densest, so each crop contains positive cells, negative cells and some dead cells.

- **Drag the yellow frame** to move a crop; it is segmented again (its labels, if any, are
  removed).
- Nuclei touching the edge of a crop are cut in two: you'll see them greyed out and can't
  label them. They are counted normally in the full images.

Click **Start labeling** when all crops are ready.

## 4. Label

![Label screen](images/05-label.png)

This is where you teach NucleiQuant your cell types.

**Categories.** *Dead* and *Unstained* are always there. Click **Add** to create your own
categories (e.g. `PAX6+`, `BRN2+`). A cell gets exactly one category, so if cells can
carry two markers and you want to count them, make a category for them (e.g.
`PAX6+BRN2+`). Double-click a name to rename it.

**Colours.** Click a category's colour square (or, when adding one, the square next to its
name) to choose its colour. The first row offers **your channel colours by name**, so
PAX6+ cells can be outlined in the same green as the PAX6 channel; then other colours and
any custom colour. Colours are used everywhere: outlines, plots, Fiji ROIs. Tip: a colour
identical to its channel can be harder to see on bright cells — hold **H** to compare.

![Choosing a colour](images/05c-colour-picker.png)

**Labeling.** Select a category (click it, or press its number key **1–9**), then click
nuclei in the image.

| Action | How |
|---|---|
| Label a nucleus | click it |
| Remove a label | right-click it, or click it again with the same category, or press **E** (erase mode) and click |
| Zoom | mouse wheel, or the – / + buttons; **F** fits the image |
| Move around | drag the image |
| See the image without outlines | hold **H** |
| Next / previous crop | **]** / **[**, or click in the strip below the image |

**Channels.** The eye shows or hides a channel; the slider sets its contrast (like ImageJ's
Brightness & Contrast). **Auto contrast** resets. These settings only change the display,
never the measurements.

**How many labels?** The recommendation is **10 of each category in every crop** — that is
30 per category per clone (3 crops per clone). The counter next to each category shows *this
crop's* count (e.g. `7 / 10`, green tick at 10) and, below, the total in all crops; the strip
of crops shows each crop's progress (`40 / 50`). Labeling the same amount in every crop keeps
dim, typical and bright images equally represented, which is what makes the classifier
robust to staining variation.

It is a recommendation, not a rule: a crop may simply not contain 10 cells of a category.
Label what you find and move on. When you click **Preview classification** before every
crop is complete, NucleiQuant lists what is missing where, and you can **Keep labeling** or
**Preview anyway**. The only requirement is that at least two categories have labels. A
category with no labels at all (e.g. no unstained cells in your staining) is never predicted.

Label cells you are sure about; skip the ones you can't decide on; include a few hard cases
(dim positives, bright negatives).

![Missing labels](images/05b-unused-warning.png)

Click **Preview classification**.

## 5. Preview

![Preview screen](images/06-preview.png)

The classifier (a random forest, the same method as ilastik) is trained on your labels and
every nucleus of every crop is outlined in the colour of its predicted category.

- **The percentage** is how often the classifier is right on a crop it did *not* train on
  (it is trained on the other crops, tested on this one, for each crop in turn). Above
  90 % is typical for clear stainings.
- **Where it gets confused** shows which categories are mixed up (rows: your label;
  columns: the prediction) and which measurements the classifier relies on most.

![Confusion matrix](images/06b-preview-confusion.png)

- **Uncertain cells only** (key **U**) shows only nuclei the classifier isn't sure about
  (probability below 60 %). These are the best ones to label next.
- To **correct** a mistake: select the right category (keys 1–9) and click the nucleus. Then
  click **Retrain** (key **R**); the colours update.

When the preview looks right, click **Classify all images**.

## 6. Test

*Optional, but this is the accuracy to report in a paper.*

The accuracy on the Preview screen is measured on your *training* crops (each crop in turn is
left out). Reviewers usually ask for more: an accuracy measured on **images the classifier
never saw**, labeled **without seeing its answers**. The Test step does exactly that.

1. **Create test crops.** NucleiQuant draws 2 images per clone at random among the images
   not used for training (random, so that the test represents the whole experiment), and
   cuts a smaller crop from each (35 % of the image side).
2. **Label them blind.** The screen looks like the Label screen, but the classifier's
   predictions are never shown. Label about **5 cells of each category in each test crop**.
   Don't hunt for easy or hard cells: label what you are sure of, as you would anywhere.
   Test labels are stored apart and are **never used for training**.
3. **Evaluate accuracy.** The report opens.

![Test report](images/11-test-report.png)

**Reading the report**

- **Balanced accuracy** — the mean of the per-category accuracies (recall). Because test
  cells are picked per category (5 of each), this is the fairest single number.
- **Accuracy on test cells** and **Cohen's κ** (agreement corrected for chance: above 0.8 is
  usually called excellent).
- **95 % confidence intervals** for all of them — the range the true value probably lies in.
  They shrink with more test cells: with 100 test cells and a true accuracy of 90 %, about
  ±6 %; with 20 cells of one category, that category's accuracy is known to about ±15 %.
  Cells from the same image are somewhat alike, so the real uncertainty is a little larger.
- **Per category**: test cells, recall (how many cells of this category were found) and
  precision (how many cells called this category really are), with intervals.
- **Per test image** and the **confusion matrix** (rows: your label, columns: the classifier).
- **Every evaluation**: each evaluation is logged with its date and classifier, so that
  evaluating again after changing the training stays visible.
- **Methods text**: a paragraph describing the test and its result, to copy and adapt.

**Good practice.** Finish your training labels first, then label the test crops and
evaluate once. If the test shows a weak category, you can label more *training* cells and
retrain — then evaluate again and report both (the history keeps them). Never copy test
cells into training.

## 7. Results

![Running](images/07-running.png)

Every image is now segmented, measured and classified — about 15 seconds per image on a
recent workstation, up to a minute on a laptop. You can **Stop** at any time; images already done are kept,
and starting again continues where it stopped. If you retrain the classifier later,
classifying again reuses the segmentations and is faster.

![Results screen](images/08-results.png)

- **Tiles**: number of images, nuclei, living cells (all except *Dead*) and organoids kept
  for statistics (at least 4 slices by default, as in Pigeon et al.).
- **Proportions**: a vertical stacked bar per organoid (or the mean per genotype, with the
  spread in the tooltip). Greyed bars are organoids excluded for having too few slices.
  Hover a bar for the percentage and the number of cells.
- **100 % =**: choose which categories make up 100 %. Tick or untick categories, or use the
  quick choices: **All nuclei**, **Living cells** (all but Dead) and **Stained cells** (all but
  Dead and Unstained — e.g. PAX6+ as a share of all marker-positive cells). The bars and the
  statistics update immediately. **Save in Excel** adds your combination to the Excel file
  and the plots; **SVG** downloads the chart on a white background for figures.
- **Statistics**: for the chosen 100 %; see below.
- **Per image**: counts per image. **View** opens the image with every nucleus outlined in
  its category colour, to check the result anywhere.

![Proportions of stained cells](images/08b-results-stained.png)

![Checking an image](images/09-image-view.png)

**Download Excel** saves the workbook. **Copy folder path** gives you the results folder.

### The Excel file

| Sheet | Content |
|---|---|
| `per_image` | one row per image: the parts of its file name, genotype, number of nuclei per category, Total, Living (= Total − Dead) |
| `per_organoid` | the slices of each organoid added up, with the number of slices |
| `per_organoid_curated` | only organoids with at least the minimum number of slices |
| `proportions` | per kept organoid, for each 100 % (all nuclei, living cells, stained cells, and each one you saved): the number of cells in it and each category as % of it |
| `statistics` | group comparisons for each 100 % (column *Measure*, e.g. "% of stained cells") |
| `classifier` | labels per category, accuracy on unseen crops, recall per category, most important measurements |
| `test_set` | the independent test (if done): accuracies with 95 % CI, per category, per test image, confusion matrix, every evaluation, methods text |
| `settings` | everything needed to reproduce the analysis (channels, pattern, segmentation settings, version) |

### The results folder

| Folder | Content |
|---|---|
| `objects/` | one CSV per image, one row per nucleus: position, area, category, probability of each category, mean intensity per channel |
| `rois/` | Fiji ROI sets: open the image in Fiji, then the zip in the ROI Manager. Each nucleus is named and coloured by its category |
| `labels/` | nucleus label images (`.tif` and `.h5`), as in V1 |
| `overlays/` | quick-look pictures with coloured outlines |
| `plots/` | proportion bar plots (and per-genotype box plots) for each 100 %, in PNG and SVG (editable in Illustrator/Inkscape) |

### Statistics

Cells from the same organoid are not independent, so comparisons use **one value per
organoid** (its proportion), never individual cells.

- Two groups (e.g. WT vs KO): **Mann-Whitney U** test.
- Three or more: **Kruskal-Wallis**, then **Dunn's** test for each pair.
- p-values are **Holm-corrected** for the number of categories tested (and of pairs),
  separately for each 100 %. If you report several 100 % for the same question, remember
  they are not corrected against each other.
- Groups are genotypes (or clones, see Settings). With fewer than 3 organoids in a group,
  the test can't reach significance; NucleiQuant warns you.

These tests make no assumption about the distribution. They don't model that clones of the
same genotype are related; for that (mixed models), use the counts in the Excel file in R.

## Reusing a classifier

For a new experiment with the **same staining and imaging settings**, you don't need to
label again: on the home screen, click **Apply a saved classifier to new images**, choose
the new images folder and the project whose classifier to reuse. You go straight to
Results. Check a few images with **View**: if staining or imaging changed, train a new
classifier.

## Settings

**Project › Advanced settings**:

| Setting | Default | Meaning |
|---|---|---|
| Labels per category per crop | 10 | recommended labels of each category in each crop (not enforced) |
| Min. slices per organoid | 4 | organoids with fewer slices are left out of proportions and statistics |
| Test images per clone | 2 | random images per clone, never used for training, for the test set |
| Test crop size | 35 % | test crop side as a percentage of the image side |
| Test labels per category per crop | 5 | recommended test labels of each category in each test crop |
| Compare groups by | Genotype | or Clone |
| Crop size | 50 % | crop side as a percentage of the image side |
| Neighbourhood ring | 30 px | ring around each nucleus measured for context (as ilastik's "neighborhood") |
| Perinuclear ring | 4 px | background just around the nucleus (cytoplasmic signal) |
| Trees in the forest | 100 | as in ilastik |
| "Uncertain" below | 0.6 | probability below which a nucleus counts as uncertain |
| Segmentation percentiles | 0.2 – 99.8 | brightness range used to normalise the nuclear channel before segmentation |
| Save every feature | off | also save all ~300 measurements of every nucleus (large files) |

Changing segmentation or measurement settings after the crops were made re-creates the
crops and removes their labels.

## Questions

**How long does it take?** Setting up and labeling: 30–60 minutes. Classifying: 15 s to
1 min per image depending on the computer (an NVIDIA GPU helps but isn't needed).

**What does the classifier look at?** About 300 measurements per nucleus: size and shape;
intensity statistics in each channel (mean, percentiles, spread…); intensity relative to
the whole image (so dim and bright images are comparable); the core versus rim of the
nucleus; a 30-pixel ring around it and the thin perinuclear region (for cytoplasmic
signal); correlations between channels; texture; and how crowded the neighbourhood is. It
does *not* use where the nucleus is in the image.

**Can it do cytoplasmic or membrane markers?** Partly: the rings around each nucleus capture
nearby signal, which often works. There is no whole-cell segmentation.

**My images are not organoids.** Any tissue works if the nuclei look like the training data
(dense tissue, DAPI, 20×). Always check the segmentation on the Crops and Label screens.

**Where are my projects?** In `NucleiQuant_projects` inside your images folder. The home
screen lists recent projects; **Open project** opens any of them.

**NucleiQuant runs on a lab workstation and I work from my laptop.** Add one line to the
workstation's entry in `~/.ssh/config` on your laptop — `LocalForward 127.0.0.1:8765 127.0.0.1:8765` —
and <http://localhost:8765> works on the laptop whenever NucleiQuant runs on the workstation,
with VS Code or plain `ssh`. Details and other options: Readme › *From another computer (SSH)*.
The images stay on the workstation.

**Nothing happens / the page says it can't reach NucleiQuant.** The app was stopped. Start it
again with the launcher; your project reopens where you left it.
