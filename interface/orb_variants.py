"""Floating-orb design variants (opt-in). One class, eight looks - pick with  FLEXIE_ORB_STYLE=<name>.

    plasma     liquid plasma drop that wobbles, swirls and pumps with the voice
    ring       Siri-style glowing voice ring made of three wavy ribbons
    eye        a cybernetic eye: segmented lens, iris fibres, pupil that dilates / contracts, blinks
    crystal    a rotating faceted gem lit from one side
    sonar      radar scope: sweeping beam, blips that flash as it passes, ripples when listening
    globe      a turning globe of dots with energy waves running over it
    equalizer  two rings of rounded voice bars around a glass disc
    atom       glowing nucleus with three tilted orbits and electrons

All of them subclass HudFlexieOrb, so state handling, mode colours, wake animation and signals are shared; only
the drawing differs. The classic orb stays the default.   Preview all:  python tools/preview_orb.py
"""
import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QConicalGradient, QPainter, QPainterPath, QPen, QRadialGradient

from interface.orb_v2 import CX, CY, HudFlexieOrb

STYLES = ("plasma", "ring", "eye", "crystal", "sonar", "globe", "equalizer", "atom")
PLUS = QPainter.CompositionMode.CompositionMode_Plus
OVER = QPainter.CompositionMode.CompositionMode_SourceOver
_ICO = None


def _icosahedron():
    """12 vertices and 20 triangular faces of a unit icosahedron (computed once)."""
    global _ICO
    if _ICO is None:
        phi = (1 + 5 ** 0.5) / 2
        raw = [(0, s1, s2 * phi) for s1 in (-1, 1) for s2 in (-1, 1)]
        raw += [(s1, s2 * phi, 0) for s1 in (-1, 1) for s2 in (-1, 1)]
        raw += [(s2 * phi, 0, s1) for s1 in (-1, 1) for s2 in (-1, 1)]
        verts = [tuple(c / math.sqrt(1 + phi * phi) for c in v) for v in raw]
        edge = 2 / math.sqrt(1 + phi * phi)
        near = lambda a, b: abs(math.dist(verts[a], verts[b]) - edge) < 1e-6   # noqa: E731
        faces = [(a, b, c) for a in range(12) for b in range(a + 1, 12) for c in range(b + 1, 12)
                 if near(a, b) and near(b, c) and near(a, c)]
        _ICO = (verts, faces)
    return _ICO


