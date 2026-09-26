import os
import sys

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
TEST_IMAGES = os.path.join(ROOT, "img_test_pipeline")


def disk(shape, cy, cx, r):
    yy, xx = np.mgrid[: shape[0], : shape[1]]
    return (yy - cy) ** 2 + (xx - cx) ** 2 <= r * r


@pytest.fixture
def synthetic():
    """Two-channel image with 4 round nuclei of known intensities."""
    H, W = 120, 140
    labels = np.zeros((H, W), np.int32)
    img = np.zeros((2, H, W), np.float32) + 10
    centres = [(30, 30, 8), (30, 90, 10), (85, 40, 6), (85, 100, 9)]
    for i, (cy, cx, r) in enumerate(centres, 1):
        m = disk((H, W), cy, cx, r)
        labels[m] = i
        img[0][m] = 100 * i
        img[1][m] = 50 if i % 2 else 400
    return img, labels


real_data = pytest.mark.skipif(not os.path.isdir(os.path.join(TEST_IMAGES, "lbl")), reason="test images not available")
