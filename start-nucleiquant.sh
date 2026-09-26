#!/usr/bin/env bash
# NucleiQuant launcher for Linux and macOS.
# Double-click it (or run ./start-nucleiquant.sh). It checks Docker, prepares
# the app the first time, starts it and opens it in your browser.
# Closing the app: use the Quit button in the app (or Ctrl+C here).

set -uo pipefail

APP_NAME="NucleiQuant"
IMAGE_LOCAL="nucleiquant:v2"
IMAGE_REMOTE="ghcr.io/julien-pgn/nucleiquant:2.0"
CONTAINER="nucleiquant-app"
PORT="${NQ_PORT:-8765}"
URL="http://localhost:${PORT}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS="$(uname -s)"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
fail() {
    printf '\n\033[31m%s\033[0m\n' "$*"
    # Keep the window open when started by double-click
    if [ -t 0 ]; then read -r -p "Press Enter to close this window." _; fi
    exit 1
}

say "Starting ${APP_NAME}"

# ---- 1. Docker ---------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
    fail "Docker is not installed. Install Docker Desktop (https://www.docker.com/products/docker-desktop/), start it, then run this again."
fi
if ! docker info >/dev/null 2>&1; then
    if [ "$OS" = "Darwin" ]; then
        info "Starting Docker Desktop..."
        open -a Docker >/dev/null 2>&1 || true
    fi
    for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
    docker info >/dev/null 2>&1 || fail "Docker is installed but not running. Start Docker Desktop (or the docker service), wait until it's ready, then run this again."
fi

# Already running? Just open it.
if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    info "${APP_NAME} is already running."
    IMAGE=""
else
    # ---- 2. The app image (first time only) --------------------------------------------
    IMAGE="$IMAGE_LOCAL"
    if ! docker image inspect "$IMAGE_LOCAL" >/dev/null 2>&1; then
        if docker image inspect "$IMAGE_REMOTE" >/dev/null 2>&1 || docker pull "$IMAGE_REMOTE" 2>/dev/null; then
            IMAGE="$IMAGE_REMOTE"
        else
            say "First start: preparing ${APP_NAME} (one time, about 10 GB, 10-30 min)"
            docker build -t "$IMAGE_LOCAL" "$REPO" || fail "Preparing the app failed. Check your internet connection and free disk space (~30 GB), then try again."
        fi
    fi

    # ---- 3. GPU? --------------------------------------------------------------------------
    GPU_FLAGS=()
    if [ "$OS" = "Linux" ] && command -v nvidia-smi >/dev/null 2>&1; then
        if docker run --rm --gpus all "$IMAGE" nvidia-smi -L >/dev/null 2>&1; then
            GPU_FLAGS=(--gpus all)
            info "NVIDIA GPU found: segmentation will be fast."
        else
            info "An NVIDIA GPU is present but Docker can't use it (the NVIDIA Container Toolkit enables it). Using the CPU."
        fi
    else
        info "No NVIDIA GPU: using the CPU (works well, a little slower)."
    fi

    # ---- 4. Folders the app may open ---------------------------------------------------------
    MOUNTS=(-v "$REPO:/workspace" -v "$HOME:$HOME")
    ROOTS="$HOME"
    for extra in /media /mnt /Volumes /data; do
        if [ -d "$extra" ] && [ "$extra" != "$HOME" ]; then
            MOUNTS+=(-v "$extra:$extra")
            ROOTS="$ROOTS:$extra"
        fi
    done
    STATE_DIR="$HOME/.nucleiquant"
    mkdir -p "$STATE_DIR/numba_cache"
    USER_FLAGS=()
    if [ "$OS" = "Linux" ]; then
        USER_FLAGS=(--user "$(id -u):$(id -g)")  # files you create stay yours
    fi
    TZ_NAME="${TZ:-$(cat /etc/timezone 2>/dev/null || readlink /etc/localtime 2>/dev/null | sed 's#.*/zoneinfo/##')}"

    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    say "Launching"
    docker run -d --rm --name "$CONTAINER" \
        ${GPU_FLAGS[@]+"${GPU_FLAGS[@]}"} ${USER_FLAGS[@]+"${USER_FLAGS[@]}"} \
        --ipc=host --shm-size=4g \
        -p "127.0.0.1:${PORT}:8765" \
        "${MOUNTS[@]}" \
        -e HOME=/tmp \
        -e TZ="$TZ_NAME" \
        -e NQ_ROOTS="$ROOTS" \
        -e NQ_HOME="$HOME" \
        -e NQ_STATE_DIR="$STATE_DIR" \
        -e NUMBA_CACHE_DIR="$STATE_DIR/numba_cache" \
        -e TF_CPP_MIN_LOG_LEVEL=3 \
        -w /workspace \
        "$IMAGE" python -m nucleiquant serve --host 0.0.0.0 --port 8765 >/dev/null \
        || fail "The app could not start. Is port ${PORT} used by another program? (set NQ_PORT=8766 to use another)"
fi

# ---- 5. Open the browser -----------------------------------------------------------------------
for _ in $(seq 1 60); do
    curl -fs "$URL/api/health" >/dev/null 2>&1 && break
    sleep 1
done
curl -fs "$URL/api/health" >/dev/null 2>&1 || fail "The app did not answer. See: docker logs $CONTAINER"

say "${APP_NAME} is ready: ${URL}"
if [ -z "${NQ_NO_BROWSER:-}" ]; then
    if [ "$OS" = "Darwin" ]; then open "$URL"; else xdg-open "$URL" >/dev/null 2>&1 || true; fi
fi
info "Keep this window open while you work. Quit from the app (or press Ctrl+C here)."
if [ -n "${SSH_CONNECTION:-}" ]; then
    info "You are connected over SSH: the link works on your own computer once port ${PORT} is forwarded."
    info "  VS Code: PORTS tab > Forward a Port > ${PORT}"
    info "  Terminal on your computer: ssh -N -L ${PORT}:127.0.0.1:${PORT} ${USER}@$(echo "$SSH_CONNECTION" | awk '{print $3}')"
fi

# Add NucleiQuant to the Linux applications menu (once)
if [ "$OS" = "Linux" ] && [ -d "$HOME/.local/share/applications" ] && [ ! -f "$HOME/.local/share/applications/nucleiquant.desktop" ]; then
    cat > "$HOME/.local/share/applications/nucleiquant.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=NucleiQuant
Comment=Count cell types in fluorescence images
Exec=$REPO/start-nucleiquant.sh
Terminal=true
Categories=Science;Biology;
DESKTOP
    info "NucleiQuant was added to your applications menu."
fi

trap 'docker stop "$CONTAINER" >/dev/null 2>&1; say "Stopped."; exit 0' INT TERM
# Wait until the app is quit from the browser
while docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; do sleep 2; done
say "${APP_NAME} has stopped. You can close this window."