class VariantOrb(HudFlexieOrb):
    """HudFlexieOrb with a selectable drawing style."""

    def __init__(self, style="plasma", parent=None):
        super().__init__(parent)
        self.style = style if style in STYLES else "plasma"

    # shared maths ---------------------------------------------------------
    def energy(self, t):
        st = self.state
        if st == "SPEAKING":
            return 0.55 + 0.45 * abs(math.sin(t * 7.0)) * (0.6 + 0.4 * abs(math.sin(t * 2.3)))
        if st == "LISTENING":
            return 0.40 + 0.25 * math.sin(t * 3.0)
        if st == "PROCESSING":
            return 0.60
        return 0.08 if st in ("SLEEP", "MINIMIZED") else 0.18

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = time.time()
        v = self._view_scale
        scale = max(0.1, self._scale * v)
        acc = self._lerp_color(self._accent_from, self._accent_to, self._color_blend)
        sec = self._lerp_color(self._secondary_from, self._secondary_to, self._color_blend)
        mx = (self._mouse_pos.x() - 150.0) / 150.0
        my = (self._mouse_pos.y() - 150.0) / 150.0
        c = QPointF(150.0 + mx * 3, 140.0 + my * 3)
        e = self.energy(t)
        spin = {"PROCESSING": 3.0, "SPEAKING": 1.6, "LISTENING": 1.0}.get(self.state, 0.5)

        def col(a, base=None):
            b = base or acc
            return QColor(b.red(), b.green(), b.blue(), max(0, min(255, int(a))))

        halo = (130 + 25 * e) * scale                                   # shared soft halo
        g = QRadialGradient(c, halo)
        g.setColorAt(0.0, col(85 * v * (0.5 + e)))
        g.setColorAt(0.6, col(22 * v, sec))
        g.setColorAt(1.0, Qt.GlobalColor.transparent)
        p.setBrush(g)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(c, halo, halo)
        getattr(self, "_draw_" + self.style)(p, c, t, v, scale, acc, sec, e, spin, col)

    # ---------------------------------------------------------------- plasma
    def _draw_plasma(self, p, c, t, v, scale, acc, sec, e, spin, col):
        R = 52 * scale
        amp = 0.03 + 0.10 * e
        path = QPainterPath()
        for i in range(97):
            a = (i % 96) / 96 * math.tau
            w = math.sin(3 * a + t * 1.4) * 0.5 + math.sin(5 * a - t * 2.0) * 0.3 + math.sin(2 * a + t * 0.8) * 0.4
            r = R * (1 + amp * w)
            pt = QPointF(c.x() + math.cos(a) * r, c.y() + math.sin(a) * r)
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        path.closeSubpath()
        h0, s0 = acc.getHsv()[:2]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(8, 8, 18, int(250 * v)))
        p.drawPath(path)
        p.setClipPath(path)
        p.setCompositionMode(PLUS)
        for k, off_h in enumerate((0, 35, -40, 150)):
            a = t * spin * (0.8 + 0.25 * k) + k * 1.57
            o = R * (0.40 + 0.1 * math.sin(t + k))
            pc = QPointF(c.x() + math.cos(a) * o, c.y() + math.sin(a * 1.17) * o)
            q = QColor.fromHsv((max(0, h0) + off_h) % 360, min(255, s0), 255)
            g = QRadialGradient(pc, R)
            g.setColorAt(0, QColor(q.red(), q.green(), q.blue(), int(200 * v)))
            g.setColorAt(0.55, QColor(q.red(), q.green(), q.blue(), int(60 * v)))
            g.setColorAt(1, Qt.GlobalColor.transparent)
            p.setBrush(g)
            p.drawEllipse(pc, R, R)
        core = R * (0.12 + 0.15 * e)
        g = QRadialGradient(c, core * 2)
        g.setColorAt(0, QColor(255, 255, 255, int(230 * v)))
        g.setColorAt(1, Qt.GlobalColor.transparent)
        p.setBrush(g)
        p.drawEllipse(c, core * 2, core * 2)
        p.setCompositionMode(OVER)
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(col(210 * v), 1.6))
        p.drawPath(path)
        p.setPen(QPen(QColor(255, 255, 255, int(140 * v)), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(QRectF(c.x() - R * 0.8, c.y() - R * 0.8, R * 1.6, R * 1.6).toRect(), 105 * 16, 48 * 16)

    # ------------------------------------------------------------------ ring
    def _draw_ring(self, p, c, t, v, scale, acc, sec, e, spin, col):
        p.setCompositionMode(PLUS)
        p.setBrush(Qt.BrushStyle.NoBrush)
        ribbons = ((54, 7, 3, 1.3, acc), (58, 9, 4, -1.7, sec), (62, 6, 5, 2.2, acc.lighter(160)))
        for k, (r0, amp, f, sp, base) in enumerate(ribbons):
            path = QPainterPath()
            for i in range(121):
                a = i / 120 * math.tau
                r = r0 * scale + e * amp * math.sin(a * f + t * sp * (1 + e)) + e * amp * 0.5 * math.sin(a * (f + 2) - t * sp)
                pt = QPointF(c.x() + math.cos(a) * r, c.y() + math.sin(a) * r)
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            for w, al in ((7.0, 28), (3.4, 80), (1.4, 220)):
                p.setPen(QPen(col(al * v, base), w - k * 0.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawPath(path)
        g = QRadialGradient(c, 42 * scale)
        g.setColorAt(0, col(110 * v * (0.4 + e)))
        g.setColorAt(1, Qt.GlobalColor.transparent)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, 42 * scale, 42 * scale)
        p.setCompositionMode(OVER)

    # ------------------------------------------------------------------- eye
    def _draw_eye(self, p, c, t, v, scale, acc, sec, e, spin, col):
        R = 58 * scale
        blink = max(0.0, 1.0 - abs(((t % 4.6) - 4.45) * 9)) if getattr(self, "allow_blink", True) else 0.0
        lid = 1.0 - 0.92 * blink
        p.save()
        p.translate(c)
        p.scale(1.0, lid)
        p.setPen(Qt.PenStyle.NoPen)
        g = QRadialGradient(QPointF(0, 0), R)
        g.setColorAt(0.0, QColor(6, 8, 14, int(250 * v)))
        g.setColorAt(0.8, QColor(10, 12, 20, int(250 * v)))
        g.setColorAt(1.0, col(200 * v))
        p.setBrush(g)
        p.drawEllipse(QPointF(0, 0), R, R)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(24):                                              # segmented lens ring
            p.setPen(QPen(col(190 * v), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            p.drawArc(QRectF(-R * 0.92, -R * 0.92, R * 1.84, R * 1.84).toRect(),
                      int(((i * 15 + t * spin * 12) % 360) * 16), 9 * 16)      # modulo: Qt angles are 32-bit ints
        ir = R * 0.66
        g = QRadialGradient(QPointF(0, 0), ir)
        g.setColorAt(0.0, col(255 * v, sec.darker(220)))
        g.setColorAt(0.55, col(235 * v, acc))
        g.setColorAt(1.0, col(255 * v, acc.lighter(150)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(0, 0), ir, ir)
        pupil = R * ({"LISTENING": 0.30, "SPEAKING": 0.24}.get(self.state, 0.17) + (0.06 * math.sin(t * 6) if self.state == "PROCESSING" else 0))
        ox = self._scan_eye_dx * scale * 0.6 + (self._mouse_pos.x() - 150) / 150 * R * 0.08
        oy = self._scan_eye_dy * scale * 0.6 + (self._mouse_pos.y() - 150) / 150 * R * 0.08
        for i in range(48):                                              # iris fibres
            a = i / 48 * math.tau
            p.setPen(QPen(QColor(255, 255, 255, int(48 * v)), 0.8))
            p.drawLine(QPointF(ox + math.cos(a) * pupil * 1.15, oy + math.sin(a) * pupil * 1.15),
                       QPointF(math.cos(a) * ir * 0.97, math.sin(a) * ir * 0.97))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, int(255 * v)))
        p.drawEllipse(QPointF(ox, oy), pupil, pupil)
        p.setBrush(QColor(255, 255, 255, int(235 * v)))
        p.drawEllipse(QPointF(ox - pupil * 0.55, oy - pupil * 0.6), pupil * 0.28, pupil * 0.22)
        p.restore()

    # --------------------------------------------------------------- crystal
    def _draw_crystal(self, p, c, t, v, scale, acc, sec, e, spin, col):
        verts, faces = _icosahedron()
        R = (46 + 8 * e) * scale
        ay, ax = t * 0.6 * spin, 0.45 + 0.25 * math.sin(t * 0.4)
        sy, cy_, sx, cx_ = math.sin(ay), math.cos(ay), math.sin(ax), math.cos(ax)
        pts = []
        for x, y, z in verts:
            x, z = x * cy_ + z * sy, -x * sy + z * cy_
            y, z = y * cx_ - z * sx, y * sx + z * cx_
            pts.append((x, y, z))
        order = sorted(faces, key=lambda f: sum(pts[i][2] for i in f))
        light = (-0.45, -0.55, 0.7)
        p.setPen(Qt.PenStyle.NoPen)
        for f in order:
            a, b, d = (pts[i] for i in f)
            ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            vx, vy, vz = d[0] - a[0], d[1] - a[1], d[2] - a[2]
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1
            lit = max(0.0, (nx * light[0] + ny * light[1] + nz * light[2]) / ln)
            if nz < 0:
                lit = max(0.0, -lit) * 0.5
            base = QColor(int(acc.red() * (0.35 + 0.65 * lit) + 255 * lit * 0.25),
                          int(acc.green() * (0.35 + 0.65 * lit) + 255 * lit * 0.25),
                          int(acc.blue() * (0.35 + 0.65 * lit) + 255 * lit * 0.25))
            base.setAlpha(int((120 + 110 * lit) * v))
            poly = QPainterPath()
            for k, q in enumerate((a, b, d)):
                pt = QPointF(c.x() + q[0] * R, c.y() + q[1] * R)
                poly.moveTo(pt) if k == 0 else poly.lineTo(pt)
            poly.closeSubpath()
            p.setBrush(base)
            p.setPen(QPen(QColor(255, 255, 255, int(110 * v)), 0.9))
            p.drawPath(poly)
        p.setCompositionMode(PLUS)
        g = QRadialGradient(c, R * 0.8)
        g.setColorAt(0, col(120 * v * (0.4 + e)))
        g.setColorAt(1, Qt.GlobalColor.transparent)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, R * 0.8, R * 0.8)
        p.setCompositionMode(OVER)

    # ----------------------------------------------------------------- sonar
    def _draw_sonar(self, p, c, t, v, scale, acc, sec, e, spin, col):
        R = 78 * scale
        p.setBrush(QColor(4, 10, 14, int(210 * v)))
        p.setPen(QPen(col(160 * v), 1.4))
        p.drawEllipse(c, R, R)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k in (0.25, 0.5, 0.75):
            p.setPen(QPen(col(55 * v), 0.9))
            p.drawEllipse(c, R * k, R * k)
        p.setPen(QPen(col(45 * v), 0.9))
        p.drawLine(QPointF(c.x() - R, c.y()), QPointF(c.x() + R, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - R), QPointF(c.x(), c.y() + R))
        for i in range(72):
            a = i / 72 * math.tau
            ln = 6 if i % 6 == 0 else 3
            p.setPen(QPen(col(150 * v), 1.0))
            p.drawLine(QPointF(c.x() + math.cos(a) * R, c.y() + math.sin(a) * R),
                       QPointF(c.x() + math.cos(a) * (R + ln), c.y() + math.sin(a) * (R + ln)))
        ang = (t * 70 * spin) % 360
        cg = QConicalGradient(c, -ang)
        cg.setColorAt(0.0, col(190 * v))
        cg.setColorAt(0.28, col(0))
        cg.setColorAt(1.0, col(0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(cg)
        p.drawEllipse(c, R, R)
        for i in range(7):                                               # blips flash when the beam passes
            s = math.sin(i * 91.7) * 1e4
            ba = (s - math.floor(s)) * 360
            br = R * (0.25 + 0.7 * ((math.sin(i * 17.3) * 0.5) + 0.5))
            since = (ang - ba) % 360
            al = max(0.0, 1 - since / 150.0)
            x, y = c.x() + math.cos(math.radians(ba)) * br, c.y() + math.sin(math.radians(ba)) * br
            p.setBrush(QColor(255, 255, 255, int(220 * al * v)))
            p.drawEllipse(QPointF(x, y), 2.6, 2.6)
        if self.state == "LISTENING" or self.state == "SPEAKING":
            for k in range(3):
                f = (t * 0.6 + k / 3) % 1.0
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(col(190 * (1 - f) * v), 1.6))
                p.drawEllipse(c, R * 0.2 + R * 0.8 * f, R * 0.2 + R * 0.8 * f)
        g = QRadialGradient(c, 9)
        g.setColorAt(0, QColor(255, 255, 255, int(255 * v)))
        g.setColorAt(1, col(0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, 9, 9)

    # ----------------------------------------------------------------- globe
    def _draw_globe(self, p, c, t, v, scale, acc, sec, e, spin, col):
        R = 56 * scale
        n = 300
        ay, ax = t * 0.5 * spin, 0.38
        sy, cy_, sx, cx_ = math.sin(ay), math.cos(ay), math.sin(ax), math.cos(ax)
        pts = []
        for i in range(n):
            y = 1 - 2 * (i + 0.5) / n
            r = math.sqrt(1 - y * y)
            th = i * 2.399963
            x, z = math.cos(th) * r, math.sin(th) * r
            x, z = x * cy_ + z * sy, -x * sy + z * cy_
            y, z = y * cx_ - z * sx, y * sx + z * cx_
            pts.append((x, y, z, i))
        pts.sort(key=lambda q: q[2])
        p.setPen(Qt.PenStyle.NoPen)
        g = QRadialGradient(c, R)
        g.setColorAt(0, col(40 * v))
        g.setColorAt(0.9, col(14 * v, sec))
        g.setColorAt(1, col(90 * v))
        p.setBrush(g)
        p.drawEllipse(c, R, R)
        p.setCompositionMode(PLUS)
        for x, y, z, _i in pts:
            wave = 0.5 + 0.5 * math.sin(math.asin(max(-1, min(1, y))) * 6 - t * 3.2)
            light = (0.25 + 0.75 * (z * 0.5 + 0.5)) * (0.55 + 0.9 * e * wave)
            size = (1.0 + 1.5 * (z * 0.5 + 0.5)) * scale
            p.setBrush(col(255 * min(1.0, light) * v, acc.lighter(130) if z > 0.5 else acc))
            p.drawEllipse(QPointF(c.x() + x * R, c.y() + y * R), size, size)
        p.setCompositionMode(OVER)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(col(150 * v), 1.2))
        p.drawEllipse(c, R * 1.06, R * 1.06)

    # ------------------------------------------------------------- equalizer
    def _draw_equalizer(self, p, c, t, v, scale, acc, sec, e, spin, col):
        disc = 34 * scale
        g = QRadialGradient(QPointF(c.x() - disc * 0.3, c.y() - disc * 0.35), disc * 1.5)
        g.setColorAt(0, col(255 * v, acc.lighter(170)))
        g.setColorAt(0.5, col(240 * v, acc))
        g.setColorAt(1, col(255 * v, sec.darker(180)))
        p.setPen(QPen(QColor(255, 255, 255, int(70 * v)), 1.2))
        p.setBrush(g)
        p.drawEllipse(c, disc, disc)
        for ring, (r0, n, maxlen, wd) in enumerate(((46, 48, 14, 3.4), (66, 72, 26, 2.4))):
            for i in range(n):
                a = i / n * math.tau
                if self.state == "SPEAKING":
                    val = abs(math.sin(t * 7 + i * 0.5 + ring)) * (0.5 + 0.5 * abs(math.sin(t * 2.7 + i * 0.21)))
                elif self.state == "PROCESSING":
                    val = 0.5 + 0.5 * math.sin(t * 4 - i * 0.4 * (1 if ring else -1))
                elif self.state == "LISTENING":
                    val = 0.25 + 0.4 * abs(math.sin(t * 3 + i * 0.7))
                else:
                    val = 0.12 + 0.08 * math.sin(t * 1.5 + i * 0.3)
                ln = (3 + maxlen * val) * scale
                mix = 0.5 + 0.5 * math.sin(a * 2 + t * 0.8)
                bc = QColor(int(acc.red() * (1 - mix) + sec.red() * mix + 60 * mix), int(acc.green() * (1 - mix) + sec.green() * mix),
                            int(acc.blue() * (1 - mix) + sec.blue() * mix + 60 * mix))
                bc.setAlpha(int((230 - 60 * ring) * v))
                p.setPen(QPen(bc, wd * scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(c.x() + math.cos(a) * r0 * scale, c.y() + math.sin(a) * r0 * scale),
                           QPointF(c.x() + math.cos(a) * (r0 * scale + ln), c.y() + math.sin(a) * (r0 * scale + ln)))

    # ------------------------------------------------------------------ atom
    def _draw_atom(self, p, c, t, v, scale, acc, sec, e, spin, col):
        p.setCompositionMode(PLUS)
        nuc = (11 + 7 * e) * scale
        g = QRadialGradient(c, nuc * 3)
        g.setColorAt(0, QColor(255, 255, 255, int(255 * v)))
        g.setColorAt(0.25, col(230 * v))
        g.setColorAt(1, col(0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, nuc * 3, nuc * 3)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k in range(3):
            p.save()
            p.translate(c)
            p.rotate(k * 60 + t * 9 * spin)
            rx, ry = 70 * scale, 24 * scale
            p.setPen(QPen(col(95 * v), 1.1))
            p.drawEllipse(QPointF(0, 0), rx, ry)
            for tail in range(9):
                a = t * 1.7 * spin * (1 + 0.2 * k) + k * 2.1 - tail * 0.07
                x, y = math.cos(a) * rx, math.sin(a) * ry
                s = (4.0 - tail * 0.38) * scale
                if s <= 0.3:
                    continue
                gg = QRadialGradient(QPointF(x, y), s * 3)
                gg.setColorAt(0, QColor(255, 255, 255, int((255 - tail * 24) * v)))
                gg.setColorAt(0.3, col((200 - tail * 18) * v))
                gg.setColorAt(1, col(0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(gg)
                p.drawEllipse(QPointF(x, y), s * 3, s * 3)
                p.setBrush(Qt.BrushStyle.NoBrush)
            p.restore()
        p.setPen(QPen(col(60 * v), 1.0, Qt.PenStyle.DotLine))
        p.drawEllipse(c, 82 * scale, 82 * scale)
        p.setCompositionMode(OVER)


__all__ = ["STYLES", "VariantOrb", "CX", "CY"]
