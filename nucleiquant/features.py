"""Per-nucleus features for the random-forest classifier.

Superset of the ilastik object features used in V1 (Standard Object
Features + convex hull, "in neighborhood" = 30 px ring), plus texture,
radial, cross-channel, image-normalised and context features.
Orientation and position in the image are deliberately not features: they
say where a nucleus is, not what it is.

Feature groups (C = number of channels, names use channel index cN):
    shape_*   geometry of the nucleus
    int_*     intensity statistics inside the nucleus, per channel
    norm_*    intensities relative to the whole image (survey), per channel
    rad_*     core vs rim of the nucleus, stain off-centring, per channel
    ring_*    ilastik neighbourhood: pixels < ring_radius from the nucleus
              (nucleus excluded, neighbouring nuclei included)
    peri_*    perinuclear background: pixels < perinuclear_radius, outside
              every nucleus (cytoplasmic signal)
    ctr_*     contrast nucleus / surroundings, per channel
    xch_*     between-channel covariance, correlation and ratios
    tex_*     Haralick (GLCM) texture, per channel
    lbp_*     local binary pattern histogram, per channel
    grad_*    edge strength and spot-like (difference of Gaussians) signal
    ctx_*     local nucleus density
"""

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
from numba import njit, prange
from scipy import ndimage
from scipy.spatial import cKDTree
from skimage.feature import local_binary_pattern

__all__ = ["compute_features", "META_COLUMNS", "feature_columns", "FEATURE_VERSION"]

# Bump when features change (invalidates cached feature files)
FEATURE_VERSION = 1

META_COLUMNS = ["label", "centroid_y", "centroid_x", "bbox_y0", "bbox_x0", "bbox_y1", "bbox_x1", "touches_border"]

QUANTILES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
LBP_POINTS = 8
LBP_BINS = LBP_POINTS + 2


def feature_columns(df):
    """Columns of a features table that are used for classification."""
    return [c for c in df.columns if c not in META_COLUMNS]


# ---- numba kernels -----------------------------------------------------------

@njit(parallel=True, cache=True)
def _rings(labels, img, ids, bbox, bstart, bcount, bys, bxs, R, r):
    """Statistics of the ring (< R) and perinuclear background (< r) around each nucleus.

    Distances are to the nearest pixel of the nucleus (its boundary pixels),
    exactly like ilastik's distance-transform neighbourhood.
    """
    n = ids.shape[0]
    C, H, W = img.shape
    P = C * (C - 1) // 2
    ring_n = np.zeros(n)
    ring_s = np.zeros((n, C, 4))
    ring_min = np.full((n, C), np.inf)
    ring_max = np.full((n, C), -np.inf)
    ring_xy = np.zeros((n, P))
    peri_n = np.zeros(n)
    peri_s = np.zeros((n, C, 2))
    peri_max = np.full((n, C), -np.inf)
    R2 = R * R
    r2 = r * r
    for i in prange(n):
        lab = ids[i]
        y0 = bbox[i, 0]
        x0 = bbox[i, 1]
        y1 = bbox[i, 2]  # inclusive
        x1 = bbox[i, 3]
        ya = max(0, y0 - R + 1)
        yb = min(H - 1, y1 + R - 1)
        xa = max(0, x0 - R + 1)
        xb = min(W - 1, x1 + R - 1)
        bs = bstart[i]
        bc = bcount[i]
        for y in range(ya, yb + 1):
            dyb = 0
            if y < y0:
                dyb = y0 - y
            elif y > y1:
                dyb = y - y1
            for x in range(xa, xb + 1):
                lx = labels[y, x]
                if lx == lab:
                    continue
                dxb = 0
                if x < x0:
                    dxb = x0 - x
                elif x > x1:
                    dxb = x - x1
                if dyb * dyb + dxb * dxb >= R2:
                    continue
                dmin = R2
                for k in range(bs, bs + bc):
                    dy = y - bys[k]
                    dx = x - bxs[k]
                    d = dy * dy + dx * dx
                    if d < dmin:
                        dmin = d
                        if d < r2:
                            break
                if dmin >= R2:
                    continue
                ring_n[i] += 1.0
                p = 0
                for c in range(C):
                    v = img[c, y, x]
                    ring_s[i, c, 0] += v
                    ring_s[i, c, 1] += v * v
                    ring_s[i, c, 2] += v * v * v
                    ring_s[i, c, 3] += v * v * v * v
                    if v < ring_min[i, c]:
                        ring_min[i, c] = v
                    if v > ring_max[i, c]:
                        ring_max[i, c] = v
                    for c2 in range(c + 1, C):
                        ring_xy[i, p] += v * img[c2, y, x]
                        p += 1
                if dmin < r2 and lx == 0:
                    peri_n[i] += 1.0
                    for c in range(C):
                        v = img[c, y, x]
                        peri_s[i, c, 0] += v
                        peri_s[i, c, 1] += v * v
                        if v > peri_max[i, c]:
                            peri_max[i, c] = v
    return ring_n, ring_s, ring_min, ring_max, ring_xy, peri_n, peri_s, peri_max


