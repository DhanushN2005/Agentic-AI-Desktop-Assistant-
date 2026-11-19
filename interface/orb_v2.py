"""Floating orb "HUD" - a glossy sphere inside a sci-fi instrument ring. Opt-in; the classic orb stays the default.

Drawn after the design reference: a glass sphere with a triangle mesh and a scan line, a dashed ring and
three thin concentric rings with orbiting dots, spectrum bars, drifting particles, live CPU / RAM / NET
readouts and an AI badge written along the outer ring, and the state in large thin letters underneath.

It subclasses EnhancedFlexieOrb so state handling, wake animation and signals are the same; only the drawing
(and the colour choice) is new. Idle / sleep / listening use the colour of the active mode; thinking is amber,
speaking magenta, errors red.

Try it:  FLEXIE_ORB_STYLE=hud python main.py        Preview (no Flexie needed):  python tools/preview_orb.py
"""
import math
import time

import psutil
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

from interface.ui import EnhancedFlexieOrb, FlexieConfig

STATUS = {"IDLE": ("READY", "FLEXIE IS READY"), "SLEEP": ("ASLEEP", "SAY HEY FLEXIE TO WAKE"),
          "MINIMIZED": ("ASLEEP", "SAY HEY FLEXIE TO WAKE"), "WAKE": ("LISTENING", "FLEXIE IS LISTENING"),
          "LISTENING": ("LISTENING", "FLEXIE IS LISTENING"), "PROCESSING": ("THINKING", "FLEXIE IS THINKING"),
          "SPEAKING": ("SPEAKING", "FLEXIE IS SPEAKING"), "SUCCESS": ("DONE", "ALL DONE"),
          "WARNING": ("HEADS UP", "FLEXIE NEEDS ATTENTION"), "ALERT": ("ALERT", "FLEXIE NEEDS ATTENTION"),
          "ERROR": ("ERROR", "SOMETHING WENT WRONG")}
STATE_RGB = {"PROCESSING": ("#FFB020", "#FF6A00"), "SPEAKING": ("#FF1493", "#B0006A"), "SUCCESS": ("#B070FF", "#6A2CC8"),
             "WARNING": ("#FF9A1F", "#FF4400"), "ALERT": ("#FF3B30", "#C00000"), "ERROR": ("#FF3B30", "#C00000")}
CX, CY = 150.0, 128.0          # sphere centre; room under it for the state title
TEAL = QColor(31, 168, 160)
CHECK, CROSS = "✓", "✗"


def _fmt_rate(bps):
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f}M"
    return f"{bps / 1000:.0f}K" if bps >= 1000 else f"{bps:.0f}B"


