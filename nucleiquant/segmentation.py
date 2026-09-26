"""Nuclei segmentation with the fine-tuned StarDist model (stardist_haug2).

TensorFlow is imported lazily, the first time a segmentation or a device
query is needed, so the app starts instantly.
"""

import math
import os
import threading

import numpy as np

# oneDNN makes this TensorFlow build's CPU inference ~350x slower (measured: 173 s vs
# 0.5 s for a 1024x1024 image). It only affects CPU operations; GPU runs are unchanged.
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

__all__ = ["model_dir", "device_info", "segment", "normalization_range", "SEGMENTATION_VERSION"]

MODEL_NAME = "stardist_haug2"
# Bump when anything changing segmentation output changes (invalidates caches)
SEGMENTATION_VERSION = 1
# Largest tile edge sent to the network at once (keeps GPU memory modest)
TILE_SIZE = 1100

_lock = threading.Lock()
_model = None
_device = None


def model_dir():
    """Folder containing the stardist_haug2 model folder."""
    env = os.environ.get("NQ_MODEL_DIR")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "models"))


def _init_tf():
    import tensorflow as tf
    for gpu in tf.config.list_physical_devices("GPU"):
        try:
            tf.config.experimental.set_memory_growth(gpu, True)
        except RuntimeError:
            pass
    return tf


def device_info():
    """{'device': 'GPU' or 'CPU', 'name': ...}; imports TensorFlow once."""
    global _device
    with _lock:
        if _device is None:
            try:
                tf = _init_tf()
                gpus = tf.config.list_physical_devices("GPU")
                if gpus:
                    try:
                        name = tf.config.experimental.get_device_details(gpus[0]).get("device_name", "GPU")
                    except Exception:
                        name = "GPU"
                    _device = {"device": "GPU", "name": name.replace("NVIDIA ", "").replace("GeForce ", "")}
                else:
                    _device = {"device": "CPU", "name": "CPU"}
            except Exception as e:  # TensorFlow missing or broken
                _device = {"device": "none", "name": f"TensorFlow unavailable: {e}"}
        return dict(_device)


def _get_model():
    global _model
    if _model is None:
        _init_tf()
        from stardist.models import StarDist2D
        _model = StarDist2D(None, name=MODEL_NAME, basedir=model_dir())
    return _model


def normalization_range(nuclear, low=0.2, high=99.8):
    """Intensity range used to normalise the nuclear channel (percentiles)."""
    lo, hi = np.percentile(nuclear, (low, high))
    return float(lo), float(hi)


def segment(nuclear, lo, hi, return_polygons=False):
    """Segment nuclei in one channel normalised to [lo, hi].

    lo/hi come from the whole image (normalization_range), so a crop is
    segmented with exactly the same scaling as its full image.
    Returns an int32 label image (0 = background), plus StarDist's polygon
    dict when return_polygons is True.
    """
    x = (np.asarray(nuclear, dtype=np.float32) - lo) / max(hi - lo, 1e-20)
    n_tiles = tuple(max(1, math.ceil(s / TILE_SIZE)) for s in x.shape)
    with _lock:
        model = _get_model()
        labels, polys = model.predict_instances(x, axes="YX", normalizer=None, n_tiles=n_tiles, show_tile_progress=False)
    labels = labels.astype(np.int32)
    return (labels, polys) if return_polygons else labels
