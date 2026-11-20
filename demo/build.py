"""Build the interactive dashboard demo (``demo/demo.html`` + ``demo/static/``) from the real dashboard, ``interface/web_ui_v2.html``.
``demo/index.html`` is the hand-written landing page (features, preview, who built it) and is not generated.

    python demo/build.py            # regenerate
    python demo/build.py --check    # exit 1 if demo/demo.html is out of date (used by a test)

What the demo is: the same Home + Settings page, always in sample-data mode, with scripted replies (``demo.js``).
What it is not: it never connects anywhere (the Content-Security-Policy forbids all network requests), carries no
token or key, and leaves out the 3D "vision mode" orb overlay and the local-server scripts entirely.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE = ROOT / "interface" / "web_ui_v2.html"
THUMBS = ROOT / "interface" / "static"

CSP = ("default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'")        # frame-ancestors only works as a header: see _headers
ICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Crect width='24' height='24' rx='6' fill='%23168bff'/%3E"
        "%3Cpath d='M12 4L5 20h3.6L12 12.6 15.4 20H19z' fill='white'/%3E%3C/svg%3E")
EXTRA_HEAD = """<meta name="description" content="Flexie OS: a voice and text desktop AI assistant for Windows. This is a demo of its dashboard with sample data.">
<meta property="og:title" content="Flexie OS (demo)">
<meta property="og:description" content="Live demo of the Flexie OS dashboard: system health, activity, AI providers, behavior, memory and orb styles. Sample data only.">
<meta name="robots" content="index,follow">
<link rel="icon" href="__ICON__">
<style>
.demo-pill{padding:7px 14px;border-radius:20px;border:1px solid color-mix(in srgb,var(--orange) 55%,transparent);background:color-mix(in srgb,var(--orange) 12%,transparent);color:var(--orange);font-size:13px;font-weight:600;white-space:nowrap}
.demo-back{display:flex;align-items:center;gap:8px;padding:11px 14px;border:1px solid var(--border);border-radius:14px;color:var(--muted);text-decoration:none;font-size:14px;margin-top:6px}
.demo-back:hover{color:var(--tx);border-color:var(--cyan)}
@media(max-width:767px){.demo-pill{display:none}}
</style>""".replace("__ICON__", ICON)


def _once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"build.py: expected exactly one occurrence of {old[:70]!r} in {SOURCE.name}, found {text.count(old)}")
    return text.replace(old, new, 1)


def render() -> str:
    html = SOURCE.read_text(encoding="utf-8")
    html, n = re.subn(r"<!-- Same policy as the classic dashboard.*?-->\s*<meta http-equiv=\"Content-Security-Policy\"[^>]*>", f'<meta http-equiv="Content-Security-Policy" content="{CSP}">', html, count=1, flags=re.S)
    if n != 1:
        raise SystemExit("build.py: could not find the Content-Security-Policy block")
    html = _once(html, '<link rel="stylesheet" href="/static/panels.css">\n<link rel="stylesheet" href="/static/orb.css">\n', "")
    html = _once(html, "<title>Flexie OS</title>", "<title>Flexie OS (demo)</title>\n" + EXTRA_HEAD)
    html = _once(html, "DEMO = /[?&]demo=1/.test(location.search);", "DEMO = true;   /* demo build: always sample data, never connects anywhere */")
    html = _once(html, "'/static/orb-thumb-'", "'static/orb-thumb-'")
    # the "classic dashboard" links point at a page that only exists on a real PC: send them to the landing page instead
    html = _once(html, '<button role="menuitem" id="uClassic">Open classic dashboard</button>', '<button role="menuitem" id="uClassic">About Flexie</button>')
    html = _once(html, "location.href = '/classic';", "location.href = 'index.html';")
    html = re.sub(r'<a class="btn" href="/classic"([^>]*)>Open classic dashboard</a>', r'<a class="btn" href="index.html">About Flexie</a>', html)
    if "/classic" in html.replace("'Open mail in the classic dashboard'", ""):
        raise SystemExit("build.py: a /classic link is left in the demo")
    # a public demo must not carry the real owner's name: neutral sample identity and sample memory
    html = _once(html, '<i id="userI">DN</i><span id="userN">Dhanush N</span>', '<i id="userI">DU</i><span id="userN">Demo User</span>')
    html = _once(html, "text: 'Name is Dhanush'", "text: 'Name is Sam'")
    html = _once(html, '<script src="/static/panels.js" defer></script>\n<script src="/static/orb-panel.js" defer></script>\n', '<script src="demo.js"></script>\n')
    return html


def sync_assets() -> list[str]:
    out = HERE / "static"
    out.mkdir(exist_ok=True)
    copied = []
    for png in sorted(THUMBS.glob("orb-thumb-*.png")):
        shutil.copyfile(png, out / png.name)
        copied.append(png.name)
    return copied


def main(argv: list[str]) -> int:
    html = render()
    target = HERE / "demo.html"
    if "--check" in argv:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current != html:
            print("demo/demo.html is out of date. Run: python demo/build.py")
            return 1
        print("demo/demo.html is up to date")
        return 0
    target.write_text(html, encoding="utf-8", newline="\n")
    names = sync_assets()
    print(f"wrote {target.relative_to(ROOT)} ({len(html):,} bytes) and {len(names)} orb thumbnails")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
