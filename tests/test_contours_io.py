import os

import numpy as np
import roifile
import tifffile

from nucleiquant import contours, io, rois


def test_outlines_lie_on_boundaries(synthetic):
    _, labels = synthetic
    ids, off, ys, xs = contours.trace_outlines(labels)
    assert list(ids) == [1, 2, 3, 4]
    owner = np.repeat(ids, np.diff(off))
    assert (labels[ys, xs] == owner).all()
    # A disc of radius r has an outline spanning its diameter
    for i, r in zip(range(4), (8, 10, 6, 9)):
        span = ys[off[i]:off[i + 1]].max() - ys[off[i]:off[i + 1]].min()
        assert span == 2 * r


def test_pack_outlines_layout(synthetic):
    _, labels = synthetic
    ids, off, ys, xs = contours.trace_outlines(labels)
    buf = contours.pack_outlines(ids, off, ys, xs)
    n, m = np.frombuffer(buf[:8], np.uint32)
    assert n == 4 and m == len(ys)
    assert len(buf) == 8 + 4 * n + 4 * (n + 1) + 4 * m


def test_rois_roundtrip(tmp_path, synthetic):
    _, labels = synthetic
    ids, off, ys, xs = contours.trace_outlines(labels)
    path = rois.write_rois(str(tmp_path / "r.zip"), ids, off, ys, xs, names={1: "S_1"}, colors={1: "#FF8A3D"})
    rs = roifile.roiread(path)
    assert len(rs) == 4
    assert rs[0].name == "S_1" and rs[0].stroke_color == bytes([255, 0xFF, 0x8A, 0x3D])


def test_crop_keeps_imagej_metadata(tmp_path):
    img = (np.arange(3 * 20 * 30).reshape(3, 20, 30) % 4000).astype(np.uint16)
    p = str(tmp_path / "crop.tif")
    io.write_image(p, img, pixel_size=0.4316)
    info = io.image_info(p)
    assert info["channels"] == 3 and info["height"] == 20 and info["width"] == 30
    assert abs(info["pixel_size"] - 0.4316) < 1e-3
    assert np.array_equal(io.read_image(p), img)
    with tifffile.TiffFile(p) as t:
        assert t.series[0].axes == "CYX"


def test_labels_written_as_tif_and_h5(tmp_path, synthetic):
    _, labels = synthetic
    base = str(tmp_path / "x_labels")
    io.write_labels(base, labels)
    assert os.path.exists(base + ".tif") and os.path.exists(base + ".h5")
    assert np.array_equal(io.read_labels(base), labels)
