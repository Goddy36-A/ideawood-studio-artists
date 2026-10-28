"""Draw a cartoon for one scene, frame by frame, while the song plays.

The drawing board has Paint-3D-style 2D tools (see toon_board.py / toon_tools.py). The song is the clock: Play starts
the audio at the scene's start and shows the frame that belongs to the current moment (the clip loops if it is
shorter than the scene). The lyric being sung is shown as a guide on the canvas, never saved into the drawing.
Frames are saved to disk as you leave them, so long clips do not eat memory.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QIcon, QImage, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QDialog, QHBoxLayout, QLabel, QListView,
                               QListWidget, QListWidgetItem, QMessageBox, QProgressDialog, QPushButton, QScrollArea,
                               QSpinBox, QVBoxLayout)

from . import toon
from .project import Project, frame_size
from .toon import ToonClip
from .toon_board import PaintBoard
from .toon_tools import ToolPanel

THUMB = QSize(112, 63)
CACHE_MAX = 30
UNDO_MAX = 80
DRAW_SHORT_SIDE = 720


def new_clip_for(p: Project, folder: Optional[str] = None) -> ToonClip:
    w, h = frame_size(p.fmt, DRAW_SHORT_SIDE)
    return ToonClip.new(w, h, 12, folder)


def _btn(text, fn, tip="") -> QPushButton:
    b = QPushButton(text)
    b.setAutoDefault(False)
    b.setFocusPolicy(Qt.NoFocus)
    b.clicked.connect(lambda _=False: fn())
    if tip:
        b.setToolTip(tip)
    return b


class ToonEditor(QDialog):
    def __init__(self, parent, project: Project, scene_index: int):
        super().__init__(parent)
        self.p = project
        self.scene = project.scenes[scene_index]
        self.setWindowTitle(f"Draw a cartoon  -  scene starting {self.scene.start:0.1f}s")
        self.resize(1360, 880)
        sc = self.scene
        self.clip = ToonClip.load(sc.toon) if sc.toon and os.path.isfile(os.path.join(sc.toon, toon.META)) \
            else new_clip_for(project)
        self.imgs: Dict[int, QImage] = {}
        self.dirty: set = set()
        self.undo_stack: List[tuple] = []
        self.redo_stack: List[tuple] = []
        self.cur = 0
        self.onion = True
        self.playing = False
        self.player = None
        self.audio_out = None
        self.result_clip: Optional[ToonClip] = None

        self.board = PaintBoard(self)
        self.board.strokeFinished.connect(lambda: self.update_thumb(self.cur))
        self.panel = ToolPanel(self.board)
        side = QScrollArea()
        side.setWidget(self.panel)
        side.setWidgetResizable(True)
        side.setFixedWidth(272)
        side.setFrameShape(QScrollArea.NoFrame)

        self.timeline = QListWidget()
        self.timeline.setViewMode(QListView.IconMode)
        self.timeline.setFlow(QListView.LeftToRight)
        self.timeline.setWrapping(False)
        self.timeline.setMovement(QListView.Static)
        self.timeline.setIconSize(THUMB)
        self.timeline.setFixedHeight(132)
        self.timeline.setFocusPolicy(Qt.NoFocus)
        self.timeline.currentRowChanged.connect(self.goto)
        self.info = QLabel()
        self.info.setObjectName("muted")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

        lay = QVBoxLayout(self)
        lay.addLayout(self._top_row())
        mid = QHBoxLayout()
        mid.addWidget(side)
        mid.addWidget(self.board, 1)
        lay.addLayout(mid, 1)
        lay.addWidget(self.timeline)
        lay.addWidget(self.info)
        ok = _btn("Save && use as this scene's background", self.save_and_close)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(_btn("Cancel", self.cancel))
        row.addWidget(ok)
        lay.addLayout(row)
        self._shortcuts()
        self.refresh_timeline()
        self.board.viewChanged.emit()

    # ------------------------------------------------------------------ UI
    def _top_row(self):
        row = QHBoxLayout()
        row.addWidget(_btn("Undo", self.undo, "Ctrl+Z"))
        row.addWidget(_btn("Redo", self.redo, "Ctrl+Y"))
        for text, fn in (("+ Frame", self.add_frame), ("Duplicate", self.dup_frame), ("Delete", self.del_frame),
                         ("Fill scene length", self.fill_scene)):
            row.addWidget(_btn(text, fn))
        row.addWidget(QLabel("FPS"))
        self.fps = QSpinBox()
        self.fps.setRange(4, 30)
        self.fps.setValue(self.clip.fps)
        self.fps.setFocusPolicy(Qt.ClickFocus)
        self.fps.valueChanged.connect(self._fps)
        row.addWidget(self.fps)
        self.bg_btn = _btn("Background", self.pick_bg)
        row.addWidget(self.bg_btn)
        on = QCheckBox("Onion skin")
        on.setChecked(True)
        on.setFocusPolicy(Qt.NoFocus)
        on.toggled.connect(self._onion)
        row.addWidget(on)
        self.play_btn = _btn("Play with song", self.toggle_play, "P")
        row.addWidget(self.play_btn)
        row.addStretch(1)
        self._paint_bg_btn()
        return row

    def _shortcuts(self):
        def sc(key, fn):
            QShortcut(QKeySequence(key), self, activated=fn)
        sc("Ctrl+Z", self.undo)
        sc("Ctrl+Y", self.redo)
        sc("Ctrl+Shift+Z", self.redo)
        sc(",", lambda: self.goto(self.cur - 1))
        sc(".", lambda: self.goto(self.cur + 1))
        sc("P", self.toggle_play)
        sc("Ctrl+A", self.board.select_all)
        sc("Ctrl+C", self.board.copy)
        sc("Ctrl+X", self.board.cut)
        sc("Ctrl+V", self.board.paste)
        sc("Ctrl+=", lambda: self.board.zoom_at(1.25))
        sc("Ctrl++", lambda: self.board.zoom_at(1.25))
        sc("Ctrl+-", lambda: self.board.zoom_at(1 / 1.25))
        sc("Ctrl+0", self.board.fit_view)
        sc("X", self.board.swap_colors)
        sc("[", lambda: self.panel.set_size(self.board.size - max(1, self.board.size // 8)))
        sc("]", lambda: self.panel.set_size(self.board.size + max(1, self.board.size // 8)))
        for key, name in (("B", "brush"), ("E", "eraser"), ("F", "fill"), ("U", "shape"), ("T", "text"),
                          ("M", "select"), ("I", "picker"), ("H", "hand")):
            sc(key, lambda n=name: self.board.set_tool(n))

    def _paint_bg_btn(self):
        self.bg_btn.setStyleSheet(f"border-left: 14px solid {self.clip.bg};")

    def pick_bg(self):
        c = QColorDialog.getColor(QColor(self.clip.bg), self)
        if c.isValid():
            self.clip.bg = c.name()
            self._paint_bg_btn()
            self.board.update()
            self.refresh_timeline()

    def _onion(self, on):
        self.onion = on
        self.board.update()

    def _fps(self, v):
        self.clip.fps = v
        if self.playing:
            self.timer.setInterval(int(1000 / v))
        self._status()

    # ------------------------------------------------------------------ frame images (lazy, saved as you leave)
    def img_of(self, fid: int) -> QImage:
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

    def img_at(self, i: int) -> QImage:
        return self.img_of(self.clip.order[i])

    def mark_dirty(self):
        self.dirty.add(self.clip.order[self.cur])

    def _flush(self, fid: int):
        if fid in self.dirty and fid in self.imgs:
            self.imgs[fid].save(self.clip.path_of(fid), "PNG")
            self.dirty.discard(fid)

    def _evict(self):
        if len(self.imgs) <= CACHE_MAX:
            return
        keep = {self.clip.order[min(self.cur, len(self.clip) - 1)], self.clip.order[max(0, self.cur - 1)]}
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

    # ------------------------------------------------------------------ undo / redo (per frame image, by frame id)
    def push_undo(self):
        fid = self.clip.order[self.cur]
        self.undo_stack.append((fid, self.img_of(fid).copy()))
        del self.undo_stack[:-UNDO_MAX]
        self.redo_stack.clear()

    def _swap_from(self, src: List[tuple], dst: List[tuple]) -> bool:
        while src:
            fid, im = src.pop()
            if fid in self.clip.order:
                dst.append((fid, self.img_of(fid).copy()))
                self.imgs[fid] = im
                self.dirty.add(fid)
                self.board.discard_selection()
                self.goto(self.clip.order.index(fid))
                self.update_thumb(self.cur)
                return True
        return False

    def undo(self):
        self._swap_from(self.undo_stack, self.redo_stack)

    def redo(self):
        self._swap_from(self.redo_stack, self.undo_stack)

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
        self.board.update()

    def update_thumb(self, i: int):
        it = self.timeline.item(i)
        if it:
            it.setIcon(self._icon(i))

    def _settle(self):
        """Place any floating selection and save the current frame before the frame list changes."""
        self.board.commit_selection()
        self._flush(self.clip.order[self.cur])

    def goto(self, i: int):
        i = max(0, min(i, len(self.clip) - 1))
        if i != self.cur:
            self._settle()
        self.cur = i
        self.timeline.blockSignals(True)
        self.timeline.setCurrentRow(i)
        self.timeline.blockSignals(False)
        self._status()
        self.board.update()

    def _status(self):
        sc = self.scene
        self.info.setText(f"Frame {self.cur + 1}/{len(self.clip)}  |  clip {self.clip.seconds:0.1f}s of the scene's "
                          f"{sc.duration:0.1f}s (shorter clips loop)  |  {self.clip.w}x{self.clip.h}  |  keys: P play, "
                          f", and . step frames, Space+drag pan, [ ] brush size, Ctrl+Z undo")

    def guide_text(self) -> str:
        t = self.scene.start + self.cur / float(self.clip.fps)
        for ln in self.p.lines:
            if ln.timed and ln.start <= t < ln.end:
                return ln.text
        return ""

    def add_frame(self):
        self._settle()
        self.goto_after(self.clip.insert_blank(self.cur))

    def dup_frame(self):
        self._settle()
        self.goto_after(self.clip.duplicate(self.cur))

    def del_frame(self):
        self.board.discard_selection()
        fid = self.clip.order[self.cur]
        self.dirty.discard(fid)
        self.imgs.pop(fid, None)
        self.goto_after(self.clip.delete(self.cur))

    def fill_scene(self):
        self._settle()
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
        self._settle()
        self.playing = True
        self.play_btn.setText("Stop")
        if self.p.audio and os.path.isfile(self.p.audio):
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
        self.board.update()

    # ------------------------------------------------------------------ finish
    def save_and_close(self):
        self.stop()
        self.board.commit_selection()
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

    def cancel(self):
        self.stop()
        self.board.commit_selection()
        self.flush_all()          # keep drawn frames on disk even if the clip was not exported
        QDialog.reject(self)

    def reject(self):
        """Esc: first place a floating selection, a second Esc closes."""
        if self.board.has_selection():
            self.board.commit_selection()
            return
        self.cancel()
