"""Render tools/web_orb_gallery.html (eight web-orb shader designs) to orb_gallery_web.png with headless Chromium."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as pw:
    browser = pw.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
    page = browser.new_page(viewport={"width": 1680, "height": 892})
    page.goto("file:///" + os.path.join(ROOT, "tools", "web_orb_gallery.html").replace("\\", "/"))
    page.wait_for_timeout(1500)
    logs = page.evaluate("window.__logs")
    for line in logs:
        print("SHADER ERROR:", line[:300])
    out = os.path.join(ROOT, "orb_gallery_web.png")
    page.screenshot(path=out)
    browser.close()
print(out, flush=True)
os._exit(1 if logs else 0)