@njit(cache=True, nogil=True)
def _glcm(q, labels, lut, n, L):
    """Symmetric grey-level co-occurrence counts per nucleus (4 directions summed)."""
    H, W = q.shape
    out = np.zeros((n, L, L), dtype=np.float32)
    for y in range(H):
        for x in range(W):
            lab = labels[y, x]
            if lab == 0:
                continue
            i = lut[lab]
            a = q[y, x]
            # right, down-right, down, down-left
            if x + 1 < W and labels[y, x + 1] == lab:
                b = q[y, x + 1]
                out[i, a, b] += 1
                out[i, b, a] += 1
            if y + 1 < H:
                if x + 1 < W and labels[y + 1, x + 1] == lab:
                    b = q[y + 1, x + 1]
                    out[i, a, b] += 1
                    out[i, b, a] += 1
                if labels[y + 1, x] == lab:
                    b = q[y + 1, x]
                    out[i, a, b] += 1
                    out[i, b, a] += 1
                if x > 0 and labels[y + 1, x - 1] == lab:
                    b = q[y + 1, x - 1]
                    out[i, a, b] += 1
                    out[i, b, a] += 1
    return out


# skimage.measure.perimeter weights (4-connectivity), indexed by the 3x3 code
_PERIM_W = np.zeros(50)
_PERIM_W[[5, 7, 15, 17, 25, 27]] = 1
_PERIM_W[[21, 33]] = np.sqrt(2)
_PERIM_W[[13, 23]] = (1 + np.sqrt(2)) / 2


@njit(cache=True)
def _perimeter(labels, boundary, lut, n, weights):
    """Per-object perimeter, same estimator as skimage.measure.perimeter."""
    H, W = labels.shape
    out = np.zeros(n)
    kern = np.array([[10, 2, 10], [2, 1, 2], [10, 2, 10]])
    for y in range(H):
        for x in range(W):
            if not boundary[y, x]:
                continue
            lab = labels[y, x]
            code = 0
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    yy = y + dy
                    xx = x + dx
                    if 0 <= yy < H and 0 <= xx < W and boundary[yy, xx] and labels[yy, xx] == lab:
                        code += kern[dy + 1, dx + 1]
            if code < 50:
                out[lut[lab]] += weights[code]
    return out


