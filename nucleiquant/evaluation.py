"""Accuracy of the classifier on an independent test set, with confidence intervals.

Test cells are labeled by the user on test crops cut from images never used for
training, blind to the classifier's predictions. Cells are picked per category (a few of
each), so the headline number is the balanced accuracy (mean recall over categories);
plain accuracy is reported too, at the test set's own category balance.
"""

import numpy as np

__all__ = ["wilson", "evaluate", "methods_text"]

Z95 = 1.959964
BOOTSTRAP = 2000


def wilson(k, n, z=Z95):
    """Wilson score 95 % interval for k successes out of n."""
    if n == 0:
        return (None, None)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (float(max(0.0, centre - half)), float(min(1.0, centre + half)))


def _kappa(y_true, y_pred, labels):
    n = len(y_true)
    if n == 0:
        return None
    po = float(np.mean(y_true == y_pred))
    pe = sum(float(np.mean(y_true == c)) * float(np.mean(y_pred == c)) for c in labels)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def _balanced(y_true, y_pred, labels):
    recalls = [float(np.mean(y_pred[y_true == c] == c)) for c in labels if np.any(y_true == c)]
    return float(np.mean(recalls)) if recalls else None


def _macro_f1(y_true, y_pred, labels):
    """Mean F1 over the categories present in y_true (robust to unequal test counts)."""
    f1s = []
    for c in labels:
        n_true = int(np.sum(y_true == c))
        if not n_true:
            continue
        tp = int(np.sum((y_true == c) & (y_pred == c)))
        n_pred = int(np.sum(y_pred == c))
        rec = tp / n_true
        prec = tp / n_pred if n_pred else 0.0
        f1s.append(2 * rec * prec / (rec + prec) if rec + prec else 0.0)
    return float(np.mean(f1s)) if f1s else None


def evaluate(y_true, y_pred, categories, seed=0):
    """Metrics for true vs predicted category ids.

    categories: all category ids (order used for the confusion matrix).
    Balanced accuracy and kappa get bootstrap 95 % intervals (cells resampled);
    accuracy, recall and precision get Wilson intervals.
    """
    y_true = np.asarray(y_true, dtype=object)
    y_pred = np.asarray(y_pred, dtype=object)
    n = len(y_true)
    present = [c for c in categories if np.any(y_true == c)]
    correct = int(np.sum(y_true == y_pred))
    conf = [[int(np.sum((y_true == a) & (y_pred == b))) for b in categories] for a in categories]
    per_cat = []
    for c in categories:
        n_true = int(np.sum(y_true == c))
        n_pred = int(np.sum(y_pred == c))
        tp = int(np.sum((y_true == c) & (y_pred == c)))
        rec = tp / n_true if n_true else None
        prec = tp / n_pred if n_pred else None
        f1 = 2 * rec * prec / (rec + prec) if rec and prec else (0.0 if n_true else None)
        per_cat.append({
            "category": c, "n_test": n_true, "n_predicted": n_pred, "correct": tp,
            "recall": rec, "recall_ci": wilson(tp, n_true),
            "precision": prec, "precision_ci": wilson(tp, n_pred),
            "f1": f1,
        })
    bal = _balanced(y_true, y_pred, present)
    kap = _kappa(y_true, y_pred, categories)
    mf1 = _macro_f1(y_true, y_pred, present)
    bal_ci = kap_ci = mf1_ci = (None, None)
    if n >= 5:
        rng = np.random.default_rng(seed)
        bals, kaps, mf1s = [], [], []
        for _ in range(BOOTSTRAP):
            idx = rng.integers(0, n, n)
            t, p = y_true[idx], y_pred[idx]
            resampled = [c for c in present if np.any(t == c)]
            b = _balanced(t, p, resampled)
            if b is not None:
                bals.append(b)
            k = _kappa(t, p, categories)
            if k is not None:
                kaps.append(k)
            f = _macro_f1(t, p, resampled)
            if f is not None:
                mf1s.append(f)
        bal_ci = (float(np.percentile(bals, 2.5)), float(np.percentile(bals, 97.5)))
        kap_ci = (float(np.percentile(kaps, 2.5)), float(np.percentile(kaps, 97.5)))
        mf1_ci = (float(np.percentile(mf1s, 2.5)), float(np.percentile(mf1s, 97.5)))
    return {
        "n": n,
        "accuracy": correct / n if n else None, "accuracy_ci": wilson(correct, n),
        "balanced_accuracy": bal, "balanced_accuracy_ci": bal_ci,
        "kappa": kap, "kappa_ci": kap_ci,
        "macro_f1": mf1, "macro_f1_ci": mf1_ci,
        "per_category": per_cat,
        "confusion": conf, "categories": list(categories),
        "categories_tested": present,
    }


def _pct(v):
    return "–" if v is None else f"{100 * v:.1f} %"


def methods_text(report, names):
    """A ready-to-adapt paragraph describing the test and its result."""
    m = report["metrics"]
    cats = ", ".join(names.get(c, c) for c in m["categories_tested"])
    lo, hi = m["balanced_accuracy_ci"]
    alo, ahi = m["accuracy_ci"]
    klo, khi = m["kappa_ci"]
    rng = report.get("labels_per_crop_range")
    if rng:
        per = (f"{rng[0]}" if rng[0] == rng[1] else f"{rng[0]}–{rng[1]}") + " per category and image"
    else:
        per = f"{report['labels_per_crop']} recommended per category and image"
    return (
        f"Classification performance was assessed on an independent test set: {report['n_images']} images "
        f"({report['n_images_per_group']} per clone) that were not used for training were randomly selected, and "
        f"{m['n']} nuclei ({per}; categories: {cats}) were annotated "
        f"in crops of these images without displaying the classifier's predictions. Balanced accuracy (mean recall "
        f"over categories) was {_pct(m['balanced_accuracy'])} (95 % CI {_pct(lo)}–{_pct(hi)}, bootstrap), overall accuracy "
        f"{_pct(m['accuracy'])} (95 % CI {_pct(alo)}–{_pct(ahi)}, Wilson), Cohen's κ "
        f"{m['kappa']:.2f} (95 % CI {klo:.2f}–{khi:.2f}) and the macro-averaged F1 score "
        f"{m['macro_f1']:.2f}. The random forest ({report['n_trees']} trees, "
        f"{report['n_features']} features per nucleus) was trained on {report['n_training_labels']} labeled nuclei from "
        f"{report['n_training_crops']} training crops; its leave-one-crop-out accuracy was "
        f"{_pct(report['cv_accuracy'])}."
        if m["kappa"] is not None and klo is not None else
        f"Classification performance was assessed on {m['n']} annotated nuclei from {report['n_images']} independent "
        f"test images: overall accuracy {_pct(m['accuracy'])} (95 % CI {_pct(alo)}–{_pct(ahi)})."
    )
