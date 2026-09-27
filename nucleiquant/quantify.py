"""Counts, proportions, statistics, Excel workbook and plots.

Proportions are always relative to a *reference*: the set of categories that makes
100 %. Three presets exist (all nuclei, living cells = all but Dead, stained cells =
all but Dead and Unstained) and the user can save others from the Results screen.
"""

import datetime
import json
import os
import platform
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import __version__, stats  # noqa: E402

__all__ = ["build_tables", "write_outputs", "experiment_name", "references", "results_view"]

# Filename fields not used to identify an organoid (they may differ between slices)
NON_ORGANOID_FIELDS = ("slice", "objective", "imaging")

# id, name, categories left out of the 100 %
PRESETS = (
    ("all", "all nuclei", ()),
    ("living", "living cells", ("dead",)),
    ("stained", "stained cells", ("dead", "unstained")),
)


def _title(field):
    return field[:1].upper() + field[1:]


def experiment_name(per_image, fields):
    """Diff_Day_Immuno style name from fields that are constant across the run."""
    parts = []
    for f in ("diff", "day", "immuno"):
        col = _title(f)
        if f in fields and col in per_image and per_image[col].nunique() == 1:
            parts.append(str(per_image[col].iloc[0]))
    return "_".join(parts) or "NucleiQuant"


# ---- references ------------------------------------------------------------------------

def references(project):
    """Presets plus the user's saved references, restricted to existing categories."""
    ids = [c["id"] for c in project.categories]
    has_user_categories = any(not c.get("builtin") for c in project.categories)
    out = []
    for rid, name, excluded in PRESETS:
        members = [c for c in ids if c not in excluded]
        if rid == "stained" and not has_user_categories:
            continue
        if members:
            out.append({"id": rid, "name": name, "categories": members, "preset": True})
    for r in project.data.get("references", []):
        members = [c for c in r["categories"] if c in ids]
        if members:
            out.append({"id": r["id"], "name": r["name"], "categories": members, "preset": False})
    return out


def find_reference(project, category_ids):
    """The preset/saved reference with exactly these categories, or None."""
    wanted = set(category_ids)
    for r in references(project):
        if set(r["categories"]) == wanted:
            return r
    return None


def default_reference_name(project, category_ids):
    names = {c["id"]: c["name"] for c in project.categories}
    return " + ".join(names[c] for c in category_ids if c in names)


# ---- tables ------------------------------------------------------------------------------

def build_tables(project, summaries):
    """Per-image / per-organoid count tables from per-image summaries.

    summaries: list of dicts {"image", "counts": {category_id: n}}.
    """
    cats = project.categories
    fields = list(project.pattern().groupindex)
    rows = []
    for s in summaries:
        try:
            meta = project.parse(s["image"])
        except ValueError:
            meta = {}
        row = {"Image_name": s["image"]}
        for f in fields:
            row[_title(f)] = meta.get(f, "")
            if f == "clone":
                row["Genotype"] = project.data["genotypes"].get(meta.get("clone", ""), "")
        total = 0
        for c in cats:
            n = int(s["counts"].get(c["id"], 0))
            row[c["name"]] = n
            total += n
        row["Total"] = total
        row["Living"] = total - int(s["counts"].get("dead", 0))
        rows.append(row)
    per_image = pd.DataFrame(rows)
    cat_cols = [c["name"] for c in cats]
    info = {"fields": fields, "category_columns": cat_cols, "warnings": []}

    if "organoid" in fields and len(per_image):
        key = [_title(f) for f in fields if f not in NON_ORGANOID_FIELDS]
        if "clone" in fields:
            key.insert(key.index("Clone") + 1, "Genotype")
        slice_col = "Slice" if "slice" in fields else None
        agg = {c: "sum" for c in cat_cols + ["Total", "Living"]}
        per_org = per_image.groupby(key, dropna=False, sort=True).agg(agg).reset_index()
        n_sl = per_image.groupby(key, dropna=False, sort=True)[slice_col or "Image_name"].nunique().reset_index(name="Slices")
        per_org = per_org.merge(n_sl, on=key)
        info["unit"] = "organoid"
    else:
        key = ["Image_name"] + [_title(f) for f in fields]
        per_org = per_image.copy()
        per_org["Slices"] = 1
        info["unit"] = "image"
        info["warnings"].append("No 'organoid' field in the file names: each image is treated as one sample.")
    info["key"] = key
    min_slices = int(project.settings["min_slices"])
    if info["unit"] == "organoid":
        per_org["Kept"] = per_org["Slices"] >= min_slices
    else:
        per_org["Kept"] = True
    curated = per_org[per_org["Kept"]].drop(columns="Kept").copy()
    return {"per_image": per_image, "per_organoid": per_org.drop(columns="Kept"), "curated": curated,
            "kept": per_org["Kept"].to_numpy(), "info": info}