@njit(parallel=True, cache=True)
def _hull(bstart, bcount, bys, bxs):
    """Convex hull area and max/min Feret diameters from each nucleus' boundary pixel corners."""
    n = bstart.shape[0]
    area = np.zeros(n)
    fmax = np.zeros(n)
    fmin = np.zeros(n)
    for i in prange(n):
        m = bcount[i]
        if m == 0:
            continue
        py = np.empty(4 * m)
        px = np.empty(4 * m)
        for k in range(m):
            y = bys[bstart[i] + k]
            x = bxs[bstart[i] + k]
            py[4 * k] = y - 0.5
            px[4 * k] = x - 0.5
            py[4 * k + 1] = y - 0.5
            px[4 * k + 1] = x + 0.5
            py[4 * k + 2] = y + 0.5
            px[4 * k + 2] = x - 0.5
            py[4 * k + 3] = y + 0.5
            px[4 * k + 3] = x + 0.5
        order = np.argsort(px * 1e6 + py)
        sx = px[order]
        sy = py[order]
        npts = sx.shape[0]
        hx = np.empty(2 * npts + 1)
        hy = np.empty(2 * npts + 1)
        h = 0
        for k in range(npts):  # lower hull
            while h >= 2 and (hx[h - 1] - hx[h - 2]) * (sy[k] - hy[h - 2]) - (hy[h - 1] - hy[h - 2]) * (sx[k] - hx[h - 2]) <= 0:
                h -= 1
            hx[h] = sx[k]
            hy[h] = sy[k]
            h += 1
        lower = h + 1
        for k in range(npts - 2, -1, -1):  # upper hull
            while h >= lower and (hx[h - 1] - hx[h - 2]) * (sy[k] - hy[h - 2]) - (hy[h - 1] - hy[h - 2]) * (sx[k] - hx[h - 2]) <= 0:
                h -= 1
            hx[h] = sx[k]
            hy[h] = sy[k]
            h += 1
        h -= 1  # last point repeats the first
        a = 0.0
        for k in range(h):
            k2 = (k + 1) % h
            a += hx[k] * hy[k2] - hx[k2] * hy[k]
        area[i] = abs(a) / 2
        best = 0.0
        for k in range(h):
            for k2 in range(k + 1, h):
                d = (hx[k] - hx[k2]) ** 2 + (hy[k] - hy[k2]) ** 2
                if d > best:
                    best = d
        fmax[i] = np.sqrt(best)
        width = 1e18
        for k in range(h):  # min caliper width: over hull edges, farthest vertex
            k2 = (k + 1) % h
            ex = hx[k2] - hx[k]
            ey = hy[k2] - hy[k]
            el = np.sqrt(ex * ex + ey * ey)
            if el == 0:
                continue
            far = 0.0
            for j in range(h):
                d = abs(ex * (hy[j] - hy[k]) - ey * (hx[j] - hx[k])) / el
                if d > far:
                    far = d
            if far < width:
                width = far
        fmin[i] = width if width < 1e18 else 0.0
    return area, fmax, fmin


# ---- helpers -------------------------------------------------------------------

def _haralick(glcm):
    """Haralick descriptors from per-object co-occurrence counts (n, L, L)."""
    n, L, _ = glcm.shape
    tot = glcm.sum(axis=(1, 2))
    tot[tot == 0] = 1
    P = glcm / tot[:, None, None]
    i = np.arange(L, dtype=np.float32)[:, None]
    j = np.arange(L, dtype=np.float32)[None, :]
    diff = i - j
    mu = (P * i).sum(axis=(1, 2))
    var = (P * (i - mu[:, None, None]) ** 2).sum(axis=(1, 2))
    cov = (P * (i - mu[:, None, None]) * (j - mu[:, None, None])).sum(axis=(1, 2))
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = np.where(var > 1e-12, cov / var, 0.0)
        logP = np.where(P > 0, np.log2(np.where(P > 0, P, 1)), 0.0)
    # Sum and difference distributions (for sum/difference entropy)
    psum = np.zeros((n, 2 * L - 1), dtype=np.float32)
    pdiff = np.zeros((n, L), dtype=np.float32)
    for a in range(L):
        for b in range(L):
            psum[:, a + b] += P[:, a, b]
            pdiff[:, abs(a - b)] += P[:, a, b]
    with np.errstate(divide="ignore", invalid="ignore"):
        sum_ent = -np.where(psum > 0, psum * np.log2(np.where(psum > 0, psum, 1)), 0).sum(axis=1)
        diff_ent = -np.where(pdiff > 0, pdiff * np.log2(np.where(pdiff > 0, pdiff, 1)), 0).sum(axis=1)
    k = np.arange(2 * L - 1, dtype=np.float32)
    return {
        "contrast": (P * diff ** 2).sum(axis=(1, 2)),
        "dissimilarity": (P * np.abs(diff)).sum(axis=(1, 2)),
        "homogeneity": (P / (1.0 + diff ** 2)).sum(axis=(1, 2)),
        "asm": (P ** 2).sum(axis=(1, 2)),
        "entropy": -(P * logP).sum(axis=(1, 2)),
        "correlation": corr,
        "mean": mu,
        "variance": var,
        "sum_average": (psum * k).sum(axis=1),
        "sum_entropy": sum_ent,
        "difference_entropy": diff_ent,
    }


