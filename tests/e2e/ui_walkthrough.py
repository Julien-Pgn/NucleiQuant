"""Automated walkthrough of the NucleiQuant app in a real (headless) browser.

Drives the six steps like a user and saves screenshots for the docs.
Runs in the Playwright container against a running app (see
tests/e2e/run_walkthrough.sh). Part 1 goes up to the Label screen; labels
are then seeded from V1 (seed_labels_from_v1.py); part 2 continues.

    python tests/e2e/ui_walkthrough.py --part 1
    python tests/e2e/ui_walkthrough.py --part 2
"""

import argparse
import os
import sys

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("NQ_URL", "http://localhost:8765")
SHOTS = os.environ.get("NQ_SHOTS", "docs/images")
ROOT = os.environ.get("NQ_ROOT_NAME", "/workspace")
NAME = os.environ.get("NQ_PROJECT", "ui-walkthrough")
errors = []


def shot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    page.wait_for_timeout(400)
    page.screenshot(path=os.path.join(SHOTS, f"{name}.png"))
    print("screenshot", name, flush=True)


def new_page(pw):
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page.on("console", lambda m: (print("console", m.type, m.text), errors.append(m.text)) if m.type == "error" else None)
    page.on("pageerror", lambda e: (print("PAGE ERROR", e), errors.append(str(e))))
    page.set_default_timeout(30000)
    return browser, page


def part1(page):
    page.goto(BASE)
    expect(page.get_by_role("heading", name="NucleiQuant")).to_be_visible()
    page.wait_for_timeout(2500)  # GPU detection
    shot(page, "01-home")

    page.get_by_role("button", name="New project").click()
    page.get_by_role("button", name=ROOT).click()
    page.get_by_role("button", name="img_test_pipeline").click()
    expect(page.get_by_text("12 TIFF images here")).to_be_visible()
    shot(page, "01b-folder-picker")
    page.get_by_role("button", name="Use this folder").click()
    page.get_by_label("Project name").fill(NAME)
    page.get_by_role("button", name="Create project").click()
    expect(page.get_by_role("heading", name="Project", exact=True)).to_be_visible()

    for i, name in ((2, "488"), (3, "555"), (4, "647")):
        box = page.get_by_label(f"Channel {i} name")
        box.fill(name)
        box.press("Tab")
        page.wait_for_timeout(300)
    geno = page.get_by_label("Genotype of clone Pa")
    geno.fill("WT/WT")
    geno.press("Tab")
    page.wait_for_timeout(500)
    shot(page, "02-project")

    page.get_by_role("button", name="Continue").click()
    expect(page.get_by_text("Mean intensity inside nuclei, per image")).to_be_visible(timeout=120000)
    shot(page, "03-survey")

    page.get_by_role("button", name="Create 3 crops").click()
    expect(page.get_by_role("heading", name="Training crops")).to_be_visible()
    page.wait_for_timeout(6000)
    shot(page, "04a-crops-running")
    expect(page.get_by_role("button", name="Start labeling")).to_be_enabled(timeout=300000)
    page.wait_for_timeout(1500)
    shot(page, "04-crops")

    page.get_by_role("button", name="Start labeling").click()
    expect(page.get_by_role("heading", name="Label cells")).to_be_visible()
    for name in ("S", "N", "T"):
        page.get_by_role("button", name="Add", exact=True).click()
        if name == "S":
            # Pick the category colour from the channel colours (S is seen in the 488 channel)
            page.get_by_role("button", name="Choose a colour").click()
            page.wait_for_timeout(300)
            shot(page, "05c-colour-picker")
            page.get_by_role("button", name="488 (#40FF73)").click()
        page.get_by_placeholder("Category name, e.g. PAX6+").fill(name)
        page.get_by_placeholder("Category name, e.g. PAX6+").press("Enter")
        page.wait_for_timeout(400)
    colours = page.evaluate("() => fetch('/api/state').then(r => r.json()).then(s => s.project.categories.map(c => [c.name, c.color]))")
    assert ["S", "#40FF73"] in colours, colours
    shot(page, "05a-label-empty")


