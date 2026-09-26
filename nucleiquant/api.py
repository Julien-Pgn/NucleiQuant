"""Every step of NucleiQuant as plain Python functions on a Session.

The web app (app/server.py), the command line (__main__.py) and any future
integration (e.g. an MCP server) call these functions; none of them
contain pipeline logic of their own.
"""

import csv
import json
import os
import shutil
import threading

import numpy as np
import pandas as pd

from . import batch, crops, features, io, metadata, quantify, segmentation, survey
from .classifier import Classifier
from .project import CATEGORY_COLORS, CHANNEL_COLORS, Project, recent_projects

__all__ = ["Session", "ApiError"]


class ApiError(Exception):
    """An error meant to be shown to the user as is."""


# ---- paths shown to users ------------------------------------------------------

def _roots():
    env = os.environ.get("NQ_ROOTS")
    if env:
        roots = [p for p in env.split(os.pathsep) if p]
    else:
        roots = [p for p in ("/workspace", "/data", "/media", "/mnt", "/Volumes", os.path.expanduser("~")) if os.path.isdir(p)]
    return [os.path.abspath(r) for r in roots if os.path.isdir(r)]


def _path_map():
    """container prefix -> prefix shown to the user (NQ_PATH_MAP='a=b;c=d')."""
    out = []
    for item in os.environ.get("NQ_PATH_MAP", "").split(";"):
        if "=" in item:
            a, b = item.split("=", 1)
            out.append((os.path.abspath(a), b))
    home = os.environ.get("NQ_HOME")
    if home:
        out.append((os.path.abspath(home), "~"))
    return sorted(out, key=lambda t: -len(t[0]))


def display_path(path):
    path = os.path.abspath(path)
    for prefix, shown in _path_map():
        if path == prefix or path.startswith(prefix + os.sep):
            rest = path[len(prefix):].lstrip(os.sep)
            if shown.endswith(("\\", ":")) or "\\" in shown:
                return shown.rstrip("\\") + ("\\" + rest.replace("/", "\\") if rest else "")
            return shown + ("/" + rest if rest else "")
    return path


def _inside_roots(path):
    path = os.path.abspath(path)
    return any(path == r or path.startswith(r.rstrip(os.sep) + os.sep) for r in _roots())