def _moments(v, starts, counts):
    """Per-object mean, std, skewness, excess kurtosis from sorted values."""
    v = v.astype(np.float64)
    s1 = np.add.reduceat(v, starts)
    s2 = np.add.reduceat(v * v, starts)
    s3 = np.add.reduceat(v ** 3, starts)
    s4 = np.add.reduceat(v ** 4, starts)
    return _moments_from_sums(counts, s1, s2, s3, s4)


def _moments_from_sums(nn, s1, s2, s3, s4):
    with np.errstate(divide="ignore", invalid="ignore"):
        n = np.where(nn > 0, nn, np.nan)
        m = s1 / n
        m2 = np.maximum(s2 / n - m * m, 0)
        m3 = s3 / n - 3 * m * s2 / n + 2 * m ** 3
        m4 = s4 / n - 4 * m * s3 / n + 6 * m * m * s2 / n - 3 * m ** 4
        sd = np.sqrt(m2)
        skew = np.where(m2 > 1e-12, m3 / np.power(m2, 1.5), 0.0)
        kurt = np.where(m2 > 1e-12, m4 / (m2 * m2) - 3.0, 0.0)
    return m, sd, skew, kurt


def _quantiles(v, obj, starts, counts, qs):
    order = np.lexsort((v, obj))
    vs = v[order].astype(np.float64)
    ends = starts + counts - 1
    out = []
    for q in qs:
        pos = starts + q * (counts - 1)
        lo = np.floor(pos).astype(np.int64)
        frac = pos - lo
        hi = np.minimum(lo + 1, ends)
        out.append(vs[lo] * (1 - frac) + vs[hi] * frac)
    return out


def _boundary_mask(labels):
    """Pixels of a nucleus touching another label, the background or the image edge."""
    b = np.zeros(labels.shape, dtype=bool)
    lp = np.pad(labels, 1, mode="constant", constant_values=-1)
    core = lp[1:-1, 1:-1]
    for sl in ((slice(0, -2), slice(1, -1)), (slice(2, None), slice(1, -1)),
               (slice(1, -1), slice(0, -2)), (slice(1, -1), slice(2, None))):
        b |= lp[sl] != core
    return b & (labels > 0)


# ---- main entry point ------------------------------------------------------------

