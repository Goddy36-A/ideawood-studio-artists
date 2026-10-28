"""Drawing engine for the cartoon board: brushes, shapes, flood fill, text. QImage/QPainter only - no widgets.

All frames are ``QImage.Format_ARGB32_Premultiplied``. Brush strokes are painted into a separate transparent
*stroke buffer* and composited once, so a stroke has one uniform opacity (no dark overlaps) and can be previewed live.
"""
from __future__ import annotations

import math
import random
from array import array
from typing import Iterator, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPolygonF,
                           QRadialGradient)

FMT = QImage.Format_ARGB32_Premultiplied

BRUSH_TYPES = ["Pen", "Marker", "Pencil", "Crayon", "Spray", "Watercolor", "Calligraphy", "Pixel"]
SHAPES = ["Line", "Arrow", "Rectangle", "Rounded rectangle", "Ellipse", "Triangle", "Diamond", "Star", "Heart",
          "Speech bubble"]
SHAPE_MODES = ["Outline", "Fill", "Outline + fill"]


def new_image(w: int, h: int) -> QImage:
    im = QImage(w, h, FMT)
    im.fill(Qt.transparent)
    return im


def with_alpha(c: QColor, a: int) -> QColor:
    c = QColor(c)
    c.setAlpha(max(0, min(255, int(a))))
    return c


