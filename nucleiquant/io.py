"""Image and label input/output.

All images are handled as (C, Y, X) arrays. TIFFs saved in other layouts
(YXC, single channel, ImageJ hyperstacks with a leading S axis) are
converted on read.
"""

import os

import h5py
import numpy as np
import tifffile

__all__ = [
    "TIFF_EXTENSIONS", "list_tiffs", "read_image", "image_info",
    "write_image", "write_labels", "read_labels",
]

TIFF_EXTENSIONS = (".tif", ".tiff")


def list_tiffs(folder):
    """Sorted TIFF file names in a folder (macOS '._' files skipped)."""
    return sorted(
        f for f in os.listdir(folder)
        if f.lower().endswith(TIFF_EXTENSIONS) and not f.startswith("._")
    )


def _to_cyx(data, axes):
    """Reorder an array to (C, Y, X) from its tifffile axes string."""
    axes = axes.upper()
    # Squeeze singleton axes other than Y and X
    keep = []
    for i, a in enumerate(axes):
        if a in "YX" or data.shape[i] > 1:
            keep.append(i)
    data = data.squeeze(axis=tuple(i for i in range(data.ndim) if i not in keep))
    axes = "".join(axes[i] for i in keep)
    if axes == "YX":
        return data[np.newaxis]
    if len(axes) != 3:
        raise ValueError(f"Unsupported image layout '{axes}' (expected 2D multichannel images)")
    other = [a for a in axes if a not in "YX"][0]
    order = [axes.index(other), axes.index("Y"), axes.index("X")]
    return np.transpose(data, order)


def _pixel_size(tif):
    """Pixel size in micrometres from the TIFF resolution tags, or None."""
    try:
        page = tif.pages[0]
        tag = page.tags.get("XResolution")
        unit = page.tags.get("ResolutionUnit")
        if tag is None:
            return None
        num, den = tag.value
        if num == 0:
            return None
        px_per_unit = num / den
        meta = tif.imagej_metadata or {}
        if meta.get("unit") in ("micron", "um", "µm") or (unit is not None and unit.value == 1 and meta):
            return 1.0 / px_per_unit
        if unit is not None and unit.value == 3:  # centimetre
            return 1e4 / px_per_unit
        if unit is not None and unit.value == 2:  # inch
            return 25400.0 / px_per_unit
    except Exception:
        return None
    return None


def read_image(path, channel=None):
    """Read a TIFF as (C, Y, X), or a single (Y, X) channel if `channel` is given."""
    with tifffile.TiffFile(path) as tif:
        series = tif.series[0]
        data = series.asarray()
        img = _to_cyx(data, series.axes)
    if channel is not None:
        return img[channel]
    return img


def image_info(path):
    """Shape, dtype and pixel size of a TIFF without loading all pixels."""
    with tifffile.TiffFile(path) as tif:
        series = tif.series[0]
        axes = series.axes.upper()
        shape = dict(zip(axes, series.shape))
        n_channels = 1
        for a, n in shape.items():
            if a not in "YX" and n > 1:
                n_channels = n
        return {
            "channels": int(n_channels),
            "height": int(shape.get("Y", 0)),
            "width": int(shape.get("X", 0)),
            "dtype": str(series.dtype),
            "pixel_size": _pixel_size(tif),
        }


def write_image(path, img, pixel_size=None):
    """Save a (C, Y, X) image as an ImageJ hyperstack, keeping the pixel size."""
    img = np.ascontiguousarray(img)
    kwargs = {"imagej": True, "metadata": {"axes": "CYX", "mode": "composite"}}
    if pixel_size:
        kwargs["resolution"] = (1.0 / pixel_size, 1.0 / pixel_size)
        kwargs["metadata"]["unit"] = "um"
    tifffile.imwrite(path, img, **kwargs)


def write_labels(base_path, labels):
    """Save a label image as both .tif and .h5 (dataset 'labels'), as in V1."""
    labels = labels.astype(np.uint16 if labels.max() < 2**16 else np.uint32)
    tifffile.imwrite(base_path + ".tif", labels, compression="zlib")
    with h5py.File(base_path + ".h5", "w") as f:
        f.create_dataset("labels", data=labels, compression="gzip")


def read_labels(base_path):
    """Read a label image written by write_labels."""
    if os.path.exists(base_path + ".tif"):
        return tifffile.imread(base_path + ".tif")
    with h5py.File(base_path + ".h5", "r") as f:
        return f["labels"][:]