def compute_features(img, labels, refs=None, ring_radius=30, perinuclear_radius=4,
                     texture_levels=16, nuclear_channel=0, progress=None):
    """Compute one row of features per nucleus.

    img: (C, Y, X) raw intensities. labels: (Y, X) integer labels.
    refs: per-channel image references from the intensity survey, a list of
    dicts with 'bg' (background), 'nuc' (mean in nuclei), 'tex_lo'/'tex_hi'
    (texture quantisation range). Without refs, they are estimated from
    this image (fine for a whole image, less consistent for a crop).
    Returns a DataFrame (META_COLUMNS + feature columns), one row per label.
    """
    def step(msg):
        if progress:
            progress(msg)

    labels = np.ascontiguousarray(labels, dtype=np.int32)
    img = np.ascontiguousarray(img, dtype=np.float32)
    C, H, W = img.shape
    ids = np.unique(labels)
    ids = ids[ids > 0].astype(np.int32)
    n = len(ids)
    if n == 0:
        return pd.DataFrame(columns=META_COLUMNS)
    lut = np.zeros(int(labels.max()) + 1, dtype=np.int64)
    lut[ids] = np.arange(n)

    if refs is None:
        refs = estimate_refs(img, nuclear_channel)

    # Pixels grouped by nucleus
    flat = labels.ravel()
    fg = np.flatnonzero(flat)
    obj_unsorted = lut[flat[fg]]
    order = np.argsort(obj_unsorted, kind="stable")
    pix = fg[order]
    obj = obj_unsorted[order]
    counts = np.bincount(obj, minlength=n)
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    ys = pix // W
    xs = pix % W

    cols = {}
    cy = np.add.reduceat(ys.astype(np.float64), starts) / counts
    cx = np.add.reduceat(xs.astype(np.float64), starts) / counts
    by0 = np.minimum.reduceat(ys, starts)
    bx0 = np.minimum.reduceat(xs, starts)
    by1 = np.maximum.reduceat(ys, starts)
    bx1 = np.maximum.reduceat(xs, starts)
    cols["label"] = ids
    cols["centroid_y"] = cy
    cols["centroid_x"] = cx
    cols["bbox_y0"], cols["bbox_x0"], cols["bbox_y1"], cols["bbox_x1"] = by0, bx0, by1, bx1
    cols["touches_border"] = (by0 == 0) | (bx0 == 0) | (by1 == H - 1) | (bx1 == W - 1)

    # ---- shape
    step("shape")
    boundary = _boundary_mask(labels)
    bpix = np.flatnonzero(boundary.ravel())
    bobj = lut[flat[bpix]]
    border = np.argsort(bobj, kind="stable")
    bpix = bpix[border]
    bcount = np.bincount(bobj, minlength=n)
    bstart = np.concatenate([[0], np.cumsum(bcount)[:-1]]).astype(np.int64)
    bys = (bpix // W).astype(np.int64)
    bxs = (bpix % W).astype(np.int64)

    area = counts.astype(np.float64)
    perim = _perimeter(labels, boundary, lut, n, _PERIM_W)
    hull_area, feret_max, feret_min = _hull(bstart, bcount.astype(np.int64), bys, bxs)
    # Central moments (y = rows, x = columns, as in skimage)
    dy = ys - cy[obj]
    dx = xs - cx[obj]

    def msum(p, q):
        return np.add.reduceat((dy ** p) * (dx ** q), starts)

    mu = {(p, q): msum(p, q) for p, q in ((2, 0), (0, 2), (1, 1), (3, 0), (0, 3), (2, 1), (1, 2))}
    a, c_, b = mu[(2, 0)] / area, mu[(0, 2)] / area, mu[(1, 1)] / area
    root = np.sqrt(((a - c_) / 2) ** 2 + b ** 2)
    l1 = (a + c_) / 2 + root
    l2 = np.maximum((a + c_) / 2 - root, 0)
    major = 4 * np.sqrt(l1)
    minor = 4 * np.sqrt(l2)
    eq_diam = np.sqrt(4 * area / np.pi)
    cols["shape_area"] = area
    cols["shape_perimeter"] = perim
    cols["shape_area_convex"] = hull_area
    with np.errstate(divide="ignore", invalid="ignore"):
        cols["shape_solidity"] = np.where(hull_area > 0, area / hull_area, 1)
        cols["shape_extent"] = area / ((by1 - by0 + 1) * (bx1 - bx0 + 1))
        cols["shape_eccentricity"] = np.where(l1 > 0, np.sqrt(np.maximum(1 - l2 / np.where(l1 > 0, l1, 1), 0)), 0)
    cols["shape_major_axis"] = major
    cols["shape_minor_axis"] = minor
    cols["shape_equivalent_diameter"] = eq_diam
    cols["shape_feret_max"] = feret_max
    cols["shape_feret_min"] = feret_min
    with np.errstate(divide="ignore", invalid="ignore"):
        cols["shape_circularity"] = np.where(perim > 0, 4 * np.pi * area / perim ** 2, 0)
        cols["shape_aspect_ratio"] = np.where(minor > 0, major / np.where(minor > 0, minor, 1), 1)
        cols["shape_roundness"] = np.where(major > 0, 4 * area / (np.pi * major ** 2), 0)
        cols["shape_feret_ratio"] = np.where(feret_max > 0, feret_min / np.where(feret_max > 0, feret_max, 1), 1)
    cols["shape_inertia_eig1"] = l1
    cols["shape_inertia_eig2"] = l2
    # Hu moments from normalised central moments
    nu = {k: v / area ** (1 + (k[0] + k[1]) / 2) for k, v in mu.items()}
    n20, n02, n11 = nu[(2, 0)], nu[(0, 2)], nu[(1, 1)]
    n30, n03, n21, n12 = nu[(3, 0)], nu[(0, 3)], nu[(2, 1)], nu[(1, 2)]
    t1, t2 = n30 + n12, n21 + n03
    hu = [
        n20 + n02,
        (n20 - n02) ** 2 + 4 * n11 ** 2,
        (n30 - 3 * n12) ** 2 + (3 * n21 - n03) ** 2,
        t1 ** 2 + t2 ** 2,
        (n30 - 3 * n12) * t1 * (t1 ** 2 - 3 * t2 ** 2) + (3 * n21 - n03) * t2 * (3 * t1 ** 2 - t2 ** 2),
        (n20 - n02) * (t1 ** 2 - t2 ** 2) + 4 * n11 * t1 * t2,
        (3 * n21 - n03) * t1 * (t1 ** 2 - 3 * t2 ** 2) - (n30 - 3 * n12) * t2 * (3 * t1 ** 2 - t2 ** 2),
    ]
    for k, h in enumerate(hu):
        # Log scale: Hu moments span many orders of magnitude
        cols[f"shape_hu{k + 1}"] = -np.sign(h) * np.log10(np.abs(h) + 1e-30)

    # ---- radial position of each pixel inside its nucleus
    interior = (labels > 0) & ~boundary
    dist = ndimage.distance_transform_edt(interior).ravel()[pix]
    dmax = np.maximum.reduceat(dist, starts)
    dnorm = dist / np.maximum(dmax[obj], 1e-6)
    core = dnorm >= 0.5
    n_core = np.add.reduceat(core.astype(np.float64), starts)
    n_rim = counts - n_core
    cols["shape_max_inner_distance"] = dmax

    # ---- per-channel intensities
    img_flat = img.reshape(C, -1)
    means = []
    for c in range(C):
        step(f"intensity c{c}")
        v = img_flat[c][pix]
        m, sd, skew, kurt = _moments(v, starts, counts)
        means.append(m)
        s = np.add.reduceat(v.astype(np.float64), starts)
        cols[f"int_c{c}_mean"] = m
        cols[f"int_c{c}_std"] = sd
        cols[f"int_c{c}_cv"] = np.where(m > 0, sd / np.where(m > 0, m, 1), 0)
        cols[f"int_c{c}_skewness"] = skew
        cols[f"int_c{c}_kurtosis"] = kurt
        cols[f"int_c{c}_min"] = np.minimum.reduceat(v, starts)
        cols[f"int_c{c}_max"] = np.maximum.reduceat(v, starts)
        cols[f"int_c{c}_sum"] = s
        qv = _quantiles(v, obj, starts, counts, QUANTILES)
        for q, val in zip(QUANTILES, qv):
            cols[f"int_c{c}_q{int(round(q * 100)):02d}"] = val
        cols[f"int_c{c}_iqr"] = qv[4] - qv[2]

        ref = refs[c]
        scale = max(ref["nuc"] - ref["bg"], 1.0)
        cols[f"norm_c{c}_mean"] = (m - ref["bg"]) / scale
        cols[f"norm_c{c}_q90"] = (qv[5] - ref["bg"]) / scale
        cols[f"norm_c{c}_max"] = (cols[f"int_c{c}_max"] - ref["bg"]) / scale

        # Core vs rim, and how far the stain's centre of mass is from the nucleus centre
        vc = np.add.reduceat(np.where(core, v, 0).astype(np.float64), starts)
        with np.errstate(divide="ignore", invalid="ignore"):
            core_mean = np.where(n_core > 0, vc / n_core, m)
            rim_mean = np.where(n_rim > 0, (s - vc) / np.where(n_rim > 0, n_rim, 1), m)
            cols[f"rad_c{c}_core_mean"] = core_mean
            cols[f"rad_c{c}_rim_mean"] = rim_mean
            cols[f"rad_c{c}_core_rim_ratio"] = np.where(rim_mean > 0, core_mean / rim_mean, 1)
            wy = np.add.reduceat(ys * v.astype(np.float64), starts) / np.where(s > 0, s, 1)
            wx = np.add.reduceat(xs * v.astype(np.float64), starts) / np.where(s > 0, s, 1)
            cols[f"rad_c{c}_offcentre"] = np.hypot(wy - cy, wx - cx) / np.maximum(eq_diam / 2, 1e-6)

    # ---- between channels, inside the nucleus
    step("channels")
    for c in range(C):
        for c2 in range(c + 1, C):
            va = img_flat[c][pix].astype(np.float64)
            vb = img_flat[c2][pix].astype(np.float64)
            sab = np.add.reduceat(va * vb, starts) / counts
            cov = sab - means[c] * means[c2]
            sa = cols[f"int_c{c}_std"]
            sb = cols[f"int_c{c2}_std"]
            with np.errstate(divide="ignore", invalid="ignore"):
                corr = np.where((sa > 1e-9) & (sb > 1e-9), cov / (sa * sb), 0)
            cols[f"xch_c{c}c{c2}_covariance"] = cov
            cols[f"xch_c{c}c{c2}_correlation"] = corr
    nuc_ch = nuclear_channel
    for c in range(C):
        if c == nuc_ch:
            continue
        with np.errstate(divide="ignore", invalid="ignore"):
            cols[f"xch_c{c}_to_c{nuc_ch}_ratio"] = np.where(means[nuc_ch] > 0, means[c] / means[nuc_ch], 0)

    # ---- neighbourhood rings (numba)
    step("neighbourhood")
    bbox = np.stack([by0, bx0, by1, bx1], axis=1).astype(np.int64)
    (ring_n, ring_s, ring_min, ring_max, ring_xy,
     peri_n, peri_s, peri_max) = _rings(labels, img, ids, bbox, bstart, bcount.astype(np.int64),
                                        bys, bxs, int(ring_radius), int(perinuclear_radius))
    cols["ring_pixels"] = ring_n
    cols["peri_background_fraction"] = peri_n / np.maximum(ring_n, 1)
    ring_means = []
    for c in range(C):
        m, sd, skew, kurt = _moments_from_sums(ring_n, ring_s[:, c, 0], ring_s[:, c, 1], ring_s[:, c, 2], ring_s[:, c, 3])
        m = np.nan_to_num(m, nan=means[c])
        ring_means.append(m)
        cols[f"ring_c{c}_mean"] = m
        cols[f"ring_c{c}_std"] = np.nan_to_num(sd)
        cols[f"ring_c{c}_skewness"] = np.nan_to_num(skew)
        cols[f"ring_c{c}_kurtosis"] = np.nan_to_num(kurt)
        cols[f"ring_c{c}_min"] = np.where(np.isfinite(ring_min[:, c]), ring_min[:, c], m)
        cols[f"ring_c{c}_max"] = np.where(np.isfinite(ring_max[:, c]), ring_max[:, c], m)
        cols[f"ring_c{c}_sum"] = ring_s[:, c, 0]
        with np.errstate(divide="ignore", invalid="ignore"):
            pm = np.where(peri_n > 0, peri_s[:, c, 0] / np.maximum(peri_n, 1), m)
            pv = np.where(peri_n > 0, peri_s[:, c, 1] / np.maximum(peri_n, 1) - pm * pm, 0)
        cols[f"peri_c{c}_mean"] = pm
        cols[f"peri_c{c}_std"] = np.sqrt(np.maximum(pv, 0))
        cols[f"peri_c{c}_max"] = np.where(np.isfinite(peri_max[:, c]), peri_max[:, c], pm)
        ref = refs[c]
        scale = max(ref["nuc"] - ref["bg"], 1.0)
        cols[f"norm_c{c}_ring_mean"] = (m - ref["bg"]) / scale
        cols[f"norm_c{c}_peri_mean"] = (pm - ref["bg"]) / scale
        with np.errstate(divide="ignore", invalid="ignore"):
            cols[f"ctr_c{c}_nucleus_vs_ring"] = np.log2(np.maximum(means[c], 1e-3) / np.maximum(m, 1e-3))
            cols[f"ctr_c{c}_nucleus_vs_peri"] = np.log2(np.maximum(means[c], 1e-3) / np.maximum(pm, 1e-3))
            cols[f"ctr_c{c}_peri_vs_ring"] = np.log2(np.maximum(pm, 1e-3) / np.maximum(m, 1e-3))
    p = 0
    for c in range(C):
        for c2 in range(c + 1, C):
            with np.errstate(divide="ignore", invalid="ignore"):
                cov = np.where(ring_n > 0, ring_xy[:, p] / np.maximum(ring_n, 1) - ring_means[c] * ring_means[c2], 0)
            cols[f"xch_c{c}c{c2}_ring_covariance"] = cov
            p += 1

    # ---- texture: GLCM (Haralick), LBP, gradients (channels in parallel threads)
    step("texture")

    def texture(c):
        out = {}
        ref = refs[c]
        lo, hi = ref["tex_lo"], ref["tex_hi"]
        L = int(texture_levels)
        q = np.clip(((img[c] - lo) / max(hi - lo, 1e-6) * L).astype(np.int64), 0, L - 1).astype(np.uint8)
        har = _haralick(_glcm(q, labels, lut, n, L))
        for k, val in har.items():
            out[f"tex_c{c}_{k}"] = val

        lbp_in = np.round(img[c]).astype(np.int32)
        lbp = local_binary_pattern(lbp_in, LBP_POINTS, 1, method="uniform").astype(np.int64).ravel()[pix]
        hist = np.bincount(obj * LBP_BINS + lbp, minlength=n * LBP_BINS).reshape(n, LBP_BINS)
        hist = hist / counts[:, None]
        for k in range(LBP_BINS):
            out[f"lbp_c{c}_bin{k}"] = hist[:, k]

        g1 = ndimage.gaussian_filter(img[c], 1.0)
        grad = np.hypot(ndimage.sobel(g1, 0), ndimage.sobel(g1, 1)).ravel()[pix]
        dog = (g1 - ndimage.gaussian_filter(img[c], 3.0)).ravel()[pix]
        gm, gsd, _, _ = _moments(grad, starts, counts)
        dm, dsd, _, _ = _moments(dog, starts, counts)
        out[f"grad_c{c}_edge_mean"] = gm
        out[f"grad_c{c}_edge_std"] = gsd
        out[f"grad_c{c}_spots_mean"] = dm
        out[f"grad_c{c}_spots_std"] = dsd
        out[f"grad_c{c}_spots_max"] = np.maximum.reduceat(dog, starts)
        return out

    with ThreadPoolExecutor(max_workers=C) as ex:
        for out in ex.map(texture, range(C)):
            cols.update(out)

    # ---- local density of nuclei
    step("context")
    tree = cKDTree(np.stack([cy, cx], axis=1))
    k = min(6, n)
    dists, _ = tree.query(np.stack([cy, cx], axis=1), k=k)
    dists = np.atleast_2d(dists)
    cols["ctx_nearest_distance"] = dists[:, 1] if k > 1 else np.zeros(n)
    cols["ctx_mean_distance_5nn"] = dists[:, 1:].mean(axis=1) if k > 1 else np.zeros(n)
    within = tree.query_ball_point(np.stack([cy, cx], axis=1), r=float(ring_radius), return_length=True)
    cols["ctx_neighbours_in_ring"] = np.asarray(within) - 1

    df = pd.DataFrame(cols)
    feats = feature_columns(df)
    df[feats] = df[feats].replace([np.inf, -np.inf], np.nan).fillna(0).astype(np.float32)
    return df


def estimate_refs(img, nuclear_channel=0):
    """Per-channel reference intensities of one image (see survey.image_refs)."""
    from .survey import image_refs
    return image_refs(img, nuclear_channel)["refs"]
