"""Run the whole V2 pipeline headlessly and compare it with V1 (ilastik).

Labels are not clicked by a person here: they are sampled from V1's ilastik
predictions (the '<image>_Object Predictions.h5' maps next to the images),
so this measures how closely V2 reproduces V1, not accuracy against a
ground truth.

    python scripts/validation/compare_with_v1.py --images img_test_pipeline

Writes a report (JSON + Markdown) in the project's results folder.
"""

import argparse
import json
import os
import shutil
import sys
import time

import h5py
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from nucleiquant import batch, io  # noqa: E402
from nucleiquant.api import Session  # noqa: E402
from nucleiquant.jobs import JobManager  # noqa: E402

# ilastik class index in the V1 prediction maps -> V2 category
V1_CLASSES = {1: "S", 2: "N", 3: "T", 4: "Dead", 5: "Unstained"}


def wait(session, job, label):
    t0 = time.time()
    last = None
    while True:
        j = session.jobs.get(job["id"])
        if j["message"] != last:
            print(f"  [{label} {j['progress'] * 100:5.1f}%] {j['message']}", flush=True)
            last = j["message"]
        if j["status"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.5)
    if j["status"] != "done":
        raise SystemExit(f"{label} failed: {j['error']}")
    print(f"  {label} finished in {time.time() - t0:.1f} s")
    return j["result"]


def v1_class_per_label(v1_map, labels):
    """Majority V1 class inside each V2 nucleus (0 = none)."""
    lab = labels.astype(np.int64).ravel()
    cls = v1_map.astype(np.int64).ravel()
    m = (lab > 0) & (cls > 0)
    votes = np.bincount(lab[m] * 8 + cls[m], minlength=(labels.max() + 1) * 8).reshape(-1, 8)
    return votes.argmax(axis=1) * (votes.max(axis=1) > 0)


