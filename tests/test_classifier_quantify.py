import numpy as np
import pandas as pd

from nucleiquant import quantify
from nucleiquant.classifier import Classifier
from nucleiquant.project import Project


def _table(rng, n=40):
    rows = []
    for crop in ("crop01", "crop02"):
        for cat, mu in (("dead", 0.0), ("cat1", 3.0), ("cat2", 6.0)):
            for _ in range(n):
                rows.append({"crop_id": crop, "category": cat, "f1": rng.normal(mu, 1), "f2": rng.normal(-mu, 1), "f3": rng.normal()})
    return pd.DataFrame(rows)


def test_classifier_fit_cv_save_load(tmp_path):
    rng = np.random.default_rng(0)
    table = _table(rng)
    clf = Classifier.fit(table, ["f1", "f2", "f3"], ["dead", "unstained", "cat1", "cat2"], n_trees=50)
    cv = clf.info["cross_validation"]
    assert cv["scheme"] == "leave-one-crop-out"
    assert cv["accuracy"] > 0.9
    assert "unstained" not in clf.categories  # no labels -> not learned
    cats, proba, pmax = clf.predict(table)
    assert proba.shape == (len(table), 3) and (pmax <= 1).all()
    clf.save(str(tmp_path / "clf"), table)
    again = Classifier.load(str(tmp_path / "clf"))
    assert (again.predict(table)[0] == cats).all()
    assert again.info["hash"] == clf.info["hash"]


def test_quantify_tables_and_excel(tmp_path, monkeypatch):
    monkeypatch.setenv("NQ_STATE_DIR", str(tmp_path / "state"))
    images = tmp_path / "images"
    images.mkdir()
    p = Project.create(str(images), "t", n_channels=2)
    p.data["genotypes"] = {"WT": "WT/WT", "KO": "KO/KO"}
    p.categories.append({"id": "cat1", "name": "S", "color": "#FF8A3D", "builtin": False})
    summaries = []
    rng = np.random.default_rng(1)
    for clone in ("WT", "KO"):
        for og in range(1, 5):
            for s in range(1, 5):
                name = f"{clone}_dQ_J70_SN_20X_g1_OG{og}_s{s}.tif"
                dead, unst = int(rng.integers(100, 200)), int(rng.integers(10, 20))
                s_cells = int(rng.integers(50, 80)) + (60 if clone == "KO" else 0)
                summaries.append({"image": name, "counts": {"dead": dead, "unstained": unst, "cat1": s_cells}})
    tables = quantify.build_tables(p, summaries)
    assert len(tables["per_image"]) == 32
    assert len(tables["per_organoid"]) == 8
    assert (tables["per_organoid"]["Slices"] == 4).all()
    total = sum(sum(s["counts"].values()) for s in summaries)
    assert tables["per_image"]["Total"].sum() == total == tables["per_organoid"]["Total"].sum()
    res = quantify.write_outputs(p, summaries)
    assert res["n_nuclei"] == total
    stat = {r["Category"]: r for r in res["stats"] if r["Measure"] == "% of living cells"}
    assert stat["S"]["Test"] == "Mann-Whitney U" and stat["S"]["p"] < 0.05
    xl = pd.read_excel(res["excel"], sheet_name=None)
    assert {"per_image", "per_organoid", "per_organoid_curated", "proportions", "statistics", "classifier", "settings"} <= set(xl)
