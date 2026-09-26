# syntax=docker/dockerfile:1.7
# NucleiQuant development image
# Base: NVIDIA NGC TensorFlow 25.02 (TensorFlow 2.17.0, CUDA 12.8, cuDNN 9.7, Python 3.12)
# Blackwell-optimized since NGC 25.01 -- tested on an RTX 5070 Ti (compute capability 12.0):
# the shipped model reproduces its own label counts to within 3 nuclei out of 38,841.
#
# An older, "version-matched" base (NGC 21.03-tf2-py3, TF 2.4.0 -- the version the
# model was actually trained with) was tried first and hangs indefinitely running a
# convolution on Blackwell GPUs: its cuDNN build predates that architecture entirely.
# This image trades exact environment reproduction for one that actually runs, and
# empirically reproduces the original model's output almost exactly (see above).

FROM nvcr.io/nvidia/tensorflow:25.02-tf2-py3

LABEL project="nucleiquant"
LABEL description="Organoid nuclei segmentation and cell-type quantification pipeline"
LABEL maintainer="Julien Pigeon"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# numba compiles the feature kernels once; the launcher points this at a
# persistent folder on the host so it only happens on first use
ENV NUMBA_CACHE_DIR=/tmp/numba_cache
ENV TF_CPP_MIN_LOG_LEVEL=2
# oneDNN makes CPU-only segmentation ~350x slower in this TensorFlow build
ENV TF_ENABLE_ONEDNN_OPTS=0

# libgl1, libglib2.0-0 -> runtime deps for scikit-image / opencv-style image I/O
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /workspace

# Copy only the dependency manifest and the small shared package for layer caching.
# The rest of the project (notebooks, scripts, data) is mounted at runtime via -v,
# not copied into the image -- so editing a notebook never requires a rebuild.
COPY pyproject.toml LICENSE Readme.md /workspace/
COPY nucleiquant /workspace/nucleiquant

# --system                : target the container's system interpreter (no venv)
# --break-system-packages : allow overwriting NGC's preinstalled packages where pinned
# -e .                    : editable install, so `import nucleiquant` works against
#                            the live, mounted copy of the package too
RUN uv pip install --system --break-system-packages --no-cache-dir -e ".[dev]"

EXPOSE 8888 8765

CMD ["/bin/bash"]
