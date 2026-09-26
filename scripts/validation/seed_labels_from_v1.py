"""Label crops of a running NucleiQuant app with classes taken from V1 (ilastik).

Used by the automated UI walkthrough (tests/e2e) to get realistic labels
without clicking thousands of times. Talks to the app over HTTP, so the
app's own label logic is used.

    python scripts/validation/seed_labels_from_v1.py --url http://localhost:8765 --per-category 55
"""

import argparse
import json
import os
import sys
import urllib.request

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from nucleiquant import io  # noqa: E402
from compare_with_v1 import V1_CLASSES, load_v1, v1_class_per_label  # noqa: E402


def call(url, path, body=None):
    req = urllib.request.Request(url + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8765")
    ap.add_argument("--per-category", type=int, default=55)
    args = ap.parse_args()
    st = call(args.url, "/api/state")
    p = st["project"]
    images_dir = os.path.normpath(os.path.join(p["dir"], "..", ".."))
    cat_id = {c["name"]: c["id"] for c in p["categories"]}
    pools = {}
    for c in p["crops"]:
        v1 = load_v1(images_dir, c["image"])
        if v1 is None:
            continue
        v1c = v1[c["y"]:c["y"] + c["h"], c["x"]:c["x"] + c["w"]]
        labels = io.read_labels(os.path.join(p["dir"], "training", "labels", c["id"] + "_labels"))
        cls = v1_class_per_label(v1c, labels)
        obj = call(args.url, f"/api/crops/{c['id']}/objects")
        for lab, edge in zip(obj["labels"], obj["edge"]):
            k = int(cls[lab]) if lab < len(cls) else 0
            if not edge and k in V1_CLASSES and V1_CLASSES[k] in cat_id:
                pools.setdefault(V1_CLASSES[k], []).append((c["id"], lab))
    rng = np.random.default_rng(1)
    n = 0
    for name, items in pools.items():
        for i in rng.permutation(len(items))[: args.per_category]:
            crop_id, lab = items[i]
            call(args.url, "/api/labels", {"crop_id": crop_id, "label": int(lab), "category_id": cat_id[name]})
            n += 1
    print(f"Seeded {n} labels:", call(args.url, "/api/state")["labels"]["per_category"])


if __name__ == "__main__":
    main()