class Session:
    """One open project plus the app's in-memory caches and background jobs."""

    def __init__(self, jobs):
        self.jobs = jobs
        self.project = None
        self.annotations = {}
        self.classifier = None
        self.predictions = {}
        self._features = {}
        self._survey = None
        self.lock = threading.RLock()
        self._device = None

    # ---- system ------------------------------------------------------------------

    def detect_device(self):
        self._device = segmentation.device_info()

    def system(self):
        from . import __version__
        return {"version": __version__, "device": self._device or {"device": "detecting", "name": ""}}

    def browse(self, path=None):
        roots = _roots()
        if not path:
            return {"path": None, "display": "", "parent": None, "n_tiffs": 0,
                    "dirs": [{"name": display_path(r), "path": r} for r in roots]}
        path = os.path.abspath(path)
        if not _inside_roots(path) or not os.path.isdir(path):
            raise ApiError("This folder can't be opened.")
        dirs = []
        try:
            for e in sorted(os.scandir(path), key=lambda e: e.name.lower()):
                if e.is_dir() and not e.name.startswith(".") and e.name != "__pycache__":
                    dirs.append({"name": e.name, "path": e.path,
                                 "is_project": os.path.exists(os.path.join(e.path, "project.json"))})
        except PermissionError:
            raise ApiError("No permission to read this folder.")
        parent = os.path.dirname(path)
        return {
            "path": path, "display": display_path(path),
            "parent": parent if _inside_roots(parent) and parent != path else None,
            "n_tiffs": len(io.list_tiffs(path)), "dirs": dirs,
            "is_project": os.path.exists(os.path.join(path, "project.json")),
        }

    def recent(self):
        out = []
        for d in recent_projects():
            try:
                with open(os.path.join(d, "project.json")) as f:
                    data = json.load(f)
                out.append({"path": d, "name": data.get("name"), "modified": data.get("modified"),
                            "images": display_path(os.path.normpath(os.path.join(d, data["images_dir"]))),
                            "stage": _stage(data)})
            except (OSError, ValueError, KeyError):
                continue
        return out

    # ---- project -----------------------------------------------------------------

    def _require(self):
        if self.project is None:
            raise ApiError("No project is open.")
        return self.project

    def suggest_name(self, images_dir):
        files = io.list_tiffs(images_dir) if os.path.isdir(images_dir) else []
        for f in files:
            try:
                fields = metadata.parse_filename(f)
                return "_".join(fields[k] for k in ("diff", "day", "immuno"))
            except ValueError:
                continue
        return os.path.basename(os.path.abspath(images_dir)) or "project"

    def create_project(self, images_dir, name):
        images_dir = os.path.abspath(images_dir)
        if not _inside_roots(images_dir) or not os.path.isdir(images_dir):
            raise ApiError("This folder can't be opened.")
        files = io.list_tiffs(images_dir)
        if not files:
            raise ApiError("No TIFF images in this folder.")
        name = "".join(ch for ch in name.strip() if ch.isalnum() or ch in "-_ .").strip() or "project"
        info = io.image_info(os.path.join(images_dir, files[0]))
        try:
            project = Project.create(images_dir, name, info["channels"])
        except ValueError as e:
            raise ApiError(str(e))
        self._set_project(project)
        return self.state()

    def open_project(self, path):
        if not os.path.exists(os.path.join(path, "project.json")):
            raise ApiError("No NucleiQuant project in this folder.")
        self._set_project(Project.load(path))
        return self.state()

    def _set_project(self, project):
        with self.lock:
            self.project = project
            self.annotations = self._load_annotations()
            self._features = {}
            self.predictions = {}
            self._survey = None
            self.classifier = None
            if os.path.exists(project.path("classifier", "classifier.json", make_parent=False)):
                try:
                    self.classifier = Classifier.load(project.path("classifier", make_parent=False))
                except Exception:
                    self.classifier = None

    def close_project(self):
        self.project = None
        return {"ok": True}

    def files(self):
        p = self._require()
        pattern = p.pattern()
        out = []
        for f in io.list_tiffs(p.images_dir):
            try:
                out.append({"image": f, "fields": metadata.parse_filename(f, pattern)})
            except ValueError:
                out.append({"image": f, "error": "name does not match the pattern"})
        return out

    def files_summary(self):
        items = self.files()
        ok = [i for i in items if "fields" in i]
        clones = sorted({i["fields"].get("clone") for i in ok if i["fields"].get("clone")})
        organoids = {}
        for i in ok:
            fl = i["fields"]
            if "organoid" in fl:
                key = (fl.get("clone"), fl["organoid"])
                organoids.setdefault(key, set()).add(fl.get("slice", i["image"]))
        slices = [len(v) for v in organoids.values()]
        example = ok[0] if ok else (items[0] if items else None)
        info = {}
        if items:
            try:
                info = io.image_info(self.project.image_path(items[0]["image"]))
            except Exception:
                info = {}
        return {
            "channels": info.get("channels"), "pixel_size": info.get("pixel_size"),
            "height": info.get("height"), "width": info.get("width"),
            "n": len(items), "n_ok": len(ok),
            "errors": [i["image"] for i in items if "error" in i][:20],
            "clones": clones, "n_organoids": len(organoids),
            "slices_min": min(slices) if slices else None, "slices_max": max(slices) if slices else None,
            "fields": list(self.project.pattern().groupindex),
            "example": example,
        }

    def update_project(self, changes):
        p = self._require()
        with p.lock:
            d = p.data
            reset_crops = False
            if "name" in changes and changes["name"].strip():
                d["name"] = changes["name"].strip()
            if "channels" in changes:
                chans = changes["channels"]
                if len(chans) != len(d["channels"]):
                    raise ApiError("The number of channels can't change.")
                for c, new in zip(d["channels"], chans):
                    c["name"] = str(new.get("name", c["name"])).strip() or c["name"]
                    c["color"] = new.get("color", c["color"])
            if "nuclear_channel" in changes:
                nc = int(changes["nuclear_channel"])
                if not 0 <= nc < len(d["channels"]):
                    raise ApiError("Invalid nuclear channel.")
                if nc != d["nuclear_channel"]:
                    d["nuclear_channel"] = nc
                    reset_crops = True
            if "genotypes" in changes:
                d["genotypes"] = {str(k): str(v).strip() for k, v in changes["genotypes"].items()}
            if "filename_template" in changes:
                try:
                    metadata.pattern_from_template(changes["filename_template"])
                except ValueError as e:
                    raise ApiError(str(e))
                d["filename_template"] = changes["filename_template"].strip()
            if "settings" in changes:
                for k, v in changes["settings"].items():
                    if k not in d["settings"]:
                        continue
                    old = d["settings"][k]
                    if isinstance(old, bool):
                        v = bool(v)
                    elif isinstance(old, int):
                        v = int(v)
                    elif isinstance(old, float):
                        v = float(v)
                    else:
                        v = str(v)
                    if k in ("norm_low", "norm_high", "ring_radius", "perinuclear_radius", "texture_levels", "crop_fraction") and v != old:
                        reset_crops = True
                    d["settings"][k] = v
            if reset_crops:
                d["survey"]["done"] = d["survey"].get("done", False) and "nuclear_channel" not in changes
                for c in d["crops"]:
                    c["status"] = "stale"
            p.save()
        return self.state()

    # ---- survey --------------------------------------------------------------------

    def _survey_entries(self):
        if self._survey is None:
            p = self._require()
            path = p.path("survey.json", make_parent=False)
            if os.path.exists(path):
                with open(path) as f:
                    self._survey = json.load(f)
            else:
                self._survey = []
        return self._survey

    def _survey_entry(self, image):
        for e in self._survey_entries():
            if e["image"] == image:
                return e
        return None

    def start_survey(self):
        p = self._require()
        return self.jobs.submit("survey", "Measuring image intensities", self._run_survey, p)

    def _run_survey(self, job, p):
        names = [i["image"] for i in self.files() if "fields" in i]
        if not names:
            raise ApiError("No image names match the pattern.")
        s = p.settings
        nuc = p.data["nuclear_channel"]

        def prog(done, total, name):
            job.update(done / total, f"{done} of {total} images")

        entries = survey.survey_images([p.image_path(n) for n in names], nuc, s["norm_low"], s["norm_high"], prog)
        with open(p.path("survey.json"), "w") as f:
            json.dump(entries, f)
        rows = []
        for e in entries:
            row = {"image": e["image"]}
            for c, ch in enumerate(p.data["channels"]):
                row[f"mean_in_nuclei_{ch['name']}"] = round(e["mean_in_nuclei"][c], 3)
            rows.append(row)
        pd.DataFrame(rows).to_csv(p.path("survey.csv"), index=False)
        self._survey = entries
        with p.lock:
            p.data["survey"] = {"done": True}
            ch = min(int(s["survey_channel"]), len(p.data["channels"]) - 1)
            p.data["selection"] = self._auto_picks(ch)
            p.save()
        return {"n": len(entries)}

    def _group_of(self, image):
        try:
            fields = self.project.parse(image)
        except ValueError:
            return ""
        return fields.get("clone", "")

    def _auto_picks(self, channel):
        picks = survey.pick_training_images(self._survey_entries(), channel, self._group_of)
        return [{"image": k, "role": v} for k, v in picks.items()]

    def survey_data(self):
        p = self._require()
        entries = self._survey_entries()
        out = []
        for e in entries:
            try:
                fields = p.parse(e["image"])
            except ValueError:
                fields = {}
            out.append({"image": e["image"], "fields": fields, "values": e["mean_in_nuclei"],
                        "group": fields.get("clone", "")})
        return {"entries": out, "selection": p.data["selection"],
                "channel": p.settings["survey_channel"], "genotypes": p.data["genotypes"]}

    def set_survey_channel(self, channel):
        p = self._require()
        with p.lock:
            p.settings["survey_channel"] = int(channel)
            p.data["selection"] = self._auto_picks(int(channel))
            p.save()
        return self.survey_data()

    def set_selection(self, selection):
        p = self._require()
        valid = {e["image"] for e in self._survey_entries()}
        sel = []
        for item in selection:
            if item["image"] in valid:
                sel.append({"image": item["image"], "role": item.get("role") or "Manual"})
        with p.lock:
            p.data["selection"] = sel
            p.save()
        return self.survey_data()

    def reset_selection(self):
        p = self._require()
        return self.set_survey_channel(p.settings["survey_channel"])

    # ---- crops ---------------------------------------------------------------------

    def start_crops(self):
        p = self._require()
        return self.jobs.submit("crops", "Creating training crops", self._run_crops, p)

    def _run_crops(self, job, p):
        with p.lock:
            selected = {s["image"]: s["role"] for s in p.data["selection"]}
            keep = []
            for c in p.data["crops"]:
                if c["image"] in selected:
                    c["role"] = selected[c["image"]]
                    keep.append(c)
                else:
                    self._drop_crop(p, c["id"])
            p.data["crops"] = keep
            existing = {c["image"] for c in keep}
            n = p.data.get("next_crop", 1)
            for image, role in selected.items():
                if image not in existing:
                    p.data["crops"].append({"id": f"crop{n:02d}", "image": image, "role": role, "status": "queued"})
                    n += 1
            p.data["next_crop"] = n
            p.save()
        todo = [c for c in p.data["crops"] if c.get("status") != "ready"]
        for k, c in enumerate(todo):
            if c.get("status") == "stale":
                # Segmentation will change: labels on this crop no longer apply
                self.annotations = {key: v for key, v in self.annotations.items() if key[0] != c["id"]}
                self._save_annotations()
            c["status"] = "running"

            def prog(msg, frac, k=k, c=c):
                job.update((k + frac) / len(todo), f"{c['image']}: {msg}")

            crops.build_crop(p, c, self._survey_entry(c["image"]), prog)
            self._features.pop(c["id"], None)
            self.predictions.pop(c["id"], None)
            with p.lock:
                p.save()
        return {"n": len(p.data["crops"])}

    def _drop_crop(self, p, crop_id):
        crops.remove_crop_files(p, crop_id)
        self.annotations = {k: v for k, v in self.annotations.items() if k[0] != crop_id}
        self._save_annotations()
        self._features.pop(crop_id, None)
        self.predictions.pop(crop_id, None)

    def move_crop(self, crop_id, y, x):
        p = self._require()
        c = p.crop(crop_id)

        def run(job):
            c["y"], c["x"] = int(y), int(x)
            c["status"] = "running"
            self.annotations = {k: v for k, v in self.annotations.items() if k[0] != crop_id}
            self._save_annotations()
            crops.build_crop(p, c, self._survey_entry(c["image"]), lambda m, f: job.update(f, m))
            self._features.pop(crop_id, None)
            self.predictions.pop(crop_id, None)
            with p.lock:
                p.save()
            return {"id": crop_id}

        return self.jobs.submit("crop", "Moving crop", run)

    def crop_file(self, crop_id, kind):
        p = self._require()
        p.crop(crop_id)
        return crops.crop_paths(p, crop_id)[kind]

    def crop_raw(self, crop_id):
        """(bytes, shape) of the crop as uint16 (C, Y, X)."""
        img = io.read_image(self.crop_file(crop_id, "image"))
        return _as_u16(img).tobytes(), img.shape

    def crop_labels(self, crop_id):
        lab = io.read_labels(self.crop_file(crop_id, "labels")).astype(np.uint32)
        return lab.tobytes(), lab.shape

    def crop_outlines(self, crop_id):
        from .contours import pack_outlines
        z = np.load(self.crop_file(crop_id, "outlines"))
        return pack_outlines(z["ids"], z["offsets"], z["ys"], z["xs"])

    def _crop_features(self, crop_id):
        if crop_id not in self._features:
            self._features[crop_id] = pd.read_pickle(self.crop_file(crop_id, "features"))
        return self._features[crop_id]

    def crop_objects(self, crop_id):
        df = self._crop_features(crop_id)
        return {"labels": df["label"].astype(int).tolist(), "edge": df["touches_border"].astype(bool).tolist()}

    # ---- categories and labels -------------------------------------------------------

    def add_category(self, name, color=None):
        p = self._require()
        name = name.strip()
        if not name:
            raise ApiError("Give the category a name.")
        if any(c["name"].lower() == name.lower() for c in p.categories):
            raise ApiError(f"There is already a category called '{name}'.")
        with p.lock:
            used = {c["color"] for c in p.categories}
            if not color:
                color = next((c for c in CATEGORY_COLORS if c not in used), CATEGORY_COLORS[len(p.categories) % len(CATEGORY_COLORS)])
            n = p.data.get("next_category", 1)
            p.data["next_category"] = n + 1
            p.categories.append({"id": f"cat{n}", "name": name, "color": color, "builtin": False})
            self._invalidate_training(p)
            p.save()
        return self.state()

    def update_category(self, category_id, name=None, color=None):
        p = self._require()
        cat = p.category(category_id)
        with p.lock:
            if name is not None and name.strip():
                if any(c["name"].lower() == name.strip().lower() and c["id"] != category_id for c in p.categories):
                    raise ApiError(f"There is already a category called '{name.strip()}'.")
                cat["name"] = name.strip()
            if color:
                cat["color"] = color
            p.save()
        return self.state()

    def delete_category(self, category_id):
        p = self._require()
        cat = p.category(category_id)
        if cat.get("builtin"):
            raise ApiError(f"'{cat['name']}' is always included and can't be deleted.")
        with p.lock:
            p.data["categories"] = [c for c in p.categories if c["id"] != category_id]
            self.annotations = {k: v for k, v in self.annotations.items() if v != category_id}
            self._save_annotations()
            self._invalidate_training(p)
            p.save()
        return self.state()

    def set_label(self, crop_id, label, category_id):
        p = self._require()
        p.crop(crop_id)
        df = self._crop_features(crop_id)
        row = df.index[df["label"] == int(label)]
        if len(row) == 0:
            raise ApiError("No nucleus there.")
        if bool(df.loc[row[0], "touches_border"]):
            raise ApiError("This nucleus is cut by the crop edge and can't be labeled.")
        key = (crop_id, int(label))
        with self.lock:
            if category_id is None:
                self.annotations.pop(key, None)
            else:
                p.category(category_id)
                self.annotations[key] = category_id
            self._save_annotations()
            if p.data["classifier"].get("trained") and not p.data["classifier"].get("stale"):
                p.data["classifier"]["stale"] = True
                p.data["classifier"]["validated"] = False
                p.save()
        return self.label_counts()

    def labels_of_crop(self, crop_id):
        return {str(lab): cat for (c, lab), cat in self.annotations.items() if c == crop_id}

    def label_counts(self):
        p = self._require()
        per_cat = {c["id"]: 0 for c in p.categories}
        per_crop = {c["id"]: {k["id"]: 0 for k in p.categories} for c in p.data["crops"]}
        for (crop_id, _), cat in self.annotations.items():
            if cat in per_cat:
                per_cat[cat] += 1
                if crop_id in per_crop:
                    per_crop[crop_id][cat] += 1
        target = int(p.settings["label_target"])
        used = [c for c, n in per_cat.items() if n > 0]
        # Categories without any label are left out of training (the app warns about them)
        needed = sum(max(0, target - per_cat[c]) for c in used)
        ready = needed == 0 and len(used) >= 2
        return {"per_category": per_cat, "per_crop": per_crop, "total": sum(per_cat.values()),
                "target": target, "needed": needed, "ready": ready,
                "unused": [c for c, n in per_cat.items() if n == 0]}

    def _annotations_path(self):
        return self.project.path("training", "annotations.csv")

    def _load_annotations(self):
        path = os.path.join(self.project.dir, "training", "annotations.csv")
        out = {}
        if os.path.exists(path):
            with open(path) as f:
                for row in csv.DictReader(f):
                    out[(row["crop_id"], int(row["label"]))] = row["category"]
        return out

    def _save_annotations(self):
        if self.project is None:
            return
        path = self._annotations_path()
        tmp = path + ".tmp"
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["crop_id", "label", "category"])
            for (crop_id, label), cat in sorted(self.annotations.items()):
                w.writerow([crop_id, label, cat])
        os.replace(tmp, path)

    def _invalidate_training(self, p):
        if p.data["classifier"].get("trained"):
            p.data["classifier"]["stale"] = True
            p.data["classifier"]["validated"] = False

    # ---- classifier ------------------------------------------------------------------

    def training_table(self):
        p = self._require()
        frames = []
        for c in p.data["crops"]:
            if c.get("status") != "ready":
                continue
            labs = {lab: cat for (cid, lab), cat in self.annotations.items() if cid == c["id"]}
            if not labs:
                continue
            df = self._crop_features(c["id"])
            sub = df[df["label"].isin(list(labs))].copy()
            sub.insert(0, "category", sub["label"].map(labs))
            sub.insert(0, "crop_id", c["id"])
            sub.insert(1, "image", c["image"])
            frames.append(sub)
        if not frames:
            raise ApiError("Label some nuclei first.")
        return pd.concat(frames, ignore_index=True)

    def start_training(self):
        p = self._require()
        return self.jobs.submit("train", "Training the classifier", self._run_training, p)

    def _run_training(self, job, p):
        job.update(0.05, "Collecting labeled nuclei")
        table = self.training_table()
        feats = features.feature_columns(table.drop(columns=["crop_id", "image", "category"]))
        cat_ids = [c["id"] for c in p.categories]
        job.update(0.15, "Training and testing on held-out crops")
        clf = Classifier.fit(table, feats, cat_ids, p.settings["n_trees"])
        clf.save(os.path.join(p.dir, "classifier"), table)
        self.classifier = clf
        job.update(0.8, "Classifying all crops")
        self.predictions = {}
        for c in p.data["crops"]:
            if c.get("status") == "ready":
                self._predict_crop(c["id"])
        with p.lock:
            p.data["classifier"] = {"trained": True, "validated": False, "stale": False, "hash": clf.info["hash"],
                                    "accuracy": clf.info["cross_validation"]["accuracy"]}
            p.save()
        return self.classifier_info()

    def _predict_crop(self, crop_id):
        df = self._crop_features(crop_id)
        cats, _, pmax = self.classifier.predict(df)
        index = {c["id"]: i for i, c in enumerate(self.project.categories)}
        self.predictions[crop_id] = {
            "labels": df["label"].astype(int).tolist(),
            "category": [index.get(c, -1) for c in cats],
            "probability": np.round(pmax, 3).tolist(),
        }
        return self.predictions[crop_id]

    def crop_predictions(self, crop_id):
        if self.classifier is None:
            raise ApiError("Train the classifier first.")
        return self.predictions.get(crop_id) or self._predict_crop(crop_id)

    def classifier_info(self):
        if self.classifier is None:
            return None
        info = dict(self.classifier.info)
        info["categories"] = self.classifier.categories
        return info

    def validate_classifier(self):
        p = self._require()
        if self.classifier is None:
            raise ApiError("Train the classifier first.")
        with p.lock:
            p.data["classifier"]["validated"] = True
            p.save()
        return self.state()

    def import_classifier(self, source_dir):
        """Reuse a trained classifier (and its categories/channels) from another project."""
        p = self._require()
        src = Project.load(source_dir)
        folder = src.path("classifier", make_parent=False)
        if not os.path.exists(os.path.join(folder, "classifier.json")):
            raise ApiError("That project has no trained classifier.")
        if len(src.data["channels"]) != len(p.data["channels"]):
            raise ApiError("That classifier was trained on images with a different number of channels.")
        dest = p.path("classifier", make_parent=False)
        if os.path.exists(dest):
            shutil.rmtree(dest)
        shutil.copytree(folder, dest)
        with p.lock:
            p.data["categories"] = src.data["categories"]
            p.data["channels"] = src.data["channels"]
            p.data["nuclear_channel"] = src.data["nuclear_channel"]
            for k in ("norm_low", "norm_high", "ring_radius", "perinuclear_radius", "texture_levels", "n_trees"):
                p.settings[k] = src.settings[k]
            self.classifier = Classifier.load(dest)
            p.data["classifier"] = {"trained": True, "validated": True, "stale": False, "imported_from": src.dir,
                                    "hash": self.classifier.info["hash"],
                                    "accuracy": self.classifier.info["cross_validation"]["accuracy"]}
            p.save()
        return self.state()

    # ---- batch and results -------------------------------------------------------------

    def start_batch(self):
        p = self._require()
        if self.classifier is None or not p.data["classifier"].get("validated"):
            raise ApiError("Validate the classifier on the Preview screen first.")
        return self.jobs.submit("batch", "Classifying all images", self._run_batch, p)

    def _run_batch(self, job, p):
        names = [i["image"] for i in self.files() if "fields" in i]
        entries = {e["image"]: e for e in self._survey_entries()}
        missing = [n for n in names if n not in entries]
        if missing:
            job.update(0.0, "Measuring image intensities")
            s = p.settings
            new = survey.survey_images([p.image_path(n) for n in missing], p.data["nuclear_channel"], s["norm_low"], s["norm_high"])
            self._survey = self._survey_entries() + new
            with open(p.path("survey.json"), "w") as f:
                json.dump(self._survey, f)
            entries = {e["image"]: e for e in self._survey}
        h = self.classifier.info["hash"]
        todo = [n for n in names if not batch.is_done(p, n, h)]
        for k, name in enumerate(todo):
            def prog(msg, frac, k=k, name=name):
                job.update((k + frac) / max(len(todo), 1) * 0.97,
                           f"Image {len(names) - len(todo) + k + 1} of {len(names)} · {name} · {msg}")
            batch.process_image(p, name, self.classifier, entries[name], prog)
        job.update(0.98, "Writing the Excel file")
        res = self._write_results(p, names)
        with p.lock:
            p.data["batch"] = {"done": True, "classifier_hash": h, "n_images": len(names)}
            p.save()
        return res

    def _write_results(self, p, names=None):
        if names is None:
            names = [i["image"] for i in self.files() if "fields" in i]
        summaries = batch.load_summaries(p, names)
        res = quantify.write_outputs(p, summaries, self.classifier.info if self.classifier else None)
        res["excel"] = display_path(res["excel"])
        res["folder"] = display_path(os.path.join(p.dir, "results"))
        with open(p.path("results", "results.json"), "w") as f:
            json.dump(res, f)
        return res

    def results(self):
        p = self._require()
        path = p.path("results", "results.json", make_parent=False)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            res = json.load(f)
        # Paths as seen now (the app may have been started with other folder mounts)
        res["folder"] = display_path(os.path.join(p.dir, "results"))
        res["excel"] = display_path(os.path.join(p.dir, "results", res["excel_name"]))
        return res

    def refresh_results(self):
        """Rebuild the Excel file and plots (e.g. after editing genotypes) without reclassifying."""
        p = self._require()
        if not p.data["batch"].get("done"):
            raise ApiError("Classify all images first.")
        return self._write_results(p)

    def excel_path(self):
        p = self._require()
        res = self.results()
        if not res:
            raise ApiError("No results yet.")
        path = os.path.join(p.dir, "results", res["excel_name"])
        if not os.path.exists(path):
            raise ApiError("The Excel file is missing; run the classification again.")
        return path

    def image_view(self, image, max_size=2048):
        """Downsampled image, labels, outlines and categories of one classified image."""
        p = self._require()
        paths = batch.result_paths(p, image)
        if not os.path.exists(paths["pred"]):
            raise ApiError("This image hasn't been classified yet.")
        img = io.read_image(p.image_path(image))
        C, H, W = img.shape
        f = max(1, int(np.ceil(max(H, W) / max_size)))
        from .render import downsample_mean
        small = downsample_mean(img.astype(np.float32), f) if f > 1 else img
        labels = io.read_labels(paths["labels"])[::f, ::f][: small.shape[1], : small.shape[2]].astype(np.uint32)
        return {"raw": _as_u16(small), "labels": labels, "scale": f, "paths": paths}

    # ---- state for the app --------------------------------------------------------------

    def state(self):
        if self.project is None:
            return {"project": None, "system": self.system()}
        p = self.project
        d = p.data
        files = self.files_summary()
        counts = self.label_counts()
        crops_ready = bool(d["crops"]) and all(c.get("status") == "ready" for c in d["crops"])
        labels_ok = counts["ready"] and crops_ready
        clf = d["classifier"]
        imported = bool(clf.get("imported_from"))
        steps = {
            "project": files["n_ok"] > 0 and files["n_ok"] == files["n"],
            "survey": bool(d["survey"].get("done")) and bool(d["selection"]),
            "crops": crops_ready,
            "label": labels_ok,
            "preview": bool(clf.get("validated")) and not clf.get("stale"),
            "results": bool(d["batch"].get("done")),
        }
        return {
            "system": self.system(),
            "project": {
                "name": d["name"], "dir": p.dir, "dir_display": display_path(p.dir),
                "images_dir_display": display_path(p.images_dir),
                "channels": d["channels"], "nuclear_channel": d["nuclear_channel"],
                "genotypes": d["genotypes"], "categories": d["categories"],
                "settings": d["settings"], "filename_template": d["filename_template"],
                "selection": d["selection"], "crops": [dict(c, fields=_fields(p, c["image"])) for c in d["crops"]],
                "survey_done": bool(d["survey"].get("done")),
                "classifier": clf, "batch": d["batch"], "imported_classifier": imported,
            },
            "files": files,
            "labels": counts,
            "steps": steps,
            "classifier": self.classifier_info(),
            "jobs": self.jobs.active(),
            "channel_colors": CHANNEL_COLORS,
            "category_colors": CATEGORY_COLORS,
        }


def _fields(project, image):
    try:
        return project.parse(image)
    except ValueError:
        return {}


def _stage(data):
    if data.get("batch", {}).get("done"):
        return "Results ready"
    if data.get("classifier", {}).get("validated"):
        return "Ready to classify all images"
    if data.get("classifier", {}).get("trained"):
        return "Previewing"
    if data.get("crops"):
        return "Labeling"
    if data.get("survey", {}).get("done"):
        return "Choosing training images"
    return "Setting up"


def _as_u16(img):
    img = np.asarray(img)
    if img.dtype == np.uint16:
        return np.ascontiguousarray(img)
    if img.dtype == np.uint8 or np.issubdtype(img.dtype, np.integer):
        return np.clip(img, 0, 65535).astype(np.uint16)
    return np.clip(np.round(img), 0, 65535).astype(np.uint16)
