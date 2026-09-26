"""Intensity survey: one quick measurement per image, no segmentation needed.

For each image, nuclei are approximated by an Otsu threshold of the nuclear
channel (on a 4x downsampled copy). Per channel we record the mean inside
that mask (used to rank images, like V1's mean nuclear intensity) and
reference values reused by the features, so that a crop and its full image
are described on the same scale.
"""

import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from skimage.filters import threshold_otsu

from . import io
from .segmentation import normalization_range

__all__ = ["image_refs", "survey_image", "pick_training_images", "ROLES"]

DOWNSAMPLE = 4
ROLES = (("Dim", 0.10), ("Typical", 0.50), ("Bright", 0.90))


def _downsample(img, f=DOWNSAMPLE):
    C, H, W = img.shape
    h, w = H // f * f, W // f * f
    return img[:, :h, :w].reshape(C, h // f, f, w // f, f).mean(axis=(2, 4))


def image_refs(img, nuclear_channel=0):
    """Nuclear mask statistics and per-channel reference intensities of one image."""
    img = np.asarray(img)
    ds = _downsample(img.astype(np.float32))
    nuc = ds[nuclear_channel]
    try:
        t = threshold_otsu(nuc)
    except ValueError:
        t = nuc.mean()
    mask = nuc > t
    if mask.sum() < 10 or (~mask).sum() < 10:
        mask = nuc > np.median(nuc)
    refs = []
    # Texture range from full-resolution pixels inside the mask (subsampled)
    full_mask = np.repeat(np.repeat(mask, DOWNSAMPLE, 0), DOWNSAMPLE, 1)
    h, w = full_mask.shape
    for c in range(ds.shape[0]):
        inside = ds[c][mask]
        outside = ds[c][~mask]
        vals = img[c, :h, :w][full_mask][::7]
        tex_lo, tex_hi = np.percentile(vals, (1, 99.8)) if vals.size else (0.0, 1.0)
        refs.append({
            "nuc": float(inside.mean()),
            "bg": float(np.median(outside)),
            "tex_lo": float(tex_lo),
            "tex_hi": float(max(tex_hi, tex_lo + 1)),
        })
    return {"refs": refs, "mask_fraction": float(mask.mean())}


def survey_image(path, nuclear_channel=0, norm_low=0.2, norm_high=99.8):
    """Survey one image file. Returns a JSON-able dict."""
    img = io.read_image(path)
    info = image_refs(img, nuclear_channel)
    seg_lo, seg_hi = normalization_range(img[nuclear_channel], norm_low, norm_high)
    return {
        "image": os.path.basename(path),
        "channels": int(img.shape[0]),
        "height": int(img.shape[1]),
        "width": int(img.shape[2]),
        "mean_in_nuclei": [r["nuc"] for r in info["refs"]],
        "refs": info["refs"],
        "tissue_fraction": info["mask_fraction"],
        "seg_lo": seg_lo,
        "seg_hi": seg_hi,
    }


def survey_images(paths, nuclear_channel=0, norm_low=0.2, norm_high=99.8, progress=None, workers=4):
    """Survey many images in parallel; progress(done, total, name) after each."""
    results = [None] * len(paths)

    def one(i):
        return i, survey_image(paths[i], nuclear_channel, norm_low, norm_high)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, res in ex.map(one, range(len(paths))):
            results[i] = res
            done += 1
            if progress:
                progress(done, len(paths), res["image"])
    return results


def pick_training_images(entries, channel, group_of):
    """Images closest to the 10th, 50th and 90th percentile of `channel`, per group.

    entries: survey results. group_of(image_name) -> group key (e.g. clone).
    Returns {image_name: role} where role is 'Dim · Q10' etc.
    """
    groups = {}
    for e in entries:
        groups.setdefault(group_of(e["image"]), []).append(e)
    picks = {}
    for _, items in sorted(groups.items()):
        values = np.array([e["mean_in_nuclei"][channel] for e in items])
        taken = set()
        for role, q in ROLES:
            target = np.quantile(values, q)
            order = np.argsort(np.abs(values - target), kind="stable")
            for i in order:
                name = items[i]["image"]
                if name not in taken:
                    taken.add(name)
                    picks[name] = f"{role} · Q{int(q * 100)}"
                    break
    return picks