def proportions(tab, project, ref, key):
    """Each category of `ref` as % of the reference's total, one row per unit."""
    names = {c["id"]: c["name"] for c in project.categories}
    cols = [names[c] for c in ref["categories"]]
    denom = tab[cols].sum(axis=1) if cols else pd.Series(0, index=tab.index)
    out = pd.DataFrame(index=tab.index)
    out[f"Cells ({ref['name']})"] = denom
    with np.errstate(divide="ignore", invalid="ignore"):
        for c in ref["categories"]:
            out[f"{names[c]} (% {ref['name']})"] = 100 * tab[names[c]] / denom.where(denom > 0)
    return out


def _group_col(project, table):
    col = "Genotype" if project.settings.get("group_by", "genotype") == "genotype" else "Clone"
    if col not in table or (table[col] == "").all():
        col = "Clone" if "Clone" in table else None
    return col


def _ref_stats(project, curated, ref, key, group_col):
    if group_col is None:
        return [], ["No clone/genotype field in the file names: no groups to compare."]
    props = pd.concat([curated[key], proportions(curated, project, ref, key)], axis=1)
    cols = [c for c in props.columns if c.endswith(f"(% {ref['name']})")]
    rows, warnings = stats.compare_groups(props, group_col, cols, f"% of {ref['name']}")
    for r in rows:
        r["Category"] = r["Category"][: -len(f" (% {ref['name']})")]
    return rows, warnings


def _unit_label(row, table):
    label = str(row.get("Organoid", row.get("Image_name", "")))
    if "Clone" in row and table["Clone"].nunique() > 1:
        label = f"{row['Clone']} · {label}"
    return label


def _num(v):
    try:
        v = float(v)
        return None if not np.isfinite(v) else round(v, 3)
    except (TypeError, ValueError):
        return None


def results_view(project, summaries, category_ids):
    """Bars, group means and statistics for one reference (the Results chart)."""
    ids = [c["id"] for c in project.categories]
    category_ids = [c for c in ids if c in set(category_ids)]
    ref = find_reference(project, category_ids) or {
        "id": None, "name": default_reference_name(project, category_ids),
        "categories": category_ids, "preset": False}
    tables = build_tables(project, summaries)
    info = tables["info"]
    key = info["key"]
    per_org = tables["per_organoid"]
    group_col = _group_col(project, per_org)
    names = {c["id"]: c["name"] for c in project.categories}
    props = proportions(per_org, project, ref, key)
    bars = []
    for (i, row), kept in zip(per_org.iterrows(), tables["kept"]):
        bars.append({
            "label": _unit_label(row, per_org),
            "group": str(row.get(group_col, "")) if group_col else "",
            "slices": int(row["Slices"]),
            "excluded": not bool(kept),
            "n": int(props.loc[i, f"Cells ({ref['name']})"]),
            "values": {c: _num(props.loc[i, f"{names[c]} (% {ref['name']})"]) for c in category_ids},
            "counts": {c: int(row[names[c]]) for c in category_ids},
        })
    group_bars = []
    if group_col:
        for g in sorted({b["group"] for b in bars if b["group"]}):
            members = [b for b in bars if b["group"] == g and not b["excluded"]]
            vals, sds = {}, {}
            for c in category_ids:
                v = np.array([b["values"][c] for b in members if b["values"][c] is not None], float)
                vals[c] = _num(v.mean()) if len(v) else None
                sds[c] = _num(v.std(ddof=1)) if len(v) > 1 else None
            group_bars.append({"label": g, "n_units": len(members), "values": vals, "sd": sds,
                               "n": int(sum(b["n"] for b in members))})
    rows, warnings = _ref_stats(project, tables["curated"], ref, key, group_col) if category_ids else ([], [])
    return {
        "reference": {"id": ref["id"], "name": ref["name"], "categories": category_ids,
                      "preset": ref.get("preset", False), "saved": ref["id"] is not None},
        "unit": info["unit"], "group_col": group_col, "min_slices": int(project.settings["min_slices"]),
        "bars": bars, "group_bars": group_bars,
        "stats": json.loads(pd.DataFrame(rows).to_json(orient="records")) if rows else [],
        "warnings": warnings + info["warnings"],
    }


