"""Render the classic orb and the new HUD orb side by side, in several states, to orb_preview.png.

    python tools/preview_orb.py
Needs no running Flexie and no screen (Qt offscreen). Loads the Windows Segoe UI fonts when present so the
labels are legible in the headless renderer.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFontDatabase, QPainter, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
for f in ("segoeui.ttf", "segoeuil.ttf", "seguisym.ttf", "segoeuib.ttf"):
    path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", f)
    if os.path.exists(path):
        QFontDatabase.addApplicationFont(path)
from PyQt6.QtGui import QFont  # noqa: E402

from interface.orb_v2 import HudFlexieOrb  # noqa: E402
from interface.orb_variants import STYLES, VariantOrb  # noqa: E402
from interface.ui import EnhancedFlexieOrb  # noqa: E402

BG = QColor(4, 6, 10)
STATE = os.environ.get("ORB_STATE", "SPEAKING")


def settle(orb, state):
    orb.set_state(state)
    for anim in (orb.wake_seq, orb.view_anim, orb.eye_anim, orb.color_anim, orb.burst_anim):
        anim.stop()
    orb._wake_burst = 0.0
    orb._color_blend = 1.0
    orb._accent_from, orb._secondary_from = orb._accent_to, orb._secondary_to
    orb._view_scale = 1.0
    orb._eye_openness = 1.0
    orb._scale = 1.0
    for _ in range(90):
        orb._update_anim()


def shot(make, state):
    orb = make()
    orb.allow_blink = False
    orb.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    orb.show()
    settle(orb, state)
    pm = QPixmap(300, 300)
    pm.fill(BG)
    painter = QPainter(pm)
    orb.render(painter)
    painter.end()
    orb.timer.stop()
    orb.hide()
    return pm


CELLS = [("1  classic (current)", EnhancedFlexieOrb), ("2  hud  (FLEXIE_ORB_STYLE=hud)", HudFlexieOrb)]
CELLS += [(f"{i + 3}  {name}", (lambda n=name: VariantOrb(n))) for i, name in enumerate(STYLES)]
COLS, LABEL_H = 5, 26
rows = -(-len(CELLS) // COLS)
out = QPixmap(300 * COLS, (300 + LABEL_H) * rows)
out.fill(BG)
painter = QPainter(out)
font = QFont("Segoe UI", 10)
font.setBold(True)
painter.setFont(font)
for n, (label, make) in enumerate(CELLS):
    x, y = (n % COLS) * 300, (n // COLS) * (300 + LABEL_H)
    painter.drawPixmap(x, y + LABEL_H, shot(make, STATE))
    painter.setPen(QColor(235, 240, 250))
    painter.drawText(x + 10, y + 18, label)
painter.end()
# thumbnails for the dashboard's Settings > Appearance picker (interface/static/orb-thumb-<style>.png)
THUMBS = [("classic", EnhancedFlexieOrb), ("hud", HudFlexieOrb)] + [(n, (lambda n=n: VariantOrb(n))) for n in STYLES]
for name, make in THUMBS:
    shot(make, STATE).scaled(180, 180, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).save(
        os.path.join(ROOT, "interface", "static", f"orb-thumb-{name}.png"))
path = os.path.join(ROOT, "orb_gallery_floating.png")
out.save(path)
print(path)
os._exit(0)
