"""Segment, measure and classify every image of a project.

Resumable: an image whose summary was written with the same classifier and
segmentation settings is skipped. Segmentations are reused when only the
classifier changed.
"""

import json
import os
import time

import numpy as np
import pandas as pd
from PIL import Image

from . import contours, features, io, render, rois, segmentation
from .survey import survey_image

__all__ = ["process_image", "result_paths", "seg_key"]

OVERLAY_MAX = 1600


def stem(image_name):
    return os.path.splitext(image_name)[0]


def result_paths(project, image_name):
    st = stem(image_name)
    return {
        "labels": project.path("results", "labels", st + "_labels"),
        "seg_meta": project.path("results", "labels", st + "_labels.json"),
        "objects": project.path("results", "objects", st + "_objects.csv"),
        "features": project.path("results", "features", st + "_features.csv.gz"),
        "rois": project.path("results", "rois", st + "_rois.zip"),
        "overlay": project.path("results", "overlays", st + ".jpg"),
        "outlines": project.path("results", "cache", st + "_outlines.npz"),
        "pred": project.path("results", "cache", st + "_pred.npz"),
        "summary": project.path("results", "summaries", st + ".json"),
    }


def seg_key(project, survey_entry):
    s = project.settings
    return {
        "version": segmentation.SEGMENTATION_VERSION,
        "nuclear_channel": project.data["nuclear_channel"],
        "norm": [s["norm_low"], s["norm_high"]],
        "range": [round(survey_entry["seg_lo"], 3), round(survey_entry["seg_hi"], 3)],
    }


def is_done(project, image_name, classifier_hash):
    p = result_paths(project, image_name)["summary"]
    if not os.path.exists(p):
        return False
    try:
        with open(p) as f:
            s = json.load(f)
    except (OSError, ValueError):
        return False
    return s.get("classifier_hash") == classifier_hash


def process_image(project, image_name, clf, survey_entry=None, progress=None):
    """Full pipeline for one image; returns its summary dict."""
    def step(msg, frac):
        if progress:
            progress(msg, frac)

    s = project.settings
    nuc = project.data["nuclear_channel"]
    paths = result_paths(project, image_name)
    t0 = time.time()
    step("Reading", 0.0)
    img = io.read_image(project.image_path(image_name))
    info = io.image_info(project.image_path(image_name))
    if survey_entry is None:
        survey_entry = survey_image(project.image_path(image_name), nuc, s["norm_low"], s["norm_high"])
    key = seg_key(project, survey_entry)

    labels = None
    if os.path.exists(paths["seg_meta"]) and os.path.exists(paths["labels"] + ".tif"):
        with open(paths["seg_meta"]) as f:
            if json.load(f) == key:
                labels = io.read_labels(paths["labels"]).astype(np.int32)
    if labels is None:
        step("Segmenting nuclei", 0.05)
        labels = segmentation.segment(img[nuc], survey_entry["seg_lo"], survey_entry["seg_hi"])
        io.write_labels(paths["labels"], labels)
        with open(paths["seg_meta"], "w") as f:
            json.dump(key, f)

    step("Measuring nuclei", 0.45)
    df = features.compute_features(img, labels, survey_entry["refs"], s["ring_radius"],
                                   s["perinuclear_radius"], s["texture_levels"], nuclear_channel=nuc)
    step("Classifying", 0.75)
    cats, proba, pmax = clf.predict(df)
    names = {c["id"]: c["name"] for c in project.categories}
    colors = {c["id"]: c["color"] for c in project.categories}

    # Objects table (one row per nucleus)
    out = pd.DataFrame({
        "label": df["label"].to_numpy(),
        "centroid_x": df["centroid_x"].round(2).to_numpy(),
        "centroid_y": df["centroid_y"].round(2).to_numpy(),
        "area_px": df["shape_area"].astype(int).to_numpy() if len(df) else [],
        "touches_border": df["touches_border"].to_numpy(),
        "category": [names.get(c, c) for c in cats],
        "probability": np.round(pmax, 3),
    })
    for j, cid in enumerate(clf.categories):
        out[f"p_{names.get(cid, cid)}"] = np.round(proba[:, j], 3) if len(df) else []
    for c, ch in enumerate(project.data["channels"]):
        out[f"mean_{ch['name']}"] = df[f"int_c{c}_mean"].round(2).to_numpy() if len(df) else []
    out.to_csv(paths["objects"], index=False)
    if s.get("save_all_features"):
        df.to_csv(paths["features"], index=False, compression="gzip")

    step("Writing ROIs and overlay", 0.85)
    ids, off, ys, xs = contours.trace_outlines(labels)
    np.savez_compressed(paths["outlines"], ids=ids, offsets=off, ys=ys, xs=xs)
    cat_of = dict(zip(df["label"].to_numpy().tolist(), cats))
    cat_index = {c["id"]: i for i, c in enumerate(project.categories)}
    np.savez_compressed(paths["pred"], labels=df["label"].to_numpy(),
                        category=np.array([cat_index.get(c, -1) for c in cats], dtype=np.int16),
                        probability=pmax.astype(np.float32))
    rois.write_rois(
        paths["rois"], ids, off, ys, xs,
        names={int(l): f"{names.get(c, c)}_{int(l):06d}" for l, c in cat_of.items()},
        colors={int(l): colors.get(c, "#FFFFFF") for l, c in cat_of.items()},
    )
    C, H, W = img.shape
    f = max(1, int(np.ceil(max(H, W) / OVERLAY_MAX)))
    ch_colors = [ch["color"] for ch in project.data["channels"]]
    pil = Image.fromarray(render.composite(render.downsample_mean(img.astype(np.float32), f), ch_colors,
                                           render.display_ranges(survey_entry["refs"])))
    render.draw_outlines(pil, ids, off, ys, xs, lambda l: colors.get(cat_of.get(l)), scale=1.0 / f)
    pil.save(paths["overlay"], quality=88)

    counts = {c["id"]: 0 for c in project.categories}
    for c in cats:
        counts[c] = counts.get(c, 0) + 1
    summary = {
        "image": image_name,
        "counts": counts,
        "total": int(len(df)),
        "touching_border": int(df["touches_border"].sum()) if len(df) else 0,
        "classifier_hash": clf.info["hash"],
        "segmentation": key,
        "height": H, "width": W,
        "pixel_size": info["pixel_size"],
        "seconds": round(time.time() - t0, 1),
    }
    with open(paths["summary"], "w") as fh:
        json.dump(summary, fh, indent=1)
    step("Done", 1.0)
    return summary


def load_summaries(project, image_names):
    out = []
    for name in image_names:
        p = result_paths(project, name)["summary"]
        if os.path.exists(p):
            with open(p) as f:
                out.append(json.load(f))
    return out
