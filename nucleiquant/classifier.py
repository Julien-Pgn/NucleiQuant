"""Random-forest classification of nuclei into the user's categories.

Same algorithm as ilastik's object classifier (Breiman random forest,
100 trees, sqrt(n_features) tried per split, Gini impurity), here with
scikit-learn and a fixed seed so results are reproducible.

The labeled nuclei (with their feature vectors) are the source of truth:
they are saved next to the model, so the model can always be rebuilt.
"""

import datetime
import hashlib
import json
import os

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier

from .features import FEATURE_VERSION

__all__ = ["train", "cross_validate", "Classifier", "SEED"]

SEED = 0


def _forest(n_trees):
    return RandomForestClassifier(
        n_estimators=int(n_trees),
        max_features="sqrt",
        criterion="gini",
        n_jobs=-1,
        random_state=SEED,
    )


def train(X, y, n_trees=100):
    model = _forest(n_trees)
    model.fit(X, y)
    return model


def cross_validate(X, y, groups, categories, n_trees=100):
    """Accuracy on crops the model did not see (leave one crop out).

    With a single crop, falls back to 5-fold cross-validation.
    Returns a JSON-able dict with accuracy, per-category recall/precision
    and the confusion matrix (rows = true category, columns = predicted).
    """
    y = np.asarray(y)
    groups = np.asarray(groups)
    pred = np.empty(len(y), dtype=object)
    unique_groups = np.unique(groups)
    if len(unique_groups) >= 2:
        scheme = "leave-one-crop-out"
        folds = [(groups != g, groups == g) for g in unique_groups]
    else:
        scheme = "5-fold"
        rng = np.random.default_rng(SEED)
        fold_of = rng.permutation(len(y)) % 5
        folds = [(fold_of != k, fold_of == k) for k in range(5)]
    per_fold = []
    for tr, te in folds:
        if te.sum() == 0 or len(np.unique(y[tr])) < 1:
            continue
        m = train(X[tr], y[tr], n_trees)
        pred[te] = m.predict(X[te])
        per_fold.append(float((pred[te] == y[te]).mean()))
    ok = pred != None  # noqa: E711
    yt, yp = y[ok], pred[ok]
    idx = {c: i for i, c in enumerate(categories)}
    conf = np.zeros((len(categories), len(categories)), dtype=int)
    for a, b in zip(yt, yp):
        if a in idx and b in idx:
            conf[idx[a], idx[b]] += 1
    recall, precision = {}, {}
    for c, i in idx.items():
        tp = conf[i, i]
        recall[c] = float(tp / conf[i].sum()) if conf[i].sum() else None
        precision[c] = float(tp / conf[:, i].sum()) if conf[:, i].sum() else None
    valid = [r for r in recall.values() if r is not None]
    return {
        "scheme": scheme,
        "n": int(ok.sum()),
        "accuracy": float((yt == yp).mean()) if len(yt) else None,
        "balanced_accuracy": float(np.mean(valid)) if valid else None,
        "per_fold": per_fold,
        "recall": recall,
        "precision": precision,
        "confusion": conf.tolist(),
        "categories": list(categories),
    }


class Classifier:
    """A trained forest plus everything needed to reuse or rebuild it."""

    def __init__(self, model, categories, feature_names, info):
        self.model = model
        self.categories = list(categories)      # category ids known to the model
        self.feature_names = list(feature_names)
        self.info = info

    @classmethod
    def fit(cls, table, feature_names, categories, n_trees=100):
        """table: one row per labeled nucleus with 'category', 'crop_id' and features."""
        X = table[feature_names].to_numpy(dtype=np.float32)
        y = table["category"].to_numpy()
        known = [c for c in categories if c in set(y)]
        cv = cross_validate(X, y, table["crop_id"].to_numpy(), known, n_trees)
        model = train(X, y, n_trees)
        importances = sorted(zip(feature_names, model.feature_importances_), key=lambda t: -t[1])
        digest = hashlib.sha1()
        digest.update(json.dumps([feature_names, known, int(n_trees), FEATURE_VERSION]).encode())
        digest.update(np.ascontiguousarray(X).tobytes())
        digest.update("|".join(map(str, y)).encode())
        info = {
            "trained": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "n_labels": int(len(y)),
            "labels_per_category": {c: int((y == c).sum()) for c in known},
            "n_features": len(feature_names),
            "n_trees": int(n_trees),
            "seed": SEED,
            "feature_version": FEATURE_VERSION,
            "sklearn_version": sklearn.__version__,
            "cross_validation": cv,
            "top_features": [{"feature": f, "importance": float(v)} for f, v in importances[:20]],
            "hash": digest.hexdigest()[:16],
        }
        return cls(model, list(model.classes_), feature_names, info)

    def predict(self, df):
        """(category ids, probabilities matrix, max probability) for a features table."""
        X = df[self.feature_names].to_numpy(dtype=np.float32)
        if len(X) == 0:
            return np.array([], dtype=object), np.zeros((0, len(self.categories))), np.zeros(0)
        proba = self.model.predict_proba(X)
        best = proba.argmax(axis=1)
        return np.array(self.categories, dtype=object)[best], proba, proba.max(axis=1)

    def save(self, folder, table=None):
        os.makedirs(folder, exist_ok=True)
        joblib.dump(self.model, os.path.join(folder, "model.joblib"), compress=3)
        meta = dict(self.info, categories=self.categories, feature_names=self.feature_names)
        with open(os.path.join(folder, "classifier.json"), "w") as f:
            json.dump(meta, f, indent=1)
        if table is not None:
            table.to_csv(os.path.join(folder, "training_set.csv.gz"), index=False, compression="gzip")

    @classmethod
    def load(cls, folder):
        with open(os.path.join(folder, "classifier.json")) as f:
            meta = json.load(f)
        path = os.path.join(folder, "model.joblib")
        try:
            model = joblib.load(path)
        except Exception:
            # Different scikit-learn version: rebuild from the saved training set
            table = pd.read_csv(os.path.join(folder, "training_set.csv.gz"))
            model = train(table[meta["feature_names"]].to_numpy(np.float32), table["category"].to_numpy(), meta["n_trees"])
        categories = meta.pop("categories")
        names = meta.pop("feature_names")
        return cls(model, categories, names, meta)