def load_v1(images_dir, image):
    path = os.path.join(images_dir, os.path.splitext(image)[0] + "_Object Predictions.h5")
    if not os.path.exists(path):
        return None
    with h5py.File(path, "r") as f:
        return f["exported_data"][..., 0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default="img_test_pipeline")
    ap.add_argument("--name", default="v1-comparison")
    ap.add_argument("--per-category", type=int, default=55)
    ap.add_argument("--fresh", action="store_true", help="Delete an existing project with this name first")
    args = ap.parse_args()
    images_dir = os.path.abspath(args.images)
    project_dir = os.path.join(images_dir, "NucleiQuant_projects", args.name)
    if args.fresh and os.path.exists(project_dir):
        shutil.rmtree(project_dir)

    s = Session(JobManager())
    s.detect_device()
    print("Device:", s.system()["device"])
    if os.path.exists(os.path.join(project_dir, "project.json")):
        s.open_project(project_dir)
    else:
        s.create_project(images_dir, args.name)
        s.update_project({
            "channels": [{"name": "DAPI"}, {"name": "488"}, {"name": "555"}, {"name": "647"}],
            "genotypes": {"Pa": "WT/WT"},
        })
        for name in ("S", "N", "T"):
            s.add_category(name)
    p = s.project
    cat_id = {c["name"]: c["id"] for c in p.categories}
    report = {"device": s.system()["device"], "timings": {}}

    t = time.time()
    wait(s, s.start_survey(), "survey")
    report["timings"]["survey_s"] = round(time.time() - t, 1)
    print("  training images:", [(x["image"][-10:], x["role"]) for x in p.data["selection"]])

    t = time.time()
    wait(s, s.start_crops(), "crops")
    report["timings"]["crops_s"] = round(time.time() - t, 1)

    # Seed labels from V1 predictions, spread over the crops
    rng = np.random.default_rng(0)
    s.annotations = {}
    pools = {}
    for c in p.data["crops"]:
        v1 = load_v1(images_dir, c["image"])
        if v1 is None:
            continue
        v1c = v1[c["y"]:c["y"] + c["h"], c["x"]:c["x"] + c["w"]]
        labels = io.read_labels(os.path.join(p.dir, "training", "labels", c["id"] + "_labels"))
        cls = v1_class_per_label(v1c, labels)
        obj = s.crop_objects(c["id"])
        for lab, edge in zip(obj["labels"], obj["edge"]):
            k = int(cls[lab]) if lab < len(cls) else 0
            if not edge and k in V1_CLASSES and V1_CLASSES[k] in cat_id:
                pools.setdefault(V1_CLASSES[k], []).append((c["id"], lab))
    for name, items in pools.items():
        take = rng.permutation(len(items))[: args.per_category]
        for i in take:
            crop_id, lab = items[i]
            s.set_label(crop_id, lab, cat_id[name])
    report["labels"] = s.label_counts()["per_category"]
    print("  labels:", report["labels"])

    t = time.time()
    info = wait(s, s.start_training(), "training")
    report["timings"]["training_s"] = round(time.time() - t, 1)
    cv = info["cross_validation"]
    report["cross_validation"] = {k: cv[k] for k in ("scheme", "n", "accuracy", "balanced_accuracy", "per_fold", "recall")}
    report["top_features"] = info["top_features"][:10]
    print(f"  held-out accuracy {cv['accuracy']:.3f} (balanced {cv['balanced_accuracy']:.3f}, {cv['scheme']})")

    s.validate_classifier()
    t = time.time()
    res = wait(s, s.start_batch(), "batch")
    report["timings"]["batch_s"] = round(time.time() - t, 1)
    report["excel"] = res["excel"]

    # Compare with V1, image by image
    names = {v: k for k, v in cat_id.items()}
    per_image = []
    agree_all = total_all = 0
    conf = {}
    for summary in batch.load_summaries(p, [i["image"] for i in s.files() if "fields" in i]):
        image = summary["image"]
        v1 = load_v1(images_dir, image)
        if v1 is None:
            continue
        paths = batch.result_paths(p, image)
        labels = io.read_labels(paths["labels"])
        z = np.load(paths["pred"])
        v1cls = v1_class_per_label(v1, labels)
        v2 = {int(l): p.categories[int(k)]["name"] for l, k in zip(z["labels"], z["category"])}
        agree = total = 0
        for lab, name in v2.items():
            k = int(v1cls[lab]) if lab < len(v1cls) else 0
            if k == 0:
                continue
            v1name = V1_CLASSES[k]
            conf[(v1name, name)] = conf.get((v1name, name), 0) + 1
            total += 1
            agree += v1name == name
        agree_all += agree
        total_all += total
        v1_counts = {}
        for k in v1cls[1:]:
            if k:
                v1_counts[V1_CLASSES[int(k)]] = v1_counts.get(V1_CLASSES[int(k)], 0) + 1
        v2_counts = {names[c]: n for c, n in summary["counts"].items() if c in names}
        per_image.append({"image": image, "agreement": agree / max(total, 1), "v1": v1_counts, "v2": v2_counts,
                          "seconds": summary.get("seconds")})
        print(f"  {image}: per-nucleus agreement {agree / max(total, 1):.3f}")

    cats = ["Dead", "Unstained", "S", "N", "T"]
    corr = {}
    for c in cats:
        a = np.array([r["v1"].get(c, 0) for r in per_image], float)
        b = np.array([r["v2"].get(c, 0) for r in per_image], float)
        if a.std() > 0 and b.std() > 0:
            corr[c] = float(np.corrcoef(a, b)[0, 1])
    # Cohen's kappa over all nuclei
    labels_ = sorted({k for pair in conf for k in pair})
    n = sum(conf.values())
    po = sum(v for (a, b), v in conf.items() if a == b) / n
    pe = sum(sum(v for (a, _), v in conf.items() if a == k) * sum(v for (_, b), v in conf.items() if b == k) for k in labels_) / n ** 2
    report["agreement_per_nucleus"] = agree_all / max(total_all, 1)
    report["cohen_kappa"] = (po - pe) / (1 - pe)
    report["count_correlation_per_image"] = corr
    report["confusion_v1_rows_v2_cols"] = {f"{a} -> {b}": v for (a, b), v in sorted(conf.items())}
    report["per_image"] = per_image
    out = os.path.join(p.dir, "results", "v1_comparison.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=1)
    print(f"\nPer-nucleus agreement with V1: {report['agreement_per_nucleus']:.3f}, Cohen's kappa {report['cohen_kappa']:.3f}")
    print("Per-image count correlation:", {k: round(v, 3) for k, v in corr.items()})
    print("Report:", out)


if __name__ == "__main__":
    main()