class HudFlexieOrb(EnhancedFlexieOrb):
    """Glass sphere + instrument rings. Drop-in replacement for EnhancedFlexieOrb."""

    ai_ok = True               # shown as "AI ✓" / "AI ✗" on the ring

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stats = {"cpu": 0.0, "ram": 0.0, "net": 0.0}
        self._stats_at = 0.0
        self._cpu_prev = None
        self._net_prev = None

    # ---- colours: mode colour while calm, fixed colours for the busy / alert states
    def mode_colors(self):
        cfg = FlexieConfig.MODES.get(str(self.mode).lower(), FlexieConfig.MODES["professional"])
        return QColor(cfg["accent"]), QColor(cfg.get("secondary", cfg["accent"]))

    def set_state(self, state):
        super().set_state(state)
        if self.state in STATE_RGB:
            a, b = STATE_RGB[self.state]
            self._accent_to, self._secondary_to = QColor(a), QColor(b)
        else:
            self._accent_to, self._secondary_to = self.mode_colors()

    # ---- live readouts, sampled once a second
    def _sample_stats(self, now):
        if now - self._stats_at < 1.0:
            return
        dt = now - self._stats_at if self._stats_at else 1.0
        self._stats_at = now
        try:
            ct = psutil.cpu_times()
            idle = ct.idle + getattr(ct, "iowait", 0.0)
            total = sum(ct) - getattr(ct, "guest", 0.0) - getattr(ct, "guest_nice", 0.0)
            if self._cpu_prev:
                didle, dtot = idle - self._cpu_prev[0], total - self._cpu_prev[1]
                if dtot > 0:
                    self._stats["cpu"] = max(0.0, min(100.0, 100.0 * (1.0 - didle / dtot)))
            self._cpu_prev = (idle, total)
            self._stats["ram"] = psutil.virtual_memory().percent
            io = psutil.net_io_counters()
            moved = io.bytes_sent + io.bytes_recv
            if self._net_prev is not None:
                self._stats["net"] = max(0.0, (moved - self._net_prev) / dt)
            self._net_prev = moved
        except Exception:
            pass

    # ---- paint
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = time.time()
        self._sample_stats(t)
        v = self._view_scale
        st = self.state
        scale = max(0.1, self._scale * v)
        acc = self._lerp_color(self._accent_from, self._accent_to, self._color_blend)
        sec = self._lerp_color(self._secondary_from, self._secondary_to, self._color_blend)
        mx = (self._mouse_pos.x() - 150.0) / 150.0
        my = (self._mouse_pos.y() - 150.0) / 150.0
        c = QPointF(CX + mx * 3, CY + my * 3)
        busy = st in ("LISTENING", "SPEAKING", "PROCESSING")
        speaking = st == "SPEAKING"

        def col(a, base=None):
            b = base or acc
            return QColor(b.red(), b.green(), b.blue(), max(0, min(255, int(a))))

        R = 50.0 * scale * (1.0 + (0.035 * math.sin(t * 7) if speaking else 0.012 * math.sin(t * 1.6)))

        halo = (150.0 + self._pulse) * scale                           # soft halo
        g = QRadialGradient(c, halo)
        g.setColorAt(0.0, col(95 * v * (0.55 + 0.45 * self._glow_intensity)))
        g.setColorAt(0.55, col(26 * v, sec))
        g.setColorAt(1.0, Qt.GlobalColor.transparent)
        p.setBrush(g)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(c, halo, halo)

        full = v > 0.55                                                # asleep / minimised: just the small sphere
        if full:
            self._draw_rings(p, c, t, v, st, busy, col)
            self._draw_bars(p, c, t, v, st, col)
            self._draw_particles(p, t, v, st, col)
        self._draw_sphere(p, c, R, t, v, acc, sec, col, full)
        if full:
            self._draw_labels(p, c, v)
            self._draw_title(p, v, st, acc)

    def _draw_rings(self, p, c, t, v, st, busy, col):
        p.setBrush(Qt.BrushStyle.NoBrush)
        for r, a in ((80, 60), (96, 50), (112, 44)):
            p.setPen(QPen(QColor(40, 150, 160, int(a * v)), 1.0))
            p.drawEllipse(c, r, r)
        spin = 70 if st == "PROCESSING" else 8                         # dashed ring: slow, fast while thinking
        p.save()
        p.translate(c)
        p.rotate(t * spin % 360)
        pen = QPen(col(110 * v), 1.1)
        pen.setDashPattern([2.0, 3.5])
        p.setPen(pen)
        p.drawEllipse(QPointF(0, 0), 66, 66)
        p.restore()
        sp = 1.8 if busy else 1.0                                      # orbiting dots: cyan, blue, violet
        for r, ang, rad, rgb in ((96, t * 0.55 * sp + 2.2, 4.2, (0, 220, 255)),
                                 (112, -t * 0.35 * sp + 4.6, 3.0, (20, 90, 255)),
                                 (80, t * 0.8 * sp + 0.6, 3.4, (170, 90, 255))):
            x, y = c.x() + math.cos(ang) * r, c.y() + math.sin(ang) * r
            gg = QRadialGradient(QPointF(x, y), rad * 3.2)
            gg.setColorAt(0, QColor(*rgb, int(150 * v)))
            gg.setColorAt(1, QColor(*rgb, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(gg)
            p.drawEllipse(QPointF(x, y), rad * 3.2, rad * 3.2)
            p.setBrush(QColor(*rgb, int(255 * v)))
            p.drawEllipse(QPointF(x, y), rad, rad)

    def _draw_bars(self, p, c, t, v, st, col):
        n = 72
        base = {"SPEAKING": 1.0, "LISTENING": 0.5, "PROCESSING": 0.6}.get(st, 0.12)
        for i in range(n):
            a = i / n * math.tau
            low = 0.2 + 0.8 * max(0.0, math.sin(a))                    # strongest along the lower arc (y is down)
            if st == "SPEAKING":
                val = abs(math.sin(t * 8 + i * 0.37)) * (0.55 + 0.45 * abs(math.sin(t * 3.1 + i)))
            elif st == "PROCESSING":
                val = 0.5 + 0.5 * math.sin(t * 5 + i * 0.5)
            else:
                val = 0.35 + 0.65 * abs(math.sin(t * 2.2 + i * 0.6))
            ln = 3 + 22 * val * low * base
            r0 = 70.0
            p.setPen(QPen(col(220 * v * (0.35 + 0.65 * low)), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(c.x() + math.cos(a) * r0, c.y() + math.sin(a) * r0),
                       QPointF(c.x() + math.cos(a) * (r0 + ln), c.y() + math.sin(a) * (r0 + ln)))

    def _draw_particles(self, p, t, v, st, col):
        count = {"SPEAKING": 46, "PROCESSING": 40, "LISTENING": 30}.get(st, 16)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(count):
            s1 = math.sin(i * 12.9898) * 43758.5453
            ph = s1 - math.floor(s1)
            s2 = math.sin(i * 78.233) * 12543.1
            ang = (s2 - math.floor(s2)) * math.tau
            life = (t * (0.07 + 0.08 * ph) + ph) % 1.0
            r = 62 + life * 82
            p.setBrush(col(math.sin(life * math.pi) * 200 * v))
            sz = 0.9 + 1.7 * ph
            p.drawEllipse(QPointF(CX + math.cos(ang + life * 0.7) * r, CY + math.sin(ang + life * 0.7) * r), sz, sz)

    def _draw_sphere(self, p, c, R, t, v, acc, sec, col, full):
        g = QRadialGradient(QPointF(c.x() - R * 0.30, c.y() - R * 0.34), R * 1.55)   # bright upper-left, dark rim
        g.setColorAt(0.00, col(255 * v, acc.lighter(165)))
        g.setColorAt(0.28, col(255 * v, acc))
        g.setColorAt(0.70, col(235 * v, sec))
        g.setColorAt(1.00, QColor(10, 4, 14, int(250 * v)))
        p.setBrush(g)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(c, R, R)
        clip = QPainterPath()
        clip.addEllipse(c, R, R)
        p.setClipPath(clip)
        if full and R > 20:
            p.setPen(QPen(QColor(255, 255, 255, int(34 * v)), 0.8))    # triangle mesh, slowly turning
            for k in range(3):
                th = math.radians(k * 60 + t * 6.0)
                dx, dy = math.cos(th), math.sin(th)
                for i in range(-6, 7):
                    ox, oy = c.x() - dy * i * 11.0, c.y() + dx * i * 11.0
                    p.drawLine(QPointF(ox - dx * R * 1.1, oy - dy * R * 1.1), QPointF(ox + dx * R * 1.1, oy + dy * R * 1.1))
            off = R * (0.50 + 0.07 * math.sin(t * 1.1))                # scan line
            half = math.sqrt(max(0.0, R * R - off * off))
            p.setPen(QPen(QColor(170, 225, 255, int(150 * v)), 1.4))
            p.drawLine(QPointF(c.x() - half, c.y() + off), QPointF(c.x() + half, c.y() + off))
        sh = QLinearGradient(QPointF(c.x(), c.y() - R * 0.1), QPointF(c.x(), c.y() + R))
        sh.setColorAt(0.0, QColor(0, 0, 0, 0))
        sh.setColorAt(1.0, QColor(8, 2, 12, int(130 * v)))
        p.setBrush(sh)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(c, R, R)
        hc = QPointF(c.x() - R * 0.36, c.y() - R * 0.40)               # big soft specular highlight
        sp = QRadialGradient(hc, R * 0.62)
        sp.setColorAt(0.0, QColor(255, 255, 255, int(245 * v)))
        sp.setColorAt(0.35, QColor(255, 235, 245, int(150 * v)))
        sp.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(sp)
        p.drawEllipse(hc, R * 0.62, R * 0.62)
        p.setClipping(False)

    def _draw_labels(self, p, c, v):
        font = QFont("Segoe UI", 6)
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        p.setFont(font)
        items = ((-90, f"AI {CHECK if self.ai_ok else CROSS}"), (180, f"RAM {self._stats['ram']:.1f}%"),
                 (0, f"CPU {self._stats['cpu']:.1f}%"), (90, f"NET {_fmt_rate(self._stats['net'])}"))
        for deg, text in items:
            p.save()
            p.translate(c)
            p.rotate(deg)                                              # put it on the ring...
            p.translate(112, 0)
            p.rotate(-90 if deg == 90 else 90)                         # ...and lay the text along the tangent (bottom one upright)
            w = p.fontMetrics().horizontalAdvance(text) + 8
            box = QRectF(-w / 2, -6, w, 12)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(2, 6, 10, int(235 * v)))
            p.drawRect(box)
            p.setPen(QColor(TEAL.red(), TEAL.green(), TEAL.blue(), int(235 * v)))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
            p.restore()

    def _draw_title(self, p, v, st, acc):
        title, sub = STATUS.get(st, (st, f"FLEXIE IS {st}"))
        font = QFont("Segoe UI Light", 15)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 4.0)
        p.setFont(font)
        p.setPen(QColor(acc.red(), acc.green(), acc.blue(), int(250 * v)))
        p.drawText(QRectF(0, 250, 300, 24), Qt.AlignmentFlag.AlignCenter, title)
        font = QFont("Segoe UI", 7)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.2)
        p.setFont(font)
        p.setPen(QColor(150, 158, 178, int(235 * v)))
        p.drawText(QRectF(0, 274, 300, 16), Qt.AlignmentFlag.AlignCenter, sub)
