import numpy as np
import pytest

from nucleiquant import metadata, quantify
from nucleiquant.api import label_progress
from nucleiquant.project import Project


def test_label_progress_per_crop_is_a_recommendation():
    cats = ["dead", "unstained", "cat1"]
    crops = ["crop01", "crop02"]
    ann = {("crop01", i): "dead" for i in range(10)}
    ann.update({("crop01", 100 + i): "cat1" for i in range(4)})
    ann.update({("crop02", 200 + i): "cat1" for i in range(12)})
    p = label_progress(cats, crops, ann, target=10)
    assert p["per_crop"]["crop01"] == {"dead": 10, "unstained": 0, "cat1": 4}
    assert p["needed_per_crop"] == {"crop01": 16, "crop02": 20}
    assert p["needed"] == 36
    assert {"crop_id": "crop02", "category": "dead", "n": 0} in p["shortfalls"]
    assert p["unused"] == ["unstained"]
    # Two labeled categories are enough to train, even with shortfalls
    assert p["ready"] and not p["complete"]


def test_label_progress_needs_two_categories():
    p = label_progress(["dead", "cat1"], ["crop01"], {("crop01", 1): "cat1"}, target=10)
    assert not p["ready"]


def test_filename_fields_are_trimmed():
    f = metadata.parse_filename("H9_dM_ J140_PBC_20Xa_g1d08_OG1_s3.tif")
    assert f["day"] == "J140"


def _project(tmp_path, monkeypatch, user_categories=("S", "T")):
    monkeypatch.setenv("NQ_STATE_DIR", str(tmp_path / "state"))
    images = tmp_path / "images"
    images.mkdir(parents=True)
    p = Project.create(str(images), "t", n_channels=2)
    p.data["genotypes"] = {"WT": "WT/WT", "KO": "KO/KO"}
    for i, name in enumerate(user_categories, 1):
        p.categories.append({"id": f"cat{i}", "name": name, "color": "#FF8A3D", "builtin": False})
    return p


def _summaries(rng):
    out = []
    for clone in ("WT", "KO"):
        for og in range(1, 5):
            for s in range(1, 5):
                counts = {"dead": int(rng.integers(100, 200)), "unstained": int(rng.integers(20, 40)),
                          "cat1": int(rng.integers(50, 80)) + (60 if clone == "KO" else 0), "cat2": int(rng.integers(10, 30))}
                out.append({"image": f"{clone}_dQ_J70_SN_20X_g1_OG{og}_s{s}.tif", "counts": counts})
    return out


def test_reference_presets(tmp_path, monkeypatch):
    p = _project(tmp_path, monkeypatch)
    refs = {r["id"]: r["categories"] for r in quantify.references(p)}
    assert refs["all"] == ["dead", "unstained", "cat1", "cat2"]
    assert refs["living"] == ["unstained", "cat1", "cat2"]
    assert refs["stained"] == ["cat1", "cat2"]
    bare = _project(tmp_path / "b", monkeypatch, user_categories=())
    assert "stained" not in {r["id"] for r in quantify.references(bare)}


def test_results_view_bars_sum_to_100(tmp_path, monkeypatch):
    p = _project(tmp_path, monkeypatch)
    view = quantify.results_view(p, _summaries(np.random.default_rng(0)), ["cat1", "cat2"])
    assert view["reference"]["name"] == "stained cells" and view["reference"]["saved"]
    assert len(view["bars"]) == 8
    for b in view["bars"]:
        assert sum(b["values"].values()) == pytest.approx(100, abs=0.01)
        assert b["n"] == b["counts"]["cat1"] + b["counts"]["cat2"]
    assert {g["label"] for g in view["group_bars"]} == {"WT/WT", "KO/KO"}
    s_row = next(r for r in view["stats"] if r["Category"] == "S")
    assert s_row["Measure"] == "% of stained cells" and s_row["p"] < 0.05


def test_custom_reference_goes_to_excel(tmp_path, monkeypatch):
    import pandas as pd
    p = _project(tmp_path, monkeypatch)
    p.data["references"] = [{"id": "ref1", "name": "S and dead", "categories": ["dead", "cat1"]}]
    view = quantify.results_view(p, _summaries(np.random.default_rng(1)), ["cat1", "dead"])
    assert view["reference"]["name"] == "S and dead"
    res = quantify.write_outputs(p, _summaries(np.random.default_rng(1)))
    props = pd.read_excel(res["excel"], sheet_name="proportions")
    assert {"S (% S and dead)", "S (% stained cells)", "T (% living cells)", "Dead (% all nuclei)"} <= set(props.columns)
    measures = set(pd.read_excel(res["excel"], sheet_name="statistics")["Measure"])
    assert {"% of all nuclei", "% of living cells", "% of stained cells", "% of S and dead"} <= measures
