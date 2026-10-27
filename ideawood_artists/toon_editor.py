"""Draw a cartoon for one scene, frame by frame, while the song plays.

The song is the clock: Play starts the audio at the scene's start and shows the frame that belongs to the current
moment (the clip loops if it is shorter than the scene). The lyric being sung is shown as a guide on the canvas,
never saved into the drawing. Frames are saved to disk as you leave them, so long clips do not eat memory.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QDialog, QHBoxLayout, QLabel, QListView,
                               QListWidget, QListWidgetItem, QMessageBox, QProgressDialog, QPushButton, QSlider,
                               QSpinBox, QVBoxLayout, QWidget, QApplication)

from . import toon
from .project import Project, frame_size
from .toon import ToonClip

THUMB = QSize(112, 63)
CACHE_MAX = 30
DRAW_SHORT_SIDE = 720


def new_clip_for(p: Project, folder: Optional[str] = None) -> ToonClip:
    w, h = frame_size(p.fmt, DRAW_SHORT_SIDE)
    return ToonClip.new(w, h, 12, folder)


class ToonCanvas(QWidget):
    stroke_done = Signal()

    def __init__(self, ed: "ToonEditor"):
        super().__init__()
        self.ed = ed
        self.last: Optional[QPointF] = None
        self.setMinimumSize(560, 320)
        self.setCursor(Qt.CrossCursor)

    def _fit(self):
        c = self.ed.clip
        s = min(self.width() / c.w, self.height() / c.h) * 0.97
        return s, (self.width() - c.w * s) / 2, (self.height() - c.h * s) / 2

    def _to_img(self, pos) -> QPointF:
        s, ox, oy = self._fit()
        return QPointF((pos.x() - ox) / s, (pos.y() - oy) / s)

    def paintEvent(self, _):
        ed, c = self.ed, self.ed.clip
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#222222"))
        s, ox, oy = self._fit()
        p.translate(ox, oy)
        p.scale(s, s)
        p.fillRect(QRectF(0, 0, c.w, c.h), QColor(c.bg))
        if ed.onion and ed.cur > 0:
            p.setOpacity(0.3)
            p.drawImage(0, 0, ed.img_at(ed.cur - 1))
            p.setOpacity(1.0)
        p.drawImage(0, 0, ed.img_at(ed.cur))
        guide = ed.guide_text()                       # lyric guide: shown here only, never exported
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

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.ed.playing:
            self.ed.push_undo()
            self.last = self._to_img(e.position())
            self.ed.stroke(self.last, self.last)
            self.update()

    def mouseMoveEvent(self, e):
        if self.last is not None:
            pt = self._to_img(e.position())
            self.ed.stroke(self.last, pt)
            self.last = pt
            self.update()

    def mouseReleaseEvent(self, e):
        if self.last is not None:
            self.last = None
            self.stroke_done.emit()


class ToonEditor(QDialog):
    def __init__(self, parent, project: Project, scene_index: int):
        super().__init__(parent)
        self.p = project
        self.scene = project.scenes[scene_index]
        self.setWindowTitle(f"Draw a cartoon  -  scene starting {self.scene.start:0.1f}s")
        self.resize(1180, 820)
        sc = self.scene
        self.clip = ToonClip.load(sc.toon) if sc.toon and os.path.isfile(os.path.join(sc.toon, toon.META)) \
            else new_clip_for(project)
        self.imgs: Dict[int, QImage] = {}
        self.dirty: set = set()
        self.undo_stack: List[tuple] = []
        self.cur = 0
        self.tool, self.color, self.size, self.onion = "pen", QColor("#111111"), 7, True
        self.playing = False
        self.player = None
        self.audio_out = None
        self.result_clip: Optional[ToonClip] = None

        self.canvas = ToonCanvas(self)
        self.canvas.stroke_done.connect(self._stroke_done)
        self.timeline = QListWidget()
        self.timeline.setViewMode(QListView.IconMode)
        self.timeline.setFlow(QListView.LeftToRight)
        self.timeline.setWrapping(False)
        self.timeline.setMovement(QListView.Static)
        self.timeline.setIconSize(THUMB)
        self.timeline.setFixedHeight(132)
        self.timeline.currentRowChanged.connect(self.goto)
        self.info = QLabel()
        self.info.setObjectName("muted")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

        lay = QVBoxLayout(self)
        lay.addLayout(self._tools_row())
        lay.addLayout(self._frames_row())
        lay.addWidget(self.canvas, 1)
        lay.addWidget(self.timeline)
        lay.addWidget(self.info)
        ok = QPushButton("Save && use as this scene's background")
        ok.setDefault(False)
        ok.clicked.connect(self.save_and_close)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

        for key, fn in (("Ctrl+Z", self.undo), (",", lambda: self.goto(self.cur - 1)),
                        (".", lambda: self.goto(self.cur + 1)), ("Space", self.toggle_play)):
            QShortcut(QKeySequence(key), self, activated=fn)
        self.refresh_timeline()

    # ------------------------------------------------------------------ UI rows
    def _tools_row(self):
        row = QHBoxLayout()
        grp = QButtonGroup(self)
        for name, label in (("pen", "Pen"), ("eraser", "Eraser")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setChecked(name == self.tool)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, n=name: setattr(self, "tool", n))
            grp.addButton(b)
            row.addWidget(b)
        self.color_btn = QPushButton("Color")
        self.color_btn.clicked.connect(self.pick_color)
        self.bg_btn = QPushButton("Background")
        self.bg_btn.clicked.connect(self.pick_bg)
        row.addWidget(self.color_btn)
        row.addWidget(self.bg_btn)
        row.addWidget(QLabel("Size"))
        sl = QSlider(Qt.Horizontal)
        sl.setRange(1, 80)
        sl.setValue(self.size)
        sl.setFixedWidth(130)
        sl.valueChanged.connect(lambda v: setattr(self, "size", v))
        row.addWidget(sl)
        on = QCheckBox("Onion skin")
        on.setChecked(True)
        on.toggled.connect(self._onion)
        row.addWidget(on)
        row.addStretch(1)
        self._paint_color_btn()
        return row

    def _frames_row(self):
        row = QHBoxLayout()
        for text, fn in (("+ Frame", self.add_frame), ("Duplicate", self.dup_frame), ("Delete", self.del_frame),
                         ("Fill scene length", self.fill_scene)):
            b = QPushButton(text)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addWidget(QLabel("FPS"))
        self.fps = QSpinBox()
        self.fps.setRange(4, 30)
        self.fps.setValue(self.clip.fps)
        self.fps.valueChanged.connect(self._fps)
        row.addWidget(self.fps)
        self.play_btn = QPushButton("Play with song")
        self.play_btn.setFocusPolicy(Qt.NoFocus)
        self.play_btn.clicked.connect(self.toggle_play)
        row.addWidget(self.play_btn)
        row.addStretch(1)
        return row

    def _paint_color_btn(self):
        self.color_btn.setStyleSheet(f"border-left: 14px solid {self.color.name()};")
        self.bg_btn.setStyleSheet(f"border-left: 14px solid {self.clip.bg};")

    def pick_color(self):
        c = QColorDialog.getColor(self.color, self)
        if c.isValid():
            self.color = c
            self._paint_color_btn()

    def pick_bg(self):
        c = QColorDialog.getColor(QColor(self.clip.bg), self)
        if c.isValid():
            self.clip.bg = c.name()
            self._paint_color_btn()
            self.canvas.update()
            self.refresh_timeline()

    def _onion(self, on):
        self.onion = on
        self.canvas.update()

    def _fps(self, v):
        self.clip.fps = v
        if self.playing:
            self.timer.setInterval(int(1000 / v))
        self._status()

    # ------------------------------------------------------------------ frame images (lazy, saved as you leave)
    def img_at(self, i: int) -> QImage:
        fid = self.clip.order[i]
        im = self.imgs.get(fid)
        if im is None:
            path = self.clip.path_of(fid)
            im = QImage(path) if os.path.isfile(path) else QImage()
            if im.isNull() or im.size() != QSize(self.clip.w, self.clip.h):
                im = QImage(self.clip.w, self.clip.h, QImage.Format_ARGB32_Premultiplied)
                im.fill(Qt.transparent)
            else:
                im = im.convertToFormat(QImage.Format_ARGB32_Premultiplied)
            self.imgs[fid] = im
            self._evict()
        return im

    def _flush(self, fid: int):
        if fid in self.dirty and fid in self.imgs:
            self.imgs[fid].save(self.clip.path_of(fid), "PNG")
            self.dirty.discard(fid)

    def _evict(self):
        if len(self.imgs) <= CACHE_MAX:
            return
        keep = {self.clip.order[self.cur], self.clip.order[max(0, self.cur - 1)]}
        for fid in list(self.imgs):
            if fid in keep:
                continue
            self._flush(fid)
            del self.imgs[fid]
            if len(self.imgs) <= CACHE_MAX // 2:
                break

    def flush_all(self):
        for fid in list(self.dirty):
            self._flush(fid)
        self.clip.save_meta()

    def composite(self, i: int) -> QImage:
        out = QImage(self.clip.w, self.clip.h, QImage.Format_RGB32)
        out.fill(QColor(self.clip.bg))
        p = QPainter(out)
        p.drawImage(0, 0, self.img_at(i))
        p.end()
        return out

    # ------------------------------------------------------------------ drawing
    def push_undo(self):
        fid = self.clip.order[self.cur]
        self.undo_stack.append((fid, self.img_at(self.cur).copy()))
        del self.undo_stack[:-60]

    def undo(self):
        while self.undo_stack:
            fid, im = self.undo_stack.pop()
            if fid in self.clip.order:
                self.imgs[fid] = im
                self.dirty.add(fid)
                self.goto(self.clip.order.index(fid))
                self.update_thumb(self.cur)
                return

    def stroke(self, a: QPointF, b: QPointF):
        fid = self.clip.order[self.cur]
        im = self.img_at(self.cur)
        p = QPainter(im)
        p.setRenderHint(QPainter.Antialiasing)
        if self.tool == "eraser":
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            pen = QPen(Qt.black, self.size * 2)
        else:
            pen = QPen(self.color, self.size)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawLine(a, b)
        p.end()
        self.dirty.add(fid)

    def _stroke_done(self):
        self.update_thumb(self.cur)

    # ------------------------------------------------------------------ timeline
    def _icon(self, i: int) -> QIcon:
        return QIcon(QPixmap.fromImage(self.composite(i)).scaled(THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def refresh_timeline(self):
        self.timeline.blockSignals(True)
        self.timeline.clear()
        for i in range(len(self.clip)):
            self.timeline.addItem(QListWidgetItem(self._icon(i), str(i + 1)))
        self.timeline.setCurrentRow(self.cur)
        self.timeline.blockSignals(False)
        self._status()
        self.canvas.update()

    def update_thumb(self, i: int):
        it = self.timeline.item(i)
        if it:
            it.setIcon(self._icon(i))

    def goto(self, i: int):
        i = max(0, min(i, len(self.clip) - 1))
        if i != self.cur:
            self._flush(self.clip.order[self.cur])
        self.cur = i
        self.timeline.blockSignals(True)
        self.timeline.setCurrentRow(i)
        self.timeline.blockSignals(False)
        self._status()
        self.canvas.update()

    def _status(self):
        sc = self.scene
        n = len(self.clip)
        self.info.setText(f"Frame {self.cur + 1}/{n}  |  clip {self.clip.seconds:0.1f}s of the scene's {sc.duration:0.1f}s "
                          f"(shorter clips loop)  |  {self.clip.w}x{self.clip.h}  |  keys: Space play, , and . step, Ctrl+Z undo")

    def guide_text(self) -> str:
        t = self.scene.start + self.cur / float(self.clip.fps)
        for ln in self.p.lines:
            if ln.timed and ln.start <= t < ln.end:
                return ln.text
        return ""

    def add_frame(self):
        self.goto_after(self.clip.insert_blank(self.cur))

    def dup_frame(self):
        self._flush(self.clip.order[self.cur])
        self.goto_after(self.clip.duplicate(self.cur))

    def del_frame(self):
        fid = self.clip.order[self.cur]
        self.dirty.discard(fid)
        self.imgs.pop(fid, None)
        self.goto_after(self.clip.delete(self.cur))

    def fill_scene(self):
        self.clip.extend_to(self.scene.duration)
        self.refresh_timeline()

    def goto_after(self, i: int):
        self.cur = max(0, min(i, len(self.clip) - 1))
        self.refresh_timeline()

    # ------------------------------------------------------------------ playback (the song is the clock)
    def _ensure_player(self):
        if self.player is None:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            self.player, self.audio_out = QMediaPlayer(self), QAudioOutput(self)
            self.player.setAudioOutput(self.audio_out)
            self.player.setSource(QUrl.fromLocalFile(self.p.audio))

    def toggle_play(self):
        if self.playing:
            return self.stop()
        self.playing = True
        self.play_btn.setText("Stop")
        self._flush(self.clip.order[self.cur])
        has_audio = bool(self.p.audio and os.path.isfile(self.p.audio))
        if has_audio:
            self._ensure_player()
            self.player.setPosition(int((self.scene.start + self.cur / float(self.clip.fps)) * 1000))
            self.player.play()
        self.timer.start(int(1000 / self.clip.fps))

    def stop(self):
        self.playing = False
        self.timer.stop()
        if self.player is not None:
            self.player.pause()
        self.play_btn.setText("Play with song")

    def _tick(self):
        n = len(self.clip)
        if self.player is not None and self.player.playbackState() == self.player.PlaybackState.PlayingState:
            t = self.player.position() / 1000.0 - self.scene.start
            if t >= self.scene.duration:
                return self.stop()
            nxt = int(max(0.0, t) * self.clip.fps) % n
        else:
            nxt = (self.cur + 1) % n
        self.cur = nxt
        self.timeline.blockSignals(True)
        self.timeline.setCurrentRow(nxt)
        self.timeline.blockSignals(False)
        self._status()
        self.canvas.update()

    # ------------------------------------------------------------------ finish
    def save_and_close(self):
        self.stop()
        self.flush_all()
        n = len(self.clip)
        dlg = QProgressDialog("Making the cartoon clip...", "Cancel", 0, n, self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)

        def frames():
            for i in range(n):
                yield bytes(self.composite(i).constBits())

        def prog(k):
            dlg.setValue(k)
            QApplication.processEvents()
        try:
            toon.export_mp4(self.clip, frames(), on_progress=prog, should_cancel=dlg.wasCanceled)
        except Exception as e:  # noqa: BLE001
            dlg.close()
            if not dlg.wasCanceled():
                QMessageBox.warning(self, "Cartoon", str(e))
            return
        dlg.close()
        self.result_clip = self.clip
        self.accept()

    def reject(self):
        self.stop()
        self.flush_all()          # keep drawn frames on disk even if the clip was not exported
        super().reject()
