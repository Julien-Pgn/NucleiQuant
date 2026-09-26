"""ImageJ/Fiji ROI export, one polygon per nucleus, named and coloured by category."""

import zipfile

import numpy as np
import roifile

__all__ = ["write_rois"]


def _argb(hex_color):
    h = hex_color.lstrip("#")
    return bytes([255, int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)])


def write_rois(path, ids, offsets, ys, xs, names=None, colors=None):
    """Write a Fiji ROI set (.zip).

    names/colors: optional dict label -> ROI name / '#RRGGBB' stroke colour.
    Coordinates are pixel centres, i.e. +0.5 in ImageJ's convention.
    """
    rois = []
    for i, lab in enumerate(ids):
        py = ys[offsets[i]:offsets[i + 1]].astype(np.float32) + 0.5
        px = xs[offsets[i]:offsets[i + 1]].astype(np.float32) + 0.5
        if len(px) < 3:
            continue
        roi = roifile.ImagejRoi.frompoints(np.stack([px, py], axis=1))
        roi.roitype = roifile.ROI_TYPE.POLYGON
        lab = int(lab)
        roi.name = names.get(lab, f"{lab:06d}") if names else f"{lab:06d}"
        if colors and lab in colors:
            roi.stroke_color = _argb(colors[lab])
        rois.append(roi)
    if not path.endswith(".zip"):
        path += ".zip"
    # Deflate: ROI headers compress well (roifile itself stores them uncompressed)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        used = set()
        for roi in rois:
            name = roi.name
            while name in used:
                name += "_"
            used.add(name)
            zf.writestr(name + ".roi", roi.tobytes())
    return path
