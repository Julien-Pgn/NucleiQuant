"""Training crops: placement, cropping, segmentation and per-crop caches."""

import os
import time

import numpy as np
from skimage.filters import threshold_otsu

from . import contours, features, io, render, segmentation
from .survey import survey_image

__all__ = ["auto_place", "build_crop", "crop_paths"]

PLACE_DOWNSAMPLE = 8


def auto_place(img, nuclear_channel=0, fraction=0.5):
    """Top-left corner (y, x) and size (h, w) of the crop window.

    The window goes where marker-positive tissue is densest: pixels inside
    the tissue (Otsu on the nuclear channel) that are in the top quarter of
    any other channel. This gives a mix of positive cells, negative cells
    and some dead core, instead of a crop full of dead cells.
    """
    C, H, W = img.shape
    h, w = max(1, int(H * fraction)), max(1, int(W * fraction))
    f = PLACE_DOWNSAMPLE
    ds = render.downsample_mean(img.astype(np.float32), f)
    nuc = ds[nuclear_channel]
    try:
        tissue = nuc > threshold_otsu(nuc)
    except ValueError:
        tissue = nuc > nuc.mean()
    score = np.zeros_like(tissue)
    others = [c for c in range(C) if c != nuclear_channel]
    for c in others:
        if tissue.any():
            score |= tissue & (ds[c] > np.percentile(ds[c][tissue], 75))
    if not others or not score.any():
        score = tissue
    ch, cw = max(1, h // f), max(1, w // f)
    ii = np.pad(score.astype(np.float64).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    sums = ii[ch:, cw:] - ii[:-ch, cw:] - ii[ch:, :-cw] + ii[:-ch, :-cw]
    y, x = np.unravel_index(np.argmax(sums), sums.shape)
    y, x = min(int(y) * f, H - h), min(int(x) * f, W - w)
    return {"y": max(0, y), "x": max(0, x), "h": h, "w": w}


def crop_paths(project, crop_id):
    base = project.path("training", "crops", crop_id)
    return {
        "image": base + ".tif",
        "labels": project.path("training", "labels", crop_id + "_labels"),
        "features": project.path("training", "cache", crop_id + "_features.pkl"),
        "outlines": project.path("training", "cache", crop_id + "_outlines.npz"),
        "thumb": project.path("training", "cache", crop_id + "_thumb.jpg"),
        "film": project.path("training", "cache", crop_id + "_film.jpg"),
    }


def build_crop(project, crop, survey_entry=None, progress=None):
    """Cut, segment and describe one crop. Updates and returns the crop dict."""
    def step(msg, frac):
        if progress:
            progress(msg, frac)

    s = project.settings
    nuc = project.data["nuclear_channel"]
    image_path = project.image_path(crop["image"])
    step("Reading image", 0.02)
    img = io.read_image(image_path)
    info = io.image_info(image_path)
    if survey_entry is None:
        survey_entry = survey_image(image_path, nuc, s["norm_low"], s["norm_high"])
    C, H, W = img.shape
    if crop.get("y") is None:
        crop.update(auto_place(img, nuc, s["crop_fraction"]))
    y, x, h, w = crop["y"], crop["x"], crop["h"], crop["w"]
    y = int(np.clip(y, 0, H - h))
    x = int(np.clip(x, 0, W - w))
    crop["y"], crop["x"] = y, x
    region = img[:, y:y + h, x:x + w]
    paths = crop_paths(project, crop["id"])

    colors = [ch["color"] for ch in project.data["channels"]]
    ranges = render.display_ranges(survey_entry["refs"])
    render.thumbnail(img, colors, ranges, 720).save(paths["thumb"], quality=88)
    render.thumbnail(region, colors, ranges, 256).save(paths["film"], quality=85)
    io.write_image(paths["image"], region, info["pixel_size"])

    step("Segmenting nuclei", 0.1)
    labels = segmentation.segment(region[nuc], survey_entry["seg_lo"], survey_entry["seg_hi"])
    io.write_labels(paths["labels"], labels)

    step("Measuring nuclei", 0.6)
    df = features.compute_features(
        region, labels, survey_entry["refs"], s["ring_radius"], s["perinuclear_radius"],
        s["texture_levels"], nuclear_channel=nuc,
    )
    df.to_pickle(paths["features"])

    step("Tracing outlines", 0.9)
    ids, off, ys, xs = contours.trace_outlines(labels)
    np.savez_compressed(paths["outlines"], ids=ids, offsets=off, ys=ys, xs=xs)

    crop.update({
        "status": "ready",
        "n_nuclei": int(len(df)),
        "n_edge": int(df["touches_border"].sum()) if len(df) else 0,
        "pixel_size": info["pixel_size"],
        "image_height": H,
        "image_width": W,
        "feature_version": features.FEATURE_VERSION,
        "built": time.time(),
    })
    step("Done", 1.0)
    return crop


def remove_crop_files(project, crop_id):
    paths = crop_paths(project, crop_id)
    for key, p in paths.items():
        for candidate in ([p + ".tif", p + ".h5"] if key == "labels" else [p]):
            if os.path.exists(candidate):
                os.remove(candidate)