# ---- workbook and plots ----------------------------------------------------------------------

def _autosize(ws):
    from openpyxl.styles import Font, PatternFill
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="EDEEF0")
    for col in ws.columns:
        width = max(len(str(c.value)) if c.value is not None else 0 for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
    ws.freeze_panes = "A2"


def _write_test_sheet(xw, project, report):
    """Independent test set: metrics with 95 % intervals, per category, per image, confusion, history."""
    names = {c["id"]: c["name"] for c in project.categories}
    m = report["metrics"]

    def ci(pair):
        return [None if v is None else round(v, 4) for v in pair]

    summary = pd.DataFrame([
        ["Balanced accuracy (mean recall)", m["balanced_accuracy"], *ci(m["balanced_accuracy_ci"]), "bootstrap over cells"],
        ["Accuracy on the test cells", m["accuracy"], *ci(m["accuracy_ci"]), "Wilson"],
        ["Cohen's kappa", m["kappa"], *ci(m["kappa_ci"]), "bootstrap over cells"],
        ["Test cells", m["n"], None, None, ""],
        ["Test images (not used for training)", report["n_images"], None, None, ""],
        ["Evaluated on", report["date"], None, None, f"classifier {report['classifier_hash']}"],
        ["Classifier changed since this test", "yes — evaluate again" if report.get("stale") else "no", None, None, ""],
    ], columns=["Measure", "Value", "95 % CI low", "95 % CI high", "Method"])
    per_cat = pd.DataFrame([{
        "Category": names.get(r["category"], r["category"]), "Test cells": r["n_test"], "Predicted": r["n_predicted"],
        "Correct": r["correct"], "Recall": r["recall"], "Recall 95 % CI": _fmt_ci(r["recall_ci"]),
        "Precision": r["precision"], "Precision 95 % CI": _fmt_ci(r["precision_ci"]), "F1": r["f1"],
    } for r in m["per_category"]])
    per_img = pd.DataFrame([{"Image": r["image"], "Test cells": r["n"], "Correct": r["correct"],
                             "Accuracy": r["accuracy"], "95 % CI": _fmt_ci(r["accuracy_ci"])} for r in report["per_crop"]])
    conf = pd.DataFrame(m["confusion"], columns=[f"predicted {names.get(c, c)}" for c in m["categories"]])
    conf.insert(0, "true category", [names.get(c, c) for c in m["categories"]])
    hist = pd.DataFrame(report.get("history", []))
    text = pd.DataFrame({"Methods (adapt before use)": [report.get("methods_text", "")]})
    row = 0
    for title, table in (("Summary", summary), ("Per category", per_cat), ("Per test image", per_img),
                         ("Confusion matrix (rows: your label, columns: classifier)", conf),
                         ("Every evaluation", hist), ("Methods text", text)):
        pd.DataFrame({title: []}).to_excel(xw, sheet_name="test_set", index=False, startrow=row)
        table.to_excel(xw, sheet_name="test_set", index=False, startrow=row + 1)
        row += len(table) + 4


def _fmt_ci(pair):
    lo, hi = pair
    return "" if lo is None else f"{100 * lo:.1f}–{100 * hi:.1f} %"


def write_outputs(project, summaries, classifier_info=None, test_report=None):
    """Write the Excel workbook and plots. Returns a JSON-able summary for the app."""
    tables = build_tables(project, summaries)
    info = tables["info"]
    key = info["key"]
    curated = tables["curated"]
    group_col = _group_col(project, tables["per_organoid"])
    refs = references(project)
    name = experiment_name(tables["per_image"], info["fields"])
    out_dir = os.path.join(project.dir, "results")
    os.makedirs(out_dir, exist_ok=True)
    xlsx = os.path.join(out_dir, f"{name}_counts.xlsx")

    prop_sheet = curated[key + ["Slices", "Total", "Living"]].copy()
    stat_rows, stat_warnings = [], []
    for ref in refs:
        prop_sheet = pd.concat([prop_sheet, proportions(curated, project, ref, key)], axis=1)
        rows, warnings = _ref_stats(project, curated, ref, key, group_col)
        stat_rows += rows
        stat_warnings += [w for w in warnings if w not in stat_warnings]
    stats_df = pd.DataFrame(stat_rows)

    cats = project.categories
    classifier_rows = []
    if classifier_info:
        cv = classifier_info.get("cross_validation", {})
        classifier_rows += [
            ("Trained", classifier_info.get("trained")),
            ("Labeled nuclei", classifier_info.get("n_labels")),
            ("Features per nucleus", classifier_info.get("n_features")),
            ("Trees", classifier_info.get("n_trees")),
            ("Validation", cv.get("scheme")),
            ("Accuracy on unseen crops", cv.get("accuracy")),
            ("Balanced accuracy", cv.get("balanced_accuracy")),
        ]
        for c in cats:
            n = classifier_info.get("labels_per_category", {}).get(c["id"], 0)
            rec = cv.get("recall", {}).get(c["id"])
            classifier_rows.append((f"{c['name']}: labels / recall", f"{n} / {rec:.2f}" if rec is not None else f"{n} / -"))
        for tf in classifier_info.get("top_features", [])[:15]:
            classifier_rows.append((f"Important feature: {tf['feature']}", round(tf["importance"], 4)))
    s = project.settings
    settings_rows = [
        ("NucleiQuant version", __version__),
        ("Date", datetime.datetime.now().astimezone().isoformat(timespec="seconds")),
        ("Images folder", project.images_dir),
        ("File name pattern", project.data["filename_template"]),
        ("Channels", ", ".join(f"{i + 1}: {c['name']}" for i, c in enumerate(project.data["channels"]))),
        ("Nuclear channel", project.data["channels"][project.data["nuclear_channel"]]["name"]),
        ("Segmentation", f"stardist_haug2, normalisation percentiles {s['norm_low']}-{s['norm_high']}"),
        ("Neighbourhood ring (px)", s["ring_radius"]),
        ("Perinuclear ring (px)", s["perinuclear_radius"]),
        ("Minimum slices per organoid", s["min_slices"]),
        ("Genotypes", json.dumps(project.data["genotypes"])),
        ("Python", platform.python_version()),
    ]
    names = {c["id"]: c["name"] for c in cats}
    for ref in refs:
        settings_rows.append((f"100 % = {ref['name']}", " + ".join(names[c] for c in ref["categories"])))

    with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
        tables["per_image"].to_excel(xw, sheet_name="per_image", index=False)
        tables["per_organoid"].to_excel(xw, sheet_name="per_organoid", index=False)
        curated.to_excel(xw, sheet_name="per_organoid_curated", index=False)
        prop_sheet.round(3).to_excel(xw, sheet_name="proportions", index=False)
        if len(stats_df):
            stats_df.to_excel(xw, sheet_name="statistics", index=False)
        else:
            pd.DataFrame({"Note": stat_warnings or ["No statistics"]}).to_excel(xw, sheet_name="statistics", index=False)
        pd.DataFrame(classifier_rows, columns=["Item", "Value"]).to_excel(xw, sheet_name="classifier", index=False)
        if test_report:
            _write_test_sheet(xw, project, test_report)
        pd.DataFrame(settings_rows, columns=["Setting", "Value"]).to_excel(xw, sheet_name="settings", index=False)
        for ws in xw.book.worksheets:
            _autosize(ws)

    plots = []
    for ref in refs:
        plots += _plots(project, curated, ref, key, group_col, out_dir)

    per_image = tables["per_image"]
    groups = sorted({str(g) for g in tables["per_organoid"][group_col].unique() if str(g)}) if group_col else []
    return {
        "excel": xlsx,
        "excel_name": os.path.basename(xlsx),
        "plots": plots,
        "n_images": int(len(per_image)),
        "n_nuclei": int(per_image["Total"].sum()) if len(per_image) else 0,
        "n_living": int(per_image["Living"].sum()) if len(per_image) else 0,
        "unit": info["unit"],
        "n_units": int(len(tables["per_organoid"])),
        "n_units_kept": int(len(curated)),
        "min_slices": int(s["min_slices"]),
        "group_col": group_col,
        "groups": groups,
        "references": refs,
        "per_image": json.loads(per_image.to_json(orient="records")),
        "stat_warnings": stat_warnings + info["warnings"],
    }


def _safe(name):
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower() or "reference"


def _plots(project, curated, ref, key, group_col, out_dir):
    """Vertical stacked bars per unit, and per-group box plots, for one reference."""
    plot_dir = os.path.join(out_dir, "plots")
    os.makedirs(plot_dir, exist_ok=True)
    names = {c["id"]: c["name"] for c in project.categories}
    colors = {c["id"]: c["color"] for c in project.categories}
    props = pd.concat([curated[key], proportions(curated, project, ref, key)], axis=1)
    files = []
    if not len(props):
        return files
    tag = _safe(ref["name"])
    label_col = "Organoid" if "Organoid" in props else "Image_name"
    order = props.sort_values([group_col, label_col] if group_col else [label_col])
    fig, ax = plt.subplots(figsize=(max(5, 0.5 * len(order) + 2.5), 4.2))
    bottom = np.zeros(len(order))
    x = np.arange(len(order))
    for c in ref["categories"]:
        v = order[f"{names[c]} (% {ref['name']})"].fillna(0).to_numpy()
        ax.bar(x, v, bottom=bottom, color=colors[c], edgecolor="white", linewidth=0.5, label=names[c])
        bottom += v
    labels = [f"{r[group_col]}\n{r[label_col]}" if group_col else str(r[label_col]) for _, r in order.iterrows()]
    ax.set_xticks(x, labels, fontsize=8)
    ax.set_ylabel(f"% of {ref['name']}")
    ax.set_ylim(0, 100)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, bbox_to_anchor=(1.01, 1), loc="upper left", fontsize=8)
    fig.tight_layout()
    for ext in ("png", "svg"):
        p = os.path.join(plot_dir, f"proportions_{tag}.{ext}")
        fig.savefig(p, dpi=200)
        files.append(p)
    plt.close(fig)

    if group_col and props[group_col].nunique() >= 2:
        groups = sorted(props[group_col].unique())
        cats = ref["categories"]
        fig, axes = plt.subplots(1, len(cats), figsize=(2.4 * len(cats) + 1, 3.6), squeeze=False)
        rng = np.random.default_rng(0)
        for ax, c in zip(axes[0], cats):
            col = f"{names[c]} (% {ref['name']})"
            data = [props.loc[props[group_col] == g, col].dropna().to_numpy() for g in groups]
            ax.boxplot(data, widths=0.5, showfliers=False, medianprops={"color": "black"})
            for i, d in enumerate(data):
                ax.scatter(i + 1 + rng.uniform(-0.12, 0.12, len(d)), d, s=16, color=colors[c], edgecolor="black", linewidth=0.4, zorder=3)
            ax.set_xticks(range(1, len(groups) + 1), groups, fontsize=8)
            ax.set_title(names[c], fontsize=10)
            ax.spines[["top", "right"]].set_visible(False)
        axes[0][0].set_ylabel(f"% of {ref['name']}")
        fig.tight_layout()
        for ext in ("png", "svg"):
            p = os.path.join(plot_dir, f"groups_{tag}.{ext}")
            fig.savefig(p, dpi=200)
            files.append(p)
        plt.close(fig)
    return files