# ============================================================================ brushes
class Stroke:
    """One brush stroke painted into its own buffer. Call begin(), add() for each pointer move, then commit()."""

    # extra opacity factor per brush (a marker is see-through by nature)
    FACTOR = {"Marker": 0.6}

    def __init__(self, w: int, h: int, kind: str, color: QColor, seed: int = 7):
        self.kind = kind if kind in BRUSH_TYPES else "Pen"
        self.color = QColor(color)
        self.color.setAlpha(255)
        self.buf = new_image(w, h)
        self.rng = random.Random(seed)
        self.carry = 0.0
        self.last: Optional[QPointF] = None

    @property
    def factor(self) -> float:
        return self.FACTOR.get(self.kind, 1.0)

    def _painter(self) -> QPainter:
        p = QPainter(self.buf)
        p.setRenderHint(QPainter.Antialiasing, self.kind != "Pixel")
        return p

    def begin(self, pt: QPointF, width: float):
        self.last = QPointF(pt)
        self.carry = 0.0
        self.add(pt, pt, width, first=True)

    def add(self, a: QPointF, b: QPointF, width: float, first: bool = False):
        width = max(1.0, float(width))
        k = self.kind
        p = self._painter()
        try:
            if k in ("Pen", "Marker", "Pixel"):
                if k == "Pixel":
                    wi = max(1, int(round(width)))
                    pen = QPen(self.color, wi)
                    pen.setCapStyle(Qt.SquareCap)
                    a, b = QPointF(round(a.x()), round(a.y())), QPointF(round(b.x()), round(b.y()))
                elif k == "Marker":
                    pen = QPen(self.color, width * 1.3)
                    pen.setCapStyle(Qt.SquareCap)
                else:
                    pen = QPen(self.color, width)
                    pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                p.setPen(pen)
                p.drawLine(a, b)
            elif k == "Pencil":
                self._stamps(p, a, b, max(0.8, width * 0.3), first, self._pencil_dab, width)
            elif k == "Crayon":
                self._stamps(p, a, b, max(0.8, width * 0.25), first, self._crayon_dab, width)
            elif k == "Spray":
                self._stamps(p, a, b, max(0.8, width * 0.2), first, self._spray_dab, width)
            elif k == "Watercolor":
                self._stamps(p, a, b, max(0.7, width * 0.12), first, self._water_dab, width)
            elif k == "Calligraphy":
                self._stamps(p, a, b, max(0.6, width * 0.07), first, self._callig_dab, width)
        finally:
            p.end()
        self.last = QPointF(b)

    # ---- stamping along a path with constant spacing
    def _stamps(self, p, a, b, spacing, first, dab, width):
        if first:
            dab(p, a, width)
            return
        dx, dy = b.x() - a.x(), b.y() - a.y()
        dist = math.hypot(dx, dy)
        if dist <= 0:
            return
        d = spacing - self.carry
        while d <= dist:
            dab(p, QPointF(a.x() + dx * d / dist, a.y() + dy * d / dist), width)
            d += spacing
        self.carry = dist - (d - spacing)

    def _dot(self, p, pt, r, alpha):
        p.setPen(Qt.NoPen)
        p.setBrush(with_alpha(self.color, alpha))
        p.drawEllipse(pt, r, r)

    def _pencil_dab(self, p, pt, width):
        self._dot(p, pt, max(0.6, width * 0.35), self.rng.randint(130, 255))

    def _crayon_dab(self, p, pt, width):
        for _ in range(max(3, int(width * 0.8))):
            ang, rad = self.rng.uniform(0, 6.2832), width * 0.55 * math.sqrt(self.rng.random())
            self._dot(p, QPointF(pt.x() + rad * math.cos(ang), pt.y() + rad * math.sin(ang)),
                      self.rng.uniform(0.5, max(1.0, width * 0.18)), self.rng.randint(140, 255))

    def _spray_dab(self, p, pt, width):
        for _ in range(max(4, int(width * 1.2))):
            self._dot(p, QPointF(pt.x() + self.rng.gauss(0, width * 0.45), pt.y() + self.rng.gauss(0, width * 0.45)),
                      0.8, 210)

    def _water_dab(self, p, pt, width):
        r = width * 0.9
        g = QRadialGradient(pt, r)
        g.setColorAt(0.0, with_alpha(self.color, 30))
        g.setColorAt(1.0, with_alpha(self.color, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(pt, r, r)

    def _callig_dab(self, p, pt, width):
        p.save()
        p.translate(pt)
        p.rotate(-45)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(QPointF(0, 0), width * 0.55, max(0.8, width * 0.15))
        p.restore()

    def commit(self, frame: QImage, opacity: float = 1.0):
        p = QPainter(frame)
        p.setOpacity(max(0.0, min(1.0, opacity * self.factor)))
        p.drawImage(0, 0, self.buf)
        p.end()


def erase_segment(frame: QImage, a: QPointF, b: QPointF, width: float):
    p = QPainter(frame)
    p.setRenderHint(QPainter.Antialiasing)
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    pen = QPen(Qt.black, max(1.0, width))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(a, b)
    p.end()


# ============================================================================ shapes
def _poly(points) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    path.closeSubpath()
    return path


def shape_path(kind: str, r: QRectF) -> QPainterPath:
    l, t, rr, bt = r.left(), r.top(), r.right(), r.bottom()
    cx, cy = r.center().x(), r.center().y()
    path = QPainterPath()
    if kind == "Rectangle":
        path.addRect(r)
    elif kind == "Rounded rectangle":
        rad = min(r.width(), r.height()) * 0.22
        path.addRoundedRect(r, rad, rad)
    elif kind == "Ellipse":
        path.addEllipse(r)
    elif kind == "Triangle":
        return _poly([(cx, t), (rr, bt), (l, bt)])
    elif kind == "Diamond":
        return _poly([(cx, t), (rr, cy), (cx, bt), (l, cy)])
    elif kind == "Star":
        pts = []
        for k in range(10):
            ang = math.radians(-90 + k * 36)
            rad = 1.0 if k % 2 == 0 else 0.42
            pts.append((cx + math.cos(ang) * rad * r.width() / 2, cy + math.sin(ang) * rad * r.height() / 2))
        return _poly(pts)
    elif kind == "Heart":
        def P(x, y):
            return QPointF(l + x * r.width(), t + y * r.height())
        path.moveTo(P(0.5, 0.95))
        path.cubicTo(P(0.05, 0.60), P(0.0, 0.25), P(0.25, 0.12))
        path.cubicTo(P(0.38, 0.05), P(0.5, 0.15), P(0.5, 0.28))
        path.cubicTo(P(0.5, 0.15), P(0.62, 0.05), P(0.75, 0.12))
        path.cubicTo(P(1.0, 0.25), P(0.95, 0.60), P(0.5, 0.95))
        path.closeSubpath()
    elif kind == "Speech bubble":
        body = QPainterPath()
        body.addEllipse(QRectF(l, t, r.width(), r.height() * 0.8))
        tail = _poly([(l + r.width() * 0.22, t + r.height() * 0.70), (l + r.width() * 0.12, bt),
                      (l + r.width() * 0.45, t + r.height() * 0.78)])
        return body.united(tail)
    else:
        path.addRect(r)
    return path


def constrain(kind: str, a: QPointF, b: QPointF) -> QPointF:
    """Shift held: lines snap to 45 degree steps, every other shape becomes square / circular."""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    if kind in ("Line", "Arrow"):
        ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        d = math.hypot(dx, dy)
        return QPointF(a.x() + math.cos(ang) * d, a.y() + math.sin(ang) * d)
    m = max(abs(dx), abs(dy))
    return QPointF(a.x() + math.copysign(m, dx or 1), a.y() + math.copysign(m, dy or 1))


def draw_shape(p: QPainter, kind: str, a: QPointF, b: QPointF, stroke: QColor, fill: QColor, width: float,
               mode: str = "Outline"):
    p.setRenderHint(QPainter.Antialiasing)
    width = max(1.0, width)
    if kind in ("Line", "Arrow"):
        pen = QPen(stroke, width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawLine(a, b)
        if kind == "Arrow":
            d = math.hypot(b.x() - a.x(), b.y() - a.y())
            if d > 1:
                ang = math.atan2(b.y() - a.y(), b.x() - a.x())
                head = max(width * 3.5, 14.0)
                pts = [b, QPointF(b.x() - head * math.cos(ang - 0.45), b.y() - head * math.sin(ang - 0.45)),
                       QPointF(b.x() - head * math.cos(ang + 0.45), b.y() - head * math.sin(ang + 0.45))]
                p.setPen(Qt.NoPen)
                p.setBrush(stroke)
                p.drawPolygon(QPolygonF(pts))
        return
    r = QRectF(a, b).normalized()
    if r.width() < 1 or r.height() < 1:
        return
    path = shape_path(kind, r)
    pen = QPen(stroke, width) if mode in ("Outline", "Outline + fill") else QPen(Qt.NoPen)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(fill if mode in ("Fill", "Outline + fill") else Qt.NoBrush)
    p.drawPath(path)


# ============================================================================ text
def draw_text(frame: QImage, pt: QPointF, text: str, font: QFont, color: QColor, opacity: float = 1.0):
    p = QPainter(frame)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setOpacity(opacity)
    p.setFont(font)
    p.setPen(color)
    fm = QFontMetrics(font)
    y = pt.y() + fm.ascent()
    for line in text.split("\n"):
        p.drawText(QPointF(pt.x(), y), line)
        y += fm.lineSpacing()
    p.end()


# ============================================================================ flood fill
def _unpack(v: int) -> Tuple[int, int, int, int]:
    return (v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255, v & 255


def flood_fill(img: QImage, x: int, y: int, color: QColor, tolerance: int = 48, opacity: float = 1.0) -> int:
    """Fill the connected region around (x, y) with ``color``. Returns the number of pixels filled.

    ``tolerance`` (0-255) is how different a pixel may be from the clicked one and still count as the same region;
    a little tolerance swallows the faint anti-aliased fringe of line art. A 1-pixel ring beneath the line is also
    painted so no light halo is left between a line and its fill.
    """
    w, h = img.width(), img.height()
    if not (0 <= x < w and 0 <= y < h):
        return 0
    if img.format() != FMT:
        raise ValueError("flood_fill needs an ARGB32 premultiplied image")
    px = memoryview(img.bits()).cast("B").cast("I")
    target = px[y * w + x]
    ta, tr, tg, tb = _unpack(target)
    tol = max(0, int(tolerance))
    cache: dict = {}

    def match(v: int) -> bool:
        r = cache.get(v)
        if r is None:
            if v == target:
                r = True
            elif tol == 0:
                r = False
            else:
                a, rr, g, b = _unpack(v)
                r = abs(a - ta) <= tol and abs(rr - tr) <= tol and abs(g - tg) <= tol and abs(b - tb) <= tol
            cache[v] = r
        return r

    c = QColor(color)
    fa = max(0, min(255, int(round(c.alpha() * opacity))))
    fr, fg, fb = c.red() * fa // 255, c.green() * fa // 255, c.blue() * fa // 255
    fill_v = (fa << 24) | (fr << 16) | (fg << 8) | fb
    if fill_v == target and tol == 0:
        return 0

    seen = bytearray(w * h)
    spans = []
    stack = [(x, y)]
    count = 0
    while stack:
        sx, sy = stack.pop()
        base = sy * w
        if seen[base + sx] or not match(px[base + sx]):
            continue
        l = sx
        while l > 0 and not seen[base + l - 1] and match(px[base + l - 1]):
            l -= 1
        r = sx
        while r < w - 1 and not seen[base + r + 1] and match(px[base + r + 1]):
            r += 1
        for xx in range(l, r + 1):
            seen[base + xx] = 1
        spans.append((l, r, sy))
        count += r - l + 1
        for ny in (sy - 1, sy + 1):
            if 0 <= ny < h:
                nb = ny * w
                inspan = False
                for xx in range(l, r + 1):
                    ok = not seen[nb + xx] and match(px[nb + xx])
                    if ok and not inspan:
                        stack.append((xx, ny))
                        inspan = True
                    elif not ok:
                        inspan = False

    # ring beneath the line art: neighbours of the region that were not filled get the fill *underneath* them
    ring = bytearray(w * h)
    under = []

    def add_ring(i: int):
        if not seen[i] and not ring[i]:
            ring[i] = 1
            under.append(i)

    for l, r, sy in spans:
        b = sy * w
        if l > 0:
            add_ring(b + l - 1)
        if r < w - 1:
            add_ring(b + r + 1)
        for ny in (sy - 1, sy + 1):
            if 0 <= ny < h:
                nb = ny * w
                for xx in range(max(0, l - 1), min(w - 1, r + 1) + 1):
                    if not seen[nb + xx] and not ring[nb + xx]:
                        ring[nb + xx] = 1
                        under.append(nb + xx)
    for l, r, sy in spans:
        b = sy * w
        px[b + l:b + r + 1] = array("I", [fill_v]) * (r - l + 1)
    for i in under:
        ea, er, eg, eb = _unpack(px[i])
        if ea == 0:
            continue
        k = 255 - ea
        na = min(255, ea + fa * k // 255)
        nr = min(na, er + fr * k // 255)
        ng = min(na, eg + fg * k // 255)
        nb_ = min(na, eb + fb * k // 255)
        px[i] = (na << 24) | (nr << 16) | (ng << 8) | nb_
    return count


# ============================================================================ small helpers
def visible_color(frame: QImage, x: int, y: int, bg: QColor) -> Optional[QColor]:
    """The colour the viewer sees at (x, y): the frame pixel blended over the background."""
    if not (0 <= x < frame.width() and 0 <= y < frame.height()):
        return None
    c = frame.pixelColor(x, y)
    a = c.alphaF()
    if a >= 0.999:
        return QColor(c.red(), c.green(), c.blue())
    return QColor(int(c.red() * a + bg.red() * (1 - a)), int(c.green() * a + bg.green() * (1 - a)),
                  int(c.blue() * a + bg.blue() * (1 - a)))


def clear_rect(img: QImage, r: QRectF):
    p = QPainter(img)
    p.setCompositionMode(QPainter.CompositionMode_Clear)
    p.fillRect(r, Qt.black)
    p.end()
