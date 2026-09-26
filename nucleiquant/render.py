"""Colour composites for thumbnails and QC overlays."""

import numpy as np
from PIL import Image, ImageDraw

__all__ = ["hex_to_rgb", "display_ranges", "composite", "thumbnail", "draw_outlines", "downsample_mean"]


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def display_ranges(refs):
    """Default contrast per channel from survey references: background to bright nuclei."""
    return [(r["bg"], max(r["tex_hi"], r["bg"] + 1)) for r in refs]


def downsample_mean(img, f):
    """(C, Y, X) block mean by an integer factor."""
    if f <= 1:
        return img
    C, H, W = img.shape
    h, w = H // f * f, W // f * f
    return img[:, :h, :w].reshape(C, h // f, f, w // f, f).mean(axis=(2, 4))


def composite(img, colors, ranges, visible=None):
    """Additive colour composite of a (C, Y, X) image -> (Y, X, 3) uint8."""
    C = img.shape[0]
    out = np.zeros(img.shape[1:] + (3,), np.float32)
    for c in range(C):
        if visible is not None and not visible[c]:
            continue
        lo, hi = ranges[c]
        v = np.clip((img[c].astype(np.float32) - lo) / max(hi - lo, 1e-6), 0, 1)
        out += v[..., None] * (np.array(hex_to_rgb(colors[c]), np.float32) / 255.0)
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)


def thumbnail(img, colors, ranges, max_size=720, visible=None):
    """PIL thumbnail of a (C, Y, X) image, longest side <= max_size."""
    f = max(1, int(np.ceil(max(img.shape[1:]) / max_size)))
    small = downsample_mean(img.astype(np.float32), f)
    return Image.fromarray(composite(small, colors, ranges, visible))


def draw_outlines(pil_img, ids, offsets, ys, xs, color_of, scale=1.0, width=1):
    """Draw outline polygons (full-resolution coordinates) onto a PIL image."""
    draw = ImageDraw.Draw(pil_img)
    for i, lab in enumerate(ids):
        col = color_of(int(lab))
        if col is None:
            continue
        py = ys[offsets[i]:offsets[i + 1]]
        px = xs[offsets[i]:offsets[i + 1]]
        if len(px) < 2:
            continue
        pts = [(float(x) * scale, float(y) * scale) for x, y in zip(px, py)]
        pts.append(pts[0])
        draw.line(pts, fill=hex_to_rgb(col), width=width)
    return pil_img
