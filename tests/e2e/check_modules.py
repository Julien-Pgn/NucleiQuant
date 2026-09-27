"""Import every frontend module in headless Chromium and report syntax/import errors.

There is no Node.js here; the browser itself is the syntax checker. Needs a running app:
    docker run --rm --network host -v "$PWD:/workspace" -w /workspace nucleiquant-e2e:1.52 \
        python tests/e2e/check_modules.py
"""

import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("NQ_URL", "http://localhost:8765")
STATIC = os.path.join(os.path.dirname(__file__), "..", "..", "nucleiquant", "app", "static", "js")


def main():
    files = sorted(os.path.relpath(os.path.join(d, f), STATIC)
                   for d, _, fs in os.walk(STATIC) for f in fs if f.endswith(".js"))
    bad = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(f"{BASE}/api/health")
        for f in files:
            r = page.evaluate("async (u) => { try { await import(u); return 'ok'; } catch (e) { return String(e); } }",
                              f"{BASE}/static/js/{f}")
            print(f"{f:28s} {r}")
            bad += r != "ok"
        browser.close()
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
