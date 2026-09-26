#!/usr/bin/env bash
# Drive the running app in a headless browser (Playwright) through all six steps
# and regenerate the documentation screenshots in docs/images/.
# Start the app first (./run_container.sh app), then run this from the repo root.
set -euo pipefail
cd "$(dirname "$0")/../.."
URL="${NQ_URL:-http://localhost:8765}"
PROJECT="${NQ_PROJECT:-ui-walkthrough}"
PW_IMAGE="nucleiquant-e2e:1.52"

docker image inspect "$PW_IMAGE" >/dev/null 2>&1 || docker build -t "$PW_IMAGE" tests/e2e
rm -rf "img_test_pipeline/NucleiQuant_projects/${PROJECT}"
pw() {
    docker run --rm --network host --user "$(id -u):$(id -g)" -e HOME=/tmp \
        -e NQ_URL="$URL" -e NQ_PROJECT="$PROJECT" -e NQ_SHOTS=/workspace/docs/images \
        -e NQ_ROOT_NAME="${NQ_ROOT_NAME:-/workspace}" \
        -v "$PWD:/workspace" -w /workspace "$PW_IMAGE" python tests/e2e/ui_walkthrough.py --part "$1"
}
pw 1
# Realistic labels from V1's ilastik predictions (55 per category), through the app's API
docker run --rm --network host --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD:/workspace" -w /workspace \
    nucleiquant:v2 python scripts/validation/seed_labels_from_v1.py --url "$URL" --per-category 55 2>&1 | grep -E "Seeded|Error|Traceback" || true
pw 2
