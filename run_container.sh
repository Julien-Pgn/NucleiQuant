#!/usr/bin/env bash
# NucleiQuant container launcher.
# Usage: ./run_container.sh <mode> [args...]
# Modes:
#   shell                  interactive bash inside the container, with GPU (default)
#   shell_cpu              interactive bash inside the container, CPU only
#   exec <cmd> [args...]   run a single command with GPU, e.g. exec python scripts/01_segmentation.py
#   exec_cpu <cmd> [args...]   same, without GPU
#   jupyter                 start JupyterLab on http://localhost:8888 (detached, GPU)
#   jupyter_cpu              same, without GPU
#   app                      start the NucleiQuant app on http://localhost:8765 (GPU)
#   app_cpu                  same, without GPU
#   test                     run the test suite (pytest)
#   stop                     stop and remove the jupyter daemon and the app
#   logs                     follow logs from the jupyter daemon
#   build                    build the image
#   help                     show this message
#
# Only the repo folder is mounted into the container by default (as /workspace),
# so an --images path has to live somewhere under the repo. To segment images
# that live elsewhere on your machine instead, set IMAGES_DIR and use /data:
#   IMAGES_DIR=/home/jul/Téléchargements/my_images ./run_container.sh exec \
#       python scripts/01_segmentation.py --images /data

set -euo pipefail

IMAGE="nucleiquant:v2"

# Common flags for every mode. GPU access is added per-mode below, not here,
# so CPU-only runs never need the NVIDIA Container Toolkit at all.
# --user + HOME: the container image runs as root by default, which would make
# every output file (labels, ROIs, notebook saves) root-owned on the host.
# Running as your own uid/gid instead means files land owned by you, as normal.
COMMON_FLAGS=(
    --ipc=host
    --ulimit memlock=-1
    --ulimit stack=67108864
    --shm-size=8g
    --user "$(id -u):$(id -g)"
    -e "HOME=/tmp"
    -v "$(pwd):/workspace"
    -e "PYTHONDONTWRITEBYTECODE=1"
    -w /workspace
)

# Optional: mount a folder from anywhere on your machine at /data, for images
# that don't live inside the repo (see IMAGES_DIR usage note above).
if [ -n "${IMAGES_DIR:-}" ]; then
    COMMON_FLAGS+=(-v "${IMAGES_DIR}:/data")
fi

mode="${1:-shell}"

case "$mode" in

    shell)
        docker run --rm -it --gpus all "${COMMON_FLAGS[@]}" "$IMAGE" bash
        ;;

    shell_cpu)
        docker run --rm -it "${COMMON_FLAGS[@]}" "$IMAGE" bash
        ;;

    exec)
        shift
        if [ $# -eq 0 ]; then
            echo "exec requires a command, e.g. ./run_container.sh exec python scripts/01_segmentation.py" >&2
            exit 1
        fi
        docker run --rm --gpus all "${COMMON_FLAGS[@]}" "$IMAGE" "$@"
        ;;

    exec_cpu)
        shift
        if [ $# -eq 0 ]; then
            echo "exec_cpu requires a command" >&2
            exit 1
        fi
        docker run --rm "${COMMON_FLAGS[@]}" "$IMAGE" "$@"
        ;;

    # "jupyter" starts JupyterLab in detached mode, mapping port 8888 to the host,
    # with no token for easy local access. Stop with "stop", follow logs with "logs".
    jupyter)
        docker rm -f nucleiquant-jupyter >/dev/null 2>&1 || true
        docker run -d --name nucleiquant-jupyter \
            --gpus all \
            "${COMMON_FLAGS[@]}" \
            -p 127.0.0.1:8888:8888 \
            "$IMAGE" \
            jupyter lab \
                --ip=0.0.0.0 --port=8888 --no-browser --allow-root \
                --IdentityProvider.token=''
        echo "JupyterLab: http://localhost:8888"
        echo "Stop with:  ./run_container.sh stop"
        echo "Logs with:  ./run_container.sh logs"
        ;;

    jupyter_cpu)
        docker rm -f nucleiquant-jupyter >/dev/null 2>&1 || true
        docker run -d --name nucleiquant-jupyter \
            "${COMMON_FLAGS[@]}" \
            -p 127.0.0.1:8888:8888 \
            "$IMAGE" \
            jupyter lab \
                --ip=0.0.0.0 --port=8888 --no-browser --allow-root \
                --IdentityProvider.token=''
        echo "JupyterLab: http://localhost:8888"
        echo "Stop with:  ./run_container.sh stop"
        echo "Logs with:  ./run_container.sh logs"
        ;;

    # "app" starts the V2 app. Most users should double-click start-nucleiquant.sh
    # instead, which also opens the browser and gives the app access to your home folder.
    app|app_cpu)
        docker rm -f nucleiquant-app >/dev/null 2>&1 || true
        gpu=(); [ "$mode" = "app" ] && gpu=(--gpus all)
        docker run -d --rm --name nucleiquant-app \
            ${gpu[@]+"${gpu[@]}"} \
            "${COMMON_FLAGS[@]}" \
            -e NQ_STATE_DIR=/workspace/.nucleiquant \
            -e NUMBA_CACHE_DIR=/workspace/.nucleiquant/numba_cache \
            -p 127.0.0.1:8765:8765 \
            "$IMAGE" \
            python -m nucleiquant serve --host 0.0.0.0 --port 8765
        echo "NucleiQuant: http://localhost:8765"
        echo "Stop with:   ./run_container.sh stop"
        ;;

    test)
        docker run --rm "${COMMON_FLAGS[@]}" -e NUMBA_CACHE_DIR=/tmp/numba_cache "$IMAGE" python -m pytest -q
        ;;

    stop)
        docker rm -f nucleiquant-jupyter >/dev/null 2>&1 \
            && echo "Stopped nucleiquant-jupyter" \
            || echo "nucleiquant-jupyter was not running"
        docker rm -f nucleiquant-app >/dev/null 2>&1 \
            && echo "Stopped nucleiquant-app" \
            || echo "nucleiquant-app was not running"
        ;;

    logs)
        docker logs -f nucleiquant-jupyter
        ;;

    build)
        docker build -t "$IMAGE" .
        ;;

    help|-h|--help)
        sed -n '2,18p' "$0"
        ;;

    *)
        echo "Unknown mode: $mode" >&2
        echo "Run './run_container.sh help' for usage." >&2
        exit 1
        ;;
esac