def click_nucleus(page, category_key, avoid=()):
    """Click the centre of a labelable nucleus via the viewer's own geometry."""
    pos = page.evaluate("""(avoid) => {
      const v = window.nqViewer; const d = v.data; const o = v.outlines;
      const { zoom, tx, ty } = v.view;
      for (let i = 0; i < o.ids.length; i++) {
        const lab = o.ids[i];
        if (avoid.includes(lab)) continue;
        const cx = (o.bb[4*i] + o.bb[4*i+2]) / 2, cy = (o.bb[4*i+1] + o.bb[4*i+3]) / 2;
        const sx = cx * zoom + tx, sy = cy * zoom + ty;
        if (sx < 60 || sy < 60 || sx > v.cw - 60 || sy > v.ch - 60) continue;
        if (d.labels[Math.floor(cy) * d.W + Math.floor(cx)] !== lab) continue;
        const r = v.el.getBoundingClientRect();
        return { x: r.left + sx, y: r.top + sy, lab };
      }
      return null;
    }""", list(avoid))
    page.keyboard.press(category_key)
    page.mouse.click(pos["x"], pos["y"])
    return pos["lab"]


def part2(page):
    page.goto(BASE + "/#/label")
    expect(page.get_by_role("heading", name="Label cells")).to_be_visible()
    page.wait_for_timeout(2500)
    # Zoom into the crop centre like a user would, then label two nuclei by clicking
    viewer = page.get_by_label("Image viewer")
    box = viewer.bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.5)
    for _ in range(5):
        page.mouse.wheel(0, -150)
        page.wait_for_timeout(120)
    page.wait_for_timeout(800)
    before = page.evaluate("() => fetch('/api/state').then(r => r.json()).then(s => s.labels.total)")
    a = click_nucleus(page, "3")
    page.wait_for_timeout(500)
    b = click_nucleus(page, "4", avoid=[a])
    page.wait_for_timeout(800)
    after = page.evaluate("() => fetch('/api/state').then(r => r.json()).then(s => s.labels.total)")
    assert after == before + 2, f"clicking should add 2 labels ({before} -> {after})"
    page.mouse.click(0, 0)  # move the pointer away (no hover outline in the screenshot)
    page.mouse.move(box["x"] + 20, box["y"] + box["height"] - 140)
    shot(page, "05-label")
    # Undo them with a right-click on the same nuclei to test erasing
    for lab in (a, b):
        pos = page.evaluate("""(lab) => { const v = window.nqViewer; const o = v.outlines; const i = o.index[lab];
          const cx = (o.bb[4*i] + o.bb[4*i+2]) / 2, cy = (o.bb[4*i+1] + o.bb[4*i+3]) / 2; const r = v.el.getBoundingClientRect();
          return { x: r.left + cx * v.view.zoom + v.view.tx, y: r.top + cy * v.view.zoom + v.view.ty }; }""", lab)
        page.mouse.click(pos["x"], pos["y"], button="right")
        page.wait_for_timeout(300)
    page.wait_for_timeout(600)
    back = page.evaluate("() => fetch('/api/state').then(r => r.json()).then(s => s.labels.total)")
    assert back == before, f"right-click should remove the labels ({back} != {before})"

    page.get_by_role("button", name="Preview classification").click()
    if page.get_by_role("button", name="Preview anyway").count():
        shot(page, "05b-unused-warning")
        page.get_by_role("button", name="Preview anyway").click()
    expect(page.get_by_role("heading", name="Preview", exact=True)).to_be_visible(timeout=180000)
    page.wait_for_timeout(3000)
    viewer = page.get_by_label("Image viewer")
    box = viewer.bounding_box()
    page.mouse.move(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.5)
    for _ in range(5):
        page.mouse.wheel(0, -150)
        page.wait_for_timeout(120)
    page.mouse.move(box["x"] + 20, box["y"] + box["height"] - 140)
    page.wait_for_timeout(800)
    shot(page, "06-preview")
    page.get_by_role("button", name="Where it gets confused").click()
    page.wait_for_timeout(400)
    shot(page, "06b-preview-confusion")

    page.get_by_role("button", name="Classify all 12 images").click()
    expect(page.get_by_role("heading", name="Classifying all images")).to_be_visible()
    page.wait_for_timeout(15000)
    shot(page, "07-running")
    expect(page.get_by_role("link", name="Download Excel")).to_be_visible(timeout=1200000)
    page.wait_for_timeout(2000)
    shot(page, "08-results")
    # 100 % = stained cells, then a custom 100 % (S + N) saved in the Excel file
    page.get_by_role("button", name="Stained cells").click()
    page.wait_for_timeout(1500)
    expect(page.get_by_text("100 % = stained cells")).to_be_visible()
    shot(page, "08b-results-stained")
    page.get_by_title("Leave T out of the 100 %").click()
    page.wait_for_timeout(1500)
    expect(page.get_by_text("100 % = S + N")).to_be_visible()
    page.get_by_role("button", name="Save in Excel").click()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("In the Excel file")).to_be_visible(timeout=60000)
    shot(page, "08c-results-custom")
    refs = page.evaluate("() => fetch('/api/results').then(r => r.json()).then(r => r.references.map(x => x.name))")
    assert "S + N" in refs, refs
    page.get_by_role("link", name="View").first.click()
    expect(page.get_by_role("link", name="Back to results")).to_be_visible()
    page.wait_for_timeout(6000)
    shot(page, "09-image-view")


