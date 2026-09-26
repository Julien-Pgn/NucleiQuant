import numpy as np
import pandas as pd
import pytest
from scipy import ndimage

from nucleiquant import features
from conftest import TEST_IMAGES, real_data

REFS = [{"nuc": 100.0, "bg": 10.0, "tex_lo": 0.0, "tex_hi": 500.0}] * 2


def test_basic_intensity_and_shape(synthetic):
    img, labels = synthetic
    df = features.compute_features(img, labels, REFS, ring_radius=10, perinuclear_radius=3).set_index("label")
    for lab in range(1, 5):
        m = labels == lab
        assert df.loc[lab, "shape_area"] == m.sum()
        assert df.loc[lab, "int_c0_mean"] == pytest.approx(100 * lab)
        assert df.loc[lab, "int_c0_std"] == pytest.approx(0, abs=1e-4)
        assert df.loc[lab, "norm_c0_mean"] == pytest.approx((100 * lab - 10) / 90)
    # Round objects: solidity and circularity close to 1, eccentricity close to 0
    assert (df["shape_solidity"] > 0.85).all()
    assert (df["shape_eccentricity"] < 0.3).all()
    assert not df[features.feature_columns(df.reset_index())].isna().any().any()


def _ring_reference(img, labels, lab, R, r):
    """Slow, obvious implementation of ilastik's neighbourhood (distance < R, object excluded)."""
    obj = labels == lab
    dist = ndimage.distance_transform_edt(~obj)
    ring = (dist < R) & ~obj
    peri = (dist < r) & ~obj & (labels == 0)
    return img[:, ring], img[:, peri]


def test_rings_match_reference(synthetic):
    img, labels = synthetic
    rng = np.random.default_rng(0)
    img = img + rng.normal(0, 5, img.shape).astype(np.float32)
    R, r = 15, 4
    df = features.compute_features(img, labels, REFS, ring_radius=R, perinuclear_radius=r).set_index("label")
    for lab in range(1, 5):
        ring, peri = _ring_reference(img, labels, lab, R, r)
        assert df.loc[lab, "ring_pixels"] == ring.shape[1]
        for c in range(2):
            assert df.loc[lab, f"ring_c{c}_mean"] == pytest.approx(ring[c].mean(), rel=1e-4)
            assert df.loc[lab, f"ring_c{c}_max"] == pytest.approx(ring[c].max(), rel=1e-5)
            assert df.loc[lab, f"ring_c{c}_std"] == pytest.approx(ring[c].std(), rel=1e-3)
            assert df.loc[lab, f"peri_c{c}_mean"] == pytest.approx(peri[c].mean(), rel=1e-4)


def test_texture_distinguishes_patterns():
    H, W = 60, 120
    labels = np.zeros((H, W), np.int32)
    labels[10:50, 10:50] = 1
    labels[10:50, 70:110] = 2
    img = np.full((1, H, W), 100, np.float32)
    yy, xx = np.mgrid[:H, :W]
    img[0][labels == 2] = np.where((yy + xx)[labels == 2] % 2, 400, 100)  # checkerboard
    refs = [{"nuc": 250.0, "bg": 0.0, "tex_lo": 0.0, "tex_hi": 500.0}]
    df = features.compute_features(img, labels, refs).set_index("label")
    assert df.loc[2, "tex_c0_contrast"] > df.loc[1, "tex_c0_contrast"]
    assert df.loc[1, "tex_c0_asm"] == pytest.approx(1.0)


@real_data
def test_matches_ilastik_exported_values():
    """Our per-nucleus means equal ilastik's (V1 tables) wherever both see the same pixels."""
    import tifffile
    from nucleiquant import io, survey
    name = "Pa_dQ_J70_SNd2T_20Xa_g1dt08_OG1_s1"
    img = io.read_image(f"{TEST_IMAGES}/{name}.tif")[:, :1200, :1200]
    lbl = tifffile.imread(f"{TEST_IMAGES}/lbl/{name}_labels.tif").astype(np.int32)[:1200, :1200]
    df = features.compute_features(img, lbl, survey.image_refs(img)["refs"]).set_index("label")
    t = pd.read_csv(f"{TEST_IMAGES}/{name}_table.csv")
    x = np.round(t["Center of the object_0"]).astype(int)
    y = np.round(t["Center of the object_1"]).astype(int)
    keep = (x < 1180) & (y < 1180)
    t = t[keep].assign(label=lbl[y[keep], x[keep]])
    t = t[t.label > 0].join(df, on="label", how="inner")
    same = t[(t["Size in pixels"] == t["shape_area"]) & ~t["touches_border"]]
    assert len(same) > 1000
    for c in range(4):
        assert np.allclose(same[f"int_c{c}_mean"], same[f"Mean Intensity_{c}"], atol=1e-3)
