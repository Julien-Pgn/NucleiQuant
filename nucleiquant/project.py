"""Project folder: settings, state and file layout.

A project lives in a folder (by default <images folder>/NucleiQuant_projects/<name>).
Everything the app knows about a project is in project.json there, written
atomically after every change, so a project can be closed and reopened at
any step.
"""

import copy
import datetime
import json
import os
import threading

from . import metadata

__all__ = [
    "Project", "DEFAULT_SETTINGS", "DEFAULT_CATEGORIES", "CHANNEL_COLORS",
    "CATEGORY_COLORS", "state_dir", "recent_projects", "remember_project",
]

PROJECT_FILE = "project.json"
PROJECTS_SUBDIR = "NucleiQuant_projects"

# Display colours offered for channels (first ones used by default)
CHANNEL_COLORS = ["#386BFF", "#40FF73", "#FF389E", "#D4D4D8", "#FFB020", "#00E5FF"]

# Colours for user categories, chosen to stay distinct from channel colours
CATEGORY_COLORS = ["#FF8A3D", "#3DB2FF", "#FF5FA2", "#B18CFF", "#2DD4BF", "#C3E14B", "#FFD166", "#F87171"]

DEFAULT_CATEGORIES = [
    {"id": "dead", "name": "Dead", "color": "#A1A1AA", "builtin": True},
    {"id": "unstained", "name": "Unstained", "color": "#E4E4E7", "builtin": True},
]

DEFAULT_SETTINGS = {
    # Segmentation (stardist_haug2). Percentiles of the nuclear channel used
    # for normalisation; 0.2 (not 1) avoids oversegmenting dark images.
    "norm_low": 0.2,
    "norm_high": 99.8,
    # Training images and crops
    "survey_channel": 1,
    "crop_fraction": 0.5,
    # Labeling target per category before the preview unlocks
    "label_target": 50,
    # Features
    "ring_radius": 30,
    "perinuclear_radius": 4,
    "texture_levels": 16,
    # Random forest
    "n_trees": 100,
    "uncertain_threshold": 0.6,
    # Quantification
    "min_slices": 4,
    "group_by": "genotype",
    # Also save every feature of every nucleus (large files)
    "save_all_features": False,
}


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def state_dir():
    """Folder for app-wide state (recent projects)."""
    d = os.environ.get("NQ_STATE_DIR") or os.path.join(os.path.expanduser("~"), ".nucleiquant")
    os.makedirs(d, exist_ok=True)
    return d


def recent_projects():
    """Recently opened project folders that still exist, newest first."""
    path = os.path.join(state_dir(), "recent.json")
    try:
        with open(path) as f:
            items = json.load(f)
    except (OSError, ValueError):
        return []
    return [p for p in items if os.path.exists(os.path.join(p, PROJECT_FILE))]


def remember_project(project_dir):
    """Put a project at the top of the recent list."""
    items = [p for p in recent_projects() if os.path.abspath(p) != os.path.abspath(project_dir)]
    items.insert(0, os.path.abspath(project_dir))
    path = os.path.join(state_dir(), "recent.json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items[:12], f, indent=1)
    os.replace(tmp, path)


class Project:
    """A NucleiQuant project folder."""

    def __init__(self, project_dir, data):
        self.dir = os.path.abspath(project_dir)
        self.data = data
        self.lock = threading.RLock()

    # ---- creation / loading -------------------------------------------------

    @classmethod
    def create(cls, images_dir, name, n_channels=4):
        images_dir = os.path.abspath(images_dir)
        project_dir = os.path.join(images_dir, PROJECTS_SUBDIR, name)
        if os.path.exists(os.path.join(project_dir, PROJECT_FILE)):
            raise ValueError(f"A project called '{name}' already exists for these images")
        os.makedirs(project_dir, exist_ok=True)
        channels = []
        for c in range(n_channels):
            channels.append({
                "name": "DAPI" if c == 0 else f"Channel {c + 1}",
                "color": CHANNEL_COLORS[c % len(CHANNEL_COLORS)],
            })
        data = {
            "version": 2,
            "name": name,
            "created": _now(),
            "modified": _now(),
            "images_dir": os.path.relpath(images_dir, project_dir),
            "filename_template": metadata.DEFAULT_TEMPLATE,
            "channels": channels,
            "nuclear_channel": 0,
            "genotypes": {},
            "categories": copy.deepcopy(DEFAULT_CATEGORIES),
            "settings": copy.deepcopy(DEFAULT_SETTINGS),
            "survey": {"done": False},
            "selection": [],
            "crops": [],
            "classifier": {"trained": False, "validated": False},
            "batch": {"done": False},
            "next_category": 1,
        }
        if n_channels < 2:
            data["settings"]["survey_channel"] = 0
        project = cls(project_dir, data)
        project.save()
        remember_project(project_dir)
        return project

    @classmethod
    def load(cls, project_dir):
        with open(os.path.join(project_dir, PROJECT_FILE)) as f:
            data = json.load(f)
        # Fill settings added in later versions
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        settings.update(data.get("settings", {}))
        data["settings"] = settings
        project = cls(project_dir, data)
        remember_project(project_dir)
        return project

    def save(self):
        with self.lock:
            self.data["modified"] = _now()
            path = os.path.join(self.dir, PROJECT_FILE)
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f, indent=1)
            os.replace(tmp, path)

    # ---- paths --------------------------------------------------------------

    @property
    def images_dir(self):
        return os.path.normpath(os.path.join(self.dir, self.data["images_dir"]))

    def path(self, *parts, make_parent=True):
        p = os.path.join(self.dir, *parts)
        if make_parent:
            os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def image_path(self, image_name):
        return os.path.join(self.images_dir, image_name)

    # ---- convenience --------------------------------------------------------

    @property
    def settings(self):
        return self.data["settings"]

    @property
    def categories(self):
        return self.data["categories"]

    @property
    def channel_names(self):
        return [c["name"] for c in self.data["channels"]]

    def pattern(self):
        return metadata.pattern_from_template(self.data["filename_template"])

    def parse(self, image_name):
        return metadata.parse_filename(image_name, self.pattern())

    def crop(self, crop_id):
        for c in self.data["crops"]:
            if c["id"] == crop_id:
                return c
        raise KeyError(f"No crop '{crop_id}'")

    def category(self, category_id):
        for c in self.categories:
            if c["id"] == category_id:
                return c
        raise KeyError(f"No category '{category_id}'")

    def genotype_of(self, fields):
        clone = fields.get("clone")
        if clone is None:
            return ""
        return self.data["genotypes"].get(clone, "")
