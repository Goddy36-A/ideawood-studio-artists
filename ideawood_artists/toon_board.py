"""The drawing board used by the cartoon editor: a zoomable, pannable canvas with Paint-3D-style 2D tools.

Tools: brush (8 types), eraser, fill bucket, shapes, text, rectangle select (move / resize / flip / rotate /
copy / cut / paste), colour picker, hand. Left button draws with the primary colour, right button with the secondary.
Pen pressure is used when a tablet is present. All pointer logic lives in ``pointer_down/move/up`` (image
coordinates) so it can be tested without real mouse events.
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QGuiApplication, QImage, QPainter, QPen, QTransform)
from PySide6.QtWidgets import QInputDialog, QWidget

from . import paint
from .paint import FMT, Stroke

TOOLS = ("brush", "eraser", "fill", "shape", "text", "select", "picker", "hand", "mouth")
HANDLE = 11  # px, resize handle of a selection (screen pixels)


def _mirror(img: QImage, horizontal: bool) -> QImage:
    """Left-right (horizontal=True) or top-bottom flip, without the deprecated QImage.mirrored on new PySide6."""
    if hasattr(img, "flipped"):
        return img.flipped(Qt.Horizontal if horizontal else Qt.Vertical)
    return img.mirrored(horizontal, not horizontal)


class PaintBoard(QWidget):
    toolChanged = Signal(str)
    colorsChanged = Signal()
    viewChanged = Signal()
    strokeFinished = Signal()          # something was drawn on the current frame
    mouthChanged = Signal()            # lip-sync mouth switched on / moved / resized

    def __init__(self, ed):
        super().__init__()
        self.ed = ed                    # the ToonEditor: clip, cur, img_at(), push_undo(), mark_dirty(), guide_text()
        self.tool = "brush"
        self.brush = "Pen"
        self.shape = "Rectangle"
        self.shape_mode = "Outline"
        self.size = 7
        self.opacity = 1.0
        self.stab = 0.0                 # 0..0.9 stroke smoothing
        self.tolerance = 48
        self.primary = QColor("#111111")
        self.secondary = QColor("#ffffff")
        self.font = QFont()
        self.font.setPixelSize(56)

        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.space_down = False
        self._pan_last: Optional[QPointF] = None
        self.hover: Optional[QPointF] = None

        self.stroke: Optional[Stroke] = None
        self.erasing = False
        self._raw: Optional[QPointF] = None
        self._smooth: Optional[QPointF] = None
        self._width_scale = 1.0
        self.tablet = False
        self.shape_a: Optional[QPointF] = None
        self.shape_b: Optional[QPointF] = None
        self._btn = Qt.LeftButton
        self._mouth_drag = False

        self.sel: Optional[QRectF] = None       # selection rectangle (image coordinates)
        self.float_img: Optional[QImage] = None  # lifted pixels, drawn at ``sel`` until committed
        self._sel_mode: Optional[str] = None
        self._sel_anchor = QPointF()
        self._sel_off = QPointF()
        self._ratio = 1.0

        self.setMinimumSize(560, 320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)

    # ------------------------------------------------------------------ tool / colour state
    def set_tool(self, name: str):
        if name == self.tool:
            return
        self.commit_selection()
        self.tool = name
        self.toolChanged.emit(name)
        self.update()

    def swap_colors(self):
        self.primary, self.secondary = self.secondary, self.primary
        self.colorsChanged.emit()

    # ------------------------------------------------------------------ view (zoom / pan)
    def _fit(self):
        c = self.ed.clip
        base = min(self.width() / c.w, self.height() / c.h) * 0.97
        s = base * self.zoom
        return s, (self.width() - c.w * s) / 2 + self.pan.x(), (self.height() - c.h * s) / 2 + self.pan.y()

    def to_img(self, pos) -> QPointF:
        s, ox, oy = self._fit()
        return QPointF((pos.x() - ox) / s, (pos.y() - oy) / s)

    def to_view(self, ip: QPointF) -> QPointF:
        s, ox, oy = self._fit()
        return QPointF(ox + ip.x() * s, oy + ip.y() * s)

    def zoom_at(self, factor: float, anchor_widget: Optional[QPointF] = None):
        anchor = anchor_widget if anchor_widget is not None else QPointF(self.width() / 2, self.height() / 2)
        ip = self.to_img(anchor)
        self.zoom = max(0.2, min(24.0, self.zoom * factor))
        v = self.to_view(ip)
        self.pan += QPointF(anchor.x() - v.x(), anchor.y() - v.y())
        self.viewChanged.emit()
        self.update()

    def fit_view(self):
        self.zoom, self.pan = 1.0, QPointF(0, 0)
        self.viewChanged.emit()
        self.update()

    def wheelEvent(self, e):
        self.zoom_at(1.15 if e.angleDelta().y() > 0 else 1 / 1.15, e.position())

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _):
        ed, c = self.ed, self.ed.clip
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#222222"))
        s, ox, oy = self._fit()
        p.save()
        p.translate(ox, oy)
        p.scale(s, s)
        p.setRenderHint(QPainter.SmoothPixmapTransform, s < 1.0)   # crisp pixels when zoomed in
        p.setClipRect(QRectF(0, 0, c.w, c.h))
        p.fillRect(QRectF(0, 0, c.w, c.h), QColor(c.bg))
        if ed.onion and ed.cur > 0:
            p.setOpacity(0.3)
            p.drawImage(0, 0, ed.img_at(ed.cur - 1))
            p.setOpacity(1.0)
        p.drawImage(0, 0, ed.img_at(ed.cur))
        if self.stroke is not None:
            p.setOpacity(self.opacity * self.stroke.factor)
            p.drawImage(0, 0, self.stroke.buf)
            p.setOpacity(1.0)
        if self.tool == "shape" and self.shape_a is not None and self.shape_b is not None:
            p.setOpacity(self.opacity)
            sc, fc = self._shape_colors()
            paint.draw_shape(p, self.shape, self.shape_a, self.shape_b, sc, fc, self.size, self.shape_mode)
            p.setOpacity(1.0)
        if self.float_img is not None and self.sel is not None:
            p.drawImage(self.sel, self.float_img)
        ov = ed.mouth_overlay()                  # lip-sync mouth for the current moment
        if ov is not None:
            p.drawImage(ov[1], ov[0])
            if self.tool == "mouth":
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(255, 255, 255, 200), 2 / s, Qt.DashLine))
                p.drawRect(ov[1])
        guide = ed.guide_text()                  # lyric guide: shown here only, never exported
        if guide:
            f = QFont()
            f.setPixelSize(max(18, int(c.h * 0.045)))
            f.setBold(True)
            p.setFont(f)
            r = QRectF(c.w * 0.05, c.h * 0.86, c.w * 0.9, c.h * 0.11)
            p.setPen(QColor(0, 0, 0, 150))
            p.drawText(r.translated(2, 2), Qt.AlignCenter | Qt.TextWordWrap, guide)
            p.setPen(QColor(255, 220, 90, 230))
            p.drawText(r, Qt.AlignCenter | Qt.TextWordWrap, guide)
        p.restore()
        if self.sel is not None:                 # marching-ants outline + resize handle (screen space)
            a, b = self.to_view(self.sel.topLeft()), self.to_view(self.sel.bottomRight())
            r = QRectF(a, b)
            pen = QPen(QColor("#000000"), 1)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            pen = QPen(QColor("#ffffff"), 1, Qt.DashLine)
            p.setPen(pen)
            p.drawRect(r)
            p.setPen(QPen(QColor("#000000"), 1))
            p.setBrush(QColor("#ffffff"))
            p.drawRect(QRectF(r.right() - HANDLE / 2, r.bottom() - HANDLE / 2, HANDLE, HANDLE))
        if self.hover is not None and self.tool in ("brush", "eraser") and not self.space_down:
            d = max(5.0, self.size * (2 if self.tool == "eraser" else 1) * s)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 200), 1))
            p.drawEllipse(self.hover, d / 2 + 1, d / 2 + 1)
            p.setPen(QPen(QColor(255, 255, 255, 220), 1))
            p.drawEllipse(self.hover, d / 2, d / 2)

    # ------------------------------------------------------------------ helpers
    def _frame(self) -> QImage:
        return self.ed.img_at(self.ed.cur)

    def _canvas_rect(self) -> QRectF:
        c = self.ed.clip
        return QRectF(0, 0, c.w, c.h)

    def _shape_colors(self):
        a, b = self.primary, self.secondary
        if self._btn == Qt.RightButton:
            a, b = b, a
        return a, b

    def _width(self, pressure: float) -> float:
        return self.size * (0.2 + 0.8 * pressure) if self.tablet else float(self.size)

    # ------------------------------------------------------------------ pointer logic (image coordinates)
    def pointer_down(self, ip: QPointF, button=Qt.LeftButton, pressure: float = 1.0, mods=Qt.NoModifier):
        self._btn = button
        t = self.tool
        if mods & Qt.AltModifier and t != "select":
            return self.pick_color(ip, button)
        if t == "picker":
            return self.pick_color(ip, button)
        if t == "mouth":
            self._mouth_drag = True
            self.ed.set_mouth_pos(ip)
            return
        if t == "fill":
            return self.do_fill(ip, button)
        if t == "text":
            return self.do_text(ip, button)
        if t == "select":
            return self._sel_down(ip, mods)
        if t == "shape":
            self.shape_a = self.shape_b = QPointF(ip)
            return
        if t in ("brush", "eraser"):
            self.ed.push_undo()
            self._raw = self._smooth = QPointF(ip)
            col = self.primary if button != Qt.RightButton else self.secondary
            w = self._width(pressure) * (2 if t == "eraser" else 1)
            if t == "eraser":
                self.erasing = True
                paint.erase_segment(self._frame(), ip, ip, w)
            else:
                self.stroke = Stroke(self.ed.clip.w, self.ed.clip.h, self.brush, col)
                self.stroke.begin(ip, w)
            self.update()

    def pointer_move(self, ip: QPointF, pressure: float = 1.0, mods=Qt.NoModifier):
        t = self.tool
        if t == "mouth":
            if self._mouth_drag:
                self.ed.set_mouth_pos(ip)
            return
        if t == "select":
            return self._sel_move(ip, mods)
        if t == "shape" and self.shape_a is not None:
            self.shape_b = paint.constrain(self.shape, self.shape_a, ip) if mods & Qt.ShiftModifier else QPointF(ip)
            self.update()
            return
        if t in ("brush", "eraser") and self._raw is not None:
            self._raw = QPointF(ip)
            k = 1.0 - self.stab if t == "brush" else 1.0
            nxt = QPointF(self._smooth.x() + (ip.x() - self._smooth.x()) * k,
                          self._smooth.y() + (ip.y() - self._smooth.y()) * k)
            self._segment(self._smooth, nxt, pressure)
            self._smooth = nxt

    def _segment(self, a: QPointF, b: QPointF, pressure: float):
        w = self._width(pressure) * (2 if self.tool == "eraser" else 1)
        if self.erasing:
            paint.erase_segment(self._frame(), a, b, w)
        elif self.stroke is not None:
            self.stroke.add(a, b, w)
        self.update()

    def pointer_up(self, ip: QPointF, mods=Qt.NoModifier):
        t = self.tool
        if t == "mouth":
            self._mouth_drag = False
            return
        if t == "select":
            return self._sel_up()
        if t == "shape" and self.shape_a is not None:
            a, b = self.shape_a, self.shape_b or self.shape_a
            self.shape_a = self.shape_b = None
            if abs(b.x() - a.x()) + abs(b.y() - a.y()) >= 2:
                self.ed.push_undo()
                buf = paint.new_image(self.ed.clip.w, self.ed.clip.h)
                q = QPainter(buf)
                sc, fc = self._shape_colors()
                paint.draw_shape(q, self.shape, a, b, sc, fc, self.size, self.shape_mode)
                q.end()
                q = QPainter(self._frame())
                q.setOpacity(self.opacity)
                q.drawImage(0, 0, buf)
                q.end()
                self.ed.mark_dirty()
                self.strokeFinished.emit()
            self.update()
            return
        if t in ("brush", "eraser") and self._raw is not None:
            if self._smooth is not None and self._raw != self._smooth:
                self._segment(self._smooth, self._raw, 1.0)
            if self.stroke is not None:
                self.stroke.commit(self._frame(), self.opacity)
            self.stroke, self.erasing, self._raw, self._smooth = None, False, None, None
            self.ed.mark_dirty()
            self.strokeFinished.emit()
            self.update()

    # ------------------------------------------------------------------ simple tools
    def pick_color(self, ip: QPointF, button=Qt.LeftButton):
        c = paint.visible_color(self._frame(), int(ip.x()), int(ip.y()), QColor(self.ed.clip.bg))
        if c is not None:
            if button == Qt.RightButton:
                self.secondary = c
            else:
                self.primary = c
            self.colorsChanged.emit()

    def do_fill(self, ip: QPointF, button=Qt.LeftButton):
        col = self.primary if button != Qt.RightButton else self.secondary
        self.ed.push_undo()
        n = paint.flood_fill(self._frame(), int(ip.x()), int(ip.y()), col, self.tolerance, self.opacity)
        if n:
            self.ed.mark_dirty()
            self.strokeFinished.emit()
        self.update()

    def do_text(self, ip: QPointF, button=Qt.LeftButton, text: Optional[str] = None):
        if text is None:
            text, ok = QInputDialog.getMultiLineText(self, "Text", "Type your text:")
            if not ok:
                return
        if not text.strip():
            return
        col = self.primary if button != Qt.RightButton else self.secondary
        self.ed.push_undo()
        paint.draw_text(self._frame(), ip, text, self.font, col, self.opacity)
        self.ed.mark_dirty()
        self.strokeFinished.emit()
        self.update()

    # ------------------------------------------------------------------ selection
    def has_selection(self) -> bool:
        return self.sel is not None

    def has_float(self) -> bool:
        return self.float_img is not None

    def _handle_hit(self, ip: QPointF) -> bool:
        if self.sel is None:
            return False
        v = self.to_view(self.sel.bottomRight())
        w = self.to_view(ip)
        return abs(v.x() - w.x()) <= HANDLE and abs(v.y() - w.y()) <= HANDLE

    def _lift(self, copy: bool = False):
        """Cut the selected pixels out of the frame so they can be moved / resized / transformed."""
        if self.float_img is not None or self.sel is None:
            return
        r = self.sel.toRect().intersected(self._canvas_rect().toRect())
        if r.width() < 1 or r.height() < 1:
            self.sel = None
            return
        self.ed.push_undo()
        self.float_img = self._frame().copy(r).convertToFormat(FMT)
        if not copy:
            paint.clear_rect(self._frame(), QRectF(r))
        self.sel = QRectF(r)
        self.ed.mark_dirty()

    def commit_selection(self):
        """Stamp the lifted pixels back into the frame at their current place and size; drop the selection."""
        if self.float_img is not None and self.sel is not None:
            q = QPainter(self._frame())
            q.setRenderHint(QPainter.SmoothPixmapTransform)
            q.drawImage(self.sel, self.float_img)
            q.end()
            self.ed.mark_dirty()
            self.strokeFinished.emit()
        self.float_img, self.sel, self._sel_mode = None, None, None
        self.update()

    def discard_selection(self):
        """Forget the selection without drawing it (used by undo)."""
        self.float_img, self.sel, self._sel_mode = None, None, None
        self.update()

    def _sel_down(self, ip: QPointF, mods):
        if self.sel is not None and self._handle_hit(ip):
            self._lift()
            if self.float_img is not None:
                self._sel_mode = "resize"
                self._ratio = self.sel.width() / max(1.0, self.sel.height())
            return
        if self.sel is not None and self.sel.contains(ip):
            self._lift(copy=bool(mods & Qt.ControlModifier))
            if self.float_img is not None:
                self._sel_mode = "move"
                self._sel_off = ip - self.sel.topLeft()
            return
        self.commit_selection()
        c = self._canvas_rect()
        self._sel_anchor = QPointF(min(max(ip.x(), 0), c.width()), min(max(ip.y(), 0), c.height()))
        self.sel = QRectF(self._sel_anchor, self._sel_anchor)
        self._sel_mode = "new"
        self.update()

    def _sel_move(self, ip: QPointF, mods):
        m = self._sel_mode
        if m == "new":
            c = self._canvas_rect()
            q = QPointF(min(max(ip.x(), 0), c.width()), min(max(ip.y(), 0), c.height()))
            self.sel = QRectF(self._sel_anchor, q).normalized()
        elif m == "move" and self.sel is not None:
            self.sel.moveTo(ip - self._sel_off)
        elif m == "resize" and self.sel is not None:
            tl = self.sel.topLeft()
            w, h = max(4.0, ip.x() - tl.x()), max(4.0, ip.y() - tl.y())
            if mods & Qt.ShiftModifier:
                h = w / self._ratio
            self.sel = QRectF(tl, QPointF(tl.x() + w, tl.y() + h))
        self.update()

    def _sel_up(self):
        if self._sel_mode == "new" and self.sel is not None and (self.sel.width() < 3 or self.sel.height() < 3):
            self.sel = None
        self._sel_mode = None
        self.update()

    def select_all(self):
        self.set_tool("select")
        self.commit_selection()
        self.sel = self._canvas_rect()
        self.update()

    def delete_selection(self):
        if self.float_img is not None:
            self.float_img, self.sel = None, None
        elif self.sel is not None:
            self.ed.push_undo()
            paint.clear_rect(self._frame(), self.sel)
            self.ed.mark_dirty()
            self.sel = None
        self.strokeFinished.emit()
        self.update()

    def flip(self, horizontal: bool):
        self._lift()
        if self.float_img is not None:
            self.float_img = _mirror(self.float_img, horizontal)
            self.update()

    def rotate90(self, clockwise: bool = True):
        self._lift()
        if self.float_img is not None and self.sel is not None:
            self.float_img = self.float_img.transformed(QTransform().rotate(90 if clockwise else -90))
            c = self.sel.center()
            w, h = self.sel.height(), self.sel.width()
            self.sel = QRectF(c.x() - w / 2, c.y() - h / 2, w, h)
            self.update()

    def selection_image(self) -> Optional[QImage]:
        if self.float_img is not None:
            return self.float_img
        if self.sel is not None:
            r = self.sel.toRect().intersected(self._canvas_rect().toRect())
            if r.width() > 0 and r.height() > 0:
                return self._frame().copy(r)
        return None

    def copy(self):
        im = self.selection_image()
        if im is not None:
            QGuiApplication.clipboard().setImage(im.convertToFormat(QImage.Format_ARGB32))

    def cut(self):
        self.copy()
        self.delete_selection()

    def paste(self, image: Optional[QImage] = None):
        im = image if image is not None else QGuiApplication.clipboard().image()
        if im is None or im.isNull():
            return
        self.set_tool("select")
        self.commit_selection()
        self.ed.push_undo()
        im = im.convertToFormat(FMT)
        c = self.ed.clip
        if im.width() > c.w or im.height() > c.h:                       # larger than the canvas: fit it
            im = im.scaled(c.w, c.h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        top = self.to_img(QPointF(0, 0))
        x = max(0.0, min(top.x() + 24, c.w - im.width()))
        y = max(0.0, min(top.y() + 24, c.h - im.height()))
        self.float_img = im
        self.sel = QRectF(x, y, im.width(), im.height())
        self.update()

    # ------------------------------------------------------------------ Qt events
    def _pan_start(self, e) -> bool:
        if e.button() == Qt.MiddleButton or self.tool == "hand" or self.space_down:
            self._pan_last = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return True
        return False

    def mousePressEvent(self, e):
        self.setFocus()
        if self.ed.playing:
            return
        if self._pan_start(e):
            return
        if e.button() in (Qt.LeftButton, Qt.RightButton):
            self.pointer_down(self.to_img(e.position()), e.button(), 1.0, e.modifiers())

    def mouseMoveEvent(self, e):
        self.hover = e.position()
        if self._pan_last is not None:
            self.pan += e.position() - self._pan_last
            self._pan_last = e.position()
            self.viewChanged.emit()
            self.update()
            return
        self.pointer_move(self.to_img(e.position()), 1.0, e.modifiers())
        self.update()

    def mouseReleaseEvent(self, e):
        if self._pan_last is not None:
            self._pan_last = None
            self.setCursor(Qt.CrossCursor)
            return
        if e.button() in (Qt.LeftButton, Qt.RightButton):
            self.pointer_up(self.to_img(e.position()), e.modifiers())

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    def tabletEvent(self, e):
        """Pen tablets: pressure changes the brush width; the pen's eraser end erases."""
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QPointingDevice
        self.tablet = True
        pos, t = e.position(), e.type()
        pressure = max(0.02, float(e.pressure()))
        if t == QEvent.TabletPress:
            self.setFocus()
            if e.pointerType() == QPointingDevice.PointerType.Eraser and self.tool == "brush":
                self._pen_eraser_restore = self.tool
                self.tool = "eraser"
            self.pointer_down(self.to_img(pos), Qt.LeftButton, pressure, e.modifiers())
        elif t == QEvent.TabletMove:
            self.hover = pos
            self.pointer_move(self.to_img(pos), pressure, e.modifiers())
        elif t == QEvent.TabletRelease:
            self.pointer_up(self.to_img(pos), e.modifiers())
            if getattr(self, "_pen_eraser_restore", None):
                self.tool, self._pen_eraser_restore = self._pen_eraser_restore, None
        e.accept()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self.space_down = True
            self.setCursor(Qt.OpenHandCursor)
        elif e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.sel is not None:
            self.delete_selection()
        elif e.key() == Qt.Key_Escape:
            self.commit_selection()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self.space_down = False
            self.setCursor(Qt.CrossCursor)
        else:
            super().keyReleaseEvent(e)