def part3(page):
    """Test step: create the test crops (labels are seeded next)."""
    page.goto(BASE + "/#/test")
    expect(page.get_by_role("heading", name="Test set")).to_be_visible()
    page.wait_for_timeout(800)
    shot(page, "10b-test-intro")
    page.get_by_role("button", name="Create test crops").click()
    expect(page.get_by_role("button", name="Evaluate accuracy")).to_be_visible(timeout=300000)
    expect(page.get_by_text("Test crop 1 of")).to_be_visible(timeout=60000)
    page.wait_for_timeout(1000)
    # Blind: the prediction legend is never shown in test mode
    assert page.locator(".legend-item:visible").count() == 0


def part4(page):
    """Evaluate the seeded test labels and check the report."""
    page.goto(BASE + "/#/test")
    expect(page.get_by_role("button", name="Evaluate accuracy")).to_be_visible()
    page.wait_for_timeout(2500)
    shot(page, "10c-test-labels")
    page.get_by_role("button", name="Evaluate accuracy").click()
    if page.get_by_role("button", name="Evaluate anyway").count():
        page.get_by_role("button", name="Evaluate anyway").click()
    expect(page.get_by_role("heading", name="Test accuracy")).to_be_visible(timeout=120000)
    expect(page.get_by_text("Balanced accuracy").first).to_be_visible()
    page.wait_for_timeout(800)
    shot(page, "11-test-report")
    page.goto(BASE + "/#/results")
    expect(page.get_by_text("Test accuracy").first).to_be_visible(timeout=30000)
    page.wait_for_timeout(1500)
    shot(page, "08-results")
    page.get_by_role("button", name="Help").click()
    page.wait_for_timeout(1500)
    shot(page, "10-help")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", type=int, required=True)
    args = ap.parse_args()
    with sync_playwright() as pw:
        browser, page = new_page(pw)
        try:
            {1: part1, 2: part2, 3: part3, 4: part4}[args.part](page)
        except Exception:
            shot(page, f"failure-part{args.part}")
            raise
        finally:
            browser.close()
    if errors:
        print("Browser errors:", *errors, sep="\n  ")
        sys.exit(1)
    print(f"Part {args.part} OK")


if __name__ == "__main__":
    main()
