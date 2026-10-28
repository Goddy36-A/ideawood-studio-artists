"""The nine mouth pictures used for lip-sync: a built-in cartoon set, or your own PNGs named A.png ... H.png, X.png."""
from __future__ import annotations

import os
from typing import Dict

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

from .lipsync import SHAPES

W, H = 300, 200
OUT, IN, TONGUE, TEETH = QColor("#2b1313"), QColor("#4a1c1c"), QColor("#e8707a"), QColor("#ffffff")


def draw_shape(shape: str) -> QImage:
    im = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
    im.fill(Qt.transparent)
    p = QPainter(im)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(OUT, 10)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)

    def hole(rect: QRectF, rounded=False):
        path = QPainterPath()
        if rounded:
            path.addRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        else:
            path.addEllipse(rect)
        p.setPen(pen)
        p.setBrush(IN)
        p.drawPath(path)
        return path

    def tongue(rect: QRectF, clip: QPainterPath):
        p.save()
        p.setClipPath(clip)
        p.setPen(Qt.NoPen)
        p.setBrush(TONGUE)
        p.drawEllipse(rect)
        p.restore()

    def teeth(rect: QRectF, clip: QPainterPath):
        p.save()
        p.setClipPath(clip)
        p.setPen(Qt.NoPen)
        p.setBrush(TEETH)
        p.drawRoundedRect(rect, 6, 6)
        p.restore()

    s = shape
    if s == "X":
        path = QPainterPath(QPointF(80, 100))
        path.quadTo(QPointF(150, 118), QPointF(220, 100))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
    elif s == "A":
        pen.setWidth(16)
        p.setPen(pen)
        p.drawLine(QPointF(85, 100), QPointF(215, 100))
    elif s == "B":
        r = QRectF(70, 78, 160, 44)
        c = hole(r, True)
        teeth(QRectF(80, 80, 140, 18), c)
        teeth(QRectF(80, 100, 140, 16), c)
    elif s == "C":
        c = hole(QRectF(75, 55, 150, 92))
        tongue(QRectF(105, 110, 90, 50), c)
    elif s == "D":
        c = hole(QRectF(80, 28, 140, 145))
        tongue(QRectF(100, 108, 100, 70), c)
    elif s == "E":
        c = hole(QRectF(100, 45, 100, 110))
        tongue(QRectF(115, 110, 70, 50), c)
    elif s == "F":
        pen.setWidth(14)
        hole(QRectF(122, 68, 56, 64))
    elif s == "G":
        c = hole(QRectF(72, 74, 156, 58), True)
        teeth(QRectF(86, 76, 128, 24), c)
    elif s == "H":
        c = hole(QRectF(80, 45, 140, 105))
        tongue(QRectF(115, 55, 70, 42), c)
    p.end()
    return im


def default_kit() -> Dict[str, QImage]:
    return {s: draw_shape(s) for s in SHAPES}


def load_kit(folder: str) -> Dict[str, QImage]:
    """Your own set; any missing letter falls back to the built-in mouth so a partial set still works."""
    kit = default_kit()
    if folder and os.path.isdir(folder):
        for s in SHAPES:
            for name in (f"{s}.png", f"{s.lower()}.png"):
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    im = QImage(path)
                    if not im.isNull():
                        kit[s] = im.convertToFormat(QImage.Format_ARGB32_Premultiplied)
                    break
    return kit
