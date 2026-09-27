import numpy as np
import pytest

from nucleiquant import evaluation, survey


def test_wilson_known_value():
    # 90 of 100: Wilson 95 % interval is about 82.6 %–94.5 %
    lo, hi = evaluation.wilson(90, 100)
    assert lo == pytest.approx(0.826, abs=0.002) and hi == pytest.approx(0.945, abs=0.002)
    assert evaluation.wilson(0, 0) == (None, None)


def test_evaluate_metrics():
    cats = ["dead", "unstained", "cat1"]
    y_true = ["dead"] * 10 + ["cat1"] * 10
    y_pred = ["dead"] * 9 + ["cat1"] + ["cat1"] * 8 + ["dead"] * 2
    m = evaluation.evaluate(y_true, y_pred, cats)
    assert m["n"] == 20
    assert m["accuracy"] == pytest.approx(17 / 20)
    assert m["balanced_accuracy"] == pytest.approx((0.9 + 0.8) / 2)
    by = {r["category"]: r for r in m["per_category"]}
    assert by["dead"]["recall"] == pytest.approx(0.9) and by["cat1"]["recall"] == pytest.approx(0.8)
    assert by["dead"]["precision"] == pytest.approx(9 / 11)
    assert by["unstained"]["n_test"] == 0 and by["unstained"]["recall"] is None
    assert m["categories_tested"] == ["dead", "cat1"]
    assert m["confusion"][0] == [9, 0, 1]
    lo, hi = m["balanced_accuracy_ci"]
    assert lo < m["balanced_accuracy"] < hi
    # kappa: po = 0.85, pe = 0.5*0.55 + 0.5*0.45 = 0.5
    assert m["kappa"] == pytest.approx((0.85 - 0.5) / 0.5)


def test_pick_test_images_excludes_training_and_is_reproducible():
    names = [f"{c}_x_OG{o}_s{s}.tif" for c in ("WT", "KO") for o in range(3) for s in range(3)]
    training = {"WT_x_OG0_s0.tif", "KO_x_OG1_s1.tif"}
    group = lambda n: n.split("_")[0]  # noqa: E731
    a = survey.pick_test_images(names, training, group, n_per_group=2, seed=0)
    b = survey.pick_test_images(names, training, group, n_per_group=2, seed=0)
    assert a == b and len(a) == 4
    assert not set(a) & training
    assert sorted(group(n) for n in a) == ["KO", "KO", "WT", "WT"]
