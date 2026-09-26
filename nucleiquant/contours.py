"""Nucleus outlines as polygons (for the viewer and ImageJ ROIs).

Each outline runs through the centres of the nucleus' boundary pixels
(8-connected Moore tracing), with collinear points removed.
"""

import numpy as np
from numba import njit, prange

__all__ = ["trace_outlines", "pack_outlines"]

# Clockwise neighbour offsets starting North: N, NE, E, SE, S, SW, W, NW
_DY = np.array([-1, -1, 0, 1, 1, 1, 0, -1], dtype=np.int64)
_DX = np.array([0, 1, 1, 1, 0, -1, -1, -1], dtype=np.int64)


@njit(cache=True)
def _is(labels, y, x, lab):
    H, W = labels.shape
    return 0 <= y < H and 0 <= x < W and labels[y, x] == lab


@njit(parallel=True, cache=True)
def _trace(labels, ids, start_y, start_x, cap, offsets, dy8, dx8):
    n = ids.shape[0]
    out_y = np.zeros(offsets[-1], dtype=np.int32)
    out_x = np.zeros(offsets[-1], dtype=np.int32)
    length = np.zeros(n, dtype=np.int64)
    for i in prange(n):
        lab = ids[i]
        sy = start_y[i]
        sx = start_x[i]
        base = offsets[i]
        maxlen = offsets[i + 1] - base
        out_y[base] = sy
        out_x[base] = sx
        k = 1
        cy = sy
        cx = sx
        # Start pixel is top-left of the object: West neighbour is outside
        back = 6
        first_dir = -1
        steps = 0
        while steps < 4 * cap[i] + 8:
            steps += 1
            found = -1
            for t in range(1, 9):
                d = (back + t) % 8
                if _is(labels, cy + dy8[d], cx + dx8[d], lab):
                    found = d
                    break
            if found < 0:
                break  # single pixel
            ny = cy + dy8[found]
            nx = cx + dx8[found]
            if cy == sy and cx == sx:
                if first_dir < 0:
                    first_dir = found
                elif found == first_dir:
                    break  # back at the start, leaving the same way (Jacob's criterion)
            # Backtrack: neighbour checked just before `found`, seen from the new pixel
            back = (found + 5) % 8 if found % 2 == 1 else (found + 6) % 8
            cy = ny
            cx = nx
            if k < maxlen:
                out_y[base + k] = cy
                out_x[base + k] = cx
                k += 1
        length[i] = k
    return out_y, out_x, length


@njit(cache=True)
def _simplify(ys, xs, offsets, length):
    """Drop points lying on a straight run; returns packed arrays and new offsets."""
    n = length.shape[0]
    new_off = np.zeros(n + 1, dtype=np.int64)
    out_y = np.zeros(ys.shape[0], dtype=np.int32)
    out_x = np.zeros(xs.shape[0], dtype=np.int32)
    w = 0
    for i in range(n):
        base = offsets[i]
        m = length[i]
        # The trace ends back on the start pixel: drop the repeat
        if m > 1 and ys[base + m - 1] == ys[base] and xs[base + m - 1] == xs[base]:
            m -= 1
        start_w = w
        for k in range(m):
            py = ys[base + (k - 1) % m]
            px = xs[base + (k - 1) % m]
            cy = ys[base + k]
            cx = xs[base + k]
            ny = ys[base + (k + 1) % m]
            nx = xs[base + (k + 1) % m]
            if m > 2 and (cy - py) == (ny - cy) and (cx - px) == (nx - cx):
                continue
            out_y[w] = cy
            out_x[w] = cx
            w += 1
        if w == start_w:  # degenerate: keep the start pixel
            out_y[w] = ys[base]
            out_x[w] = xs[base]
            w += 1
        new_off[i + 1] = w
    return out_y[:w], out_x[:w], new_off


def trace_outlines(labels):
    """Outline polygons of every label.

    Returns (ids, offsets, ys, xs): the outline of ids[i] is
    ys[offsets[i]:offsets[i+1]], xs[...] (pixel-centre coordinates).
    """
    labels = np.ascontiguousarray(labels, dtype=np.int32)
    H, W = labels.shape
    flat = labels.ravel()
    fg = np.flatnonzero(flat)
    lab = flat[fg]
    ids, first = np.unique(lab, return_index=True)  # first pixel in raster order = top-left
    if len(ids) == 0:
        return ids.astype(np.int32), np.zeros(1, np.int64), np.zeros(0, np.int32), np.zeros(0, np.int32)
    counts = np.bincount(lab)[ids]
    start_y = (fg[first] // W).astype(np.int64)
    start_x = (fg[first] % W).astype(np.int64)
    cap = counts.astype(np.int64)
    offsets = np.concatenate([[0], np.cumsum(4 * cap + 8)]).astype(np.int64)
    ys, xs, length = _trace(labels, ids.astype(np.int32), start_y, start_x, cap, offsets, _DY, _DX)
    ys, xs, off = _simplify(ys, xs, offsets, length)
    return ids.astype(np.int32), off, ys, xs


def pack_outlines(ids, offsets, ys, xs):
    """Binary layout for the browser: header + ids (u32) + offsets (u32) + points (u16 x,y)."""
    n = len(ids)
    header = np.array([n, len(ys)], dtype=np.uint32)
    pts = np.empty(2 * len(ys), dtype=np.uint16)
    pts[0::2] = xs
    pts[1::2] = ys
    return header.tobytes() + ids.astype(np.uint32).tobytes() + offsets.astype(np.uint32).tobytes() + pts.tobytes()
