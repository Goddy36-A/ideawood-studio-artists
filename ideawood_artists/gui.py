"""Ideawood Studio for Artists - main window.

Steps: 1 Song & lyrics -> 2 Timing -> 3 Look -> 4 Visuals (AI) -> 5 Export, with a live preview frame on the right.
Heavy work (speech recognition, AI search, rendering) runs in worker threads so the window never freezes.
"""
from __future__ import annotations

import os
import sys
import tempfile

from PySide6.QtCore import QSettings, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFontDatabase, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox, QDialog,
                               QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QScrollArea, QSlider, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from . import APP_NAME, __version__, asr, fonts, lyrics, render, scenes as scn, syncer, visuals
from .cloud import CloudClient, CloudError, parse_storyboard
from .paths import asset_path, bundled_fonts_dir, user_fonts_dir
from .project import FORMATS, LOGO_POSITIONS, QUALITIES, Project
from .styles import ANIMATIONS, GRADES, HIGHLIGHTS, PRESETS, TRANSITIONS, VIZ_MODES, LyricStyle
from .theme import ACCENT_PRESETS, THEMES, apply_theme
from .toon_editor import ToonEditor

AUDIO_FILTER = "Songs (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.mp4 *.mov *.mkv);;All files (*)"
GENRES = ["", "Afrobeats", "Reggae", "Hip hop", "Gospel", "R&B", "Pop", "Rock", "Acoustic", "Dancehall", "Funk / Disco"]


# --------------------------------------------------------------------------- small UI helpers
def card(title: str, subtitle: str = ""):
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)
    t = QLabel(title)
    t.setObjectName("h")
    lay.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("muted")
        s.setWordWrap(True)
        lay.addWidget(s)
    return f, lay


def hrow(*widgets, stretch_first=False):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for i, x in enumerate(widgets):
        if isinstance(x, str):
            lbl = QLabel(x)
            lbl.setObjectName("muted")
            h.addWidget(lbl)
        else:
            h.addWidget(x, 1 if (stretch_first and i == 0) else 0)
    return w


def combo(items, current=""):
    c = QComboBox()
    c.addItems(list(items))
    if current in items:
        c.setCurrentText(current)
    return c


def btn(text, fn=None, primary=False):
    b = QPushButton(text)
    if primary:
        b.setObjectName("primary")
    if fn:
        b.clicked.connect(fn)
    return b


def scroll(*cards):
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(4, 4, 12, 4)
    lay.setSpacing(12)
    for c in cards:
        lay.addWidget(c)
    lay.addStretch(1)
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(inner)
    return sa


def fmt_t(sec: float) -> str:
    sec = max(sec, 0.0)
    m, s = divmod(sec, 60)
    return f"{int(m)}:{s:05.2f}"


def parse_t(s: str):
    import re
    m = re.match(r"^\s*(?:(\d+):)?(\d+(?:[.,]\d+)?)\s*$", s or "")
    if not m:
        return None
    return int(m.group(1) or 0) * 60 + float(m.group(2).replace(",", "."))


class Worker(QThread):
    status = Signal(str)
    progress = Signal(float)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn, self.stop = fn, False

    def run(self):
        try:
            self.done.emit(self.fn(self))
        except (asr.Cancelled, render.Cancelled):
            self.failed.emit("Cancelled")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class FrameWorker(QThread):
    ready = Signal(int, str)

    def __init__(self, seq, project, t, out):
        super().__init__()
        self.seq, self.project, self.t, self.out = seq, project, t, out

    def run(self):
        try:
            render.preview_frame(self.project, self.t, self.out)
            self.ready.emit(self.seq, self.out)
        except Exception as e:  # noqa: BLE001
            self.ready.emit(self.seq, "ERR:" + str(e))


# --------------------------------------------------------------------------- dialogs
class TapSync(QDialog):
    """Play the song and tap SPACE as each line starts - the reliable way for languages speech recognition lacks."""

    def __init__(self, parent, audio: str, line_texts):
        super().__init__(parent)
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        self.setWindowTitle("Tap to sync")
        self.resize(720, 360)
        self.texts, self.starts, self.i = list(line_texts), [], 0
        self.player, self.out = QMediaPlayer(self), QAudioOutput(self)
        self.player.setAudioOutput(self.out)
        self.player.setSource(QUrl.fromLocalFile(audio))
        lay = QVBoxLayout(self)
        info = QLabel("Press Play, then tap SPACE exactly when each line starts being sung. Backspace goes back one "
                      "line. After the last line tap SPACE once more when it ends.")
        info.setWordWrap(True)
        info.setObjectName("muted")
        self.cur, self.nxt = QLabel(""), QLabel("")
        self.cur.setAlignment(Qt.AlignCenter)
        self.cur.setWordWrap(True)
        self.cur.setStyleSheet("font-size: 22pt; font-weight: 700;")
        self.nxt.setAlignment(Qt.AlignCenter)
        self.nxt.setObjectName("muted")
        self.nxt.setWordWrap(True)
        self.clock = QLabel("0:00.00")
        self.clock.setAlignment(Qt.AlignCenter)
        self.play = btn("Play / pause", self.toggle, True)
        self.tap = btn("TAP (Space)", self.mark)
        self.undo = btn("Back one line", self.back)
        self.finish = btn("Done", self.accept)
        for w in (info, self.cur, self.nxt, self.clock, hrow(self.play, self.tap, self.undo, self.finish)):
            lay.addWidget(w)
        self.tm = QTimer(self)
        self.tm.timeout.connect(lambda: self.clock.setText(fmt_t(self.player.position() / 1000.0)))
        self.tm.start(50)
        self.last_end = None
        self.show_line()

    def toggle(self):
        if self.player.playbackState() == self.player.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()
        self.setFocus()

    def show_line(self):
        n = len(self.texts)
        self.cur.setText(self.texts[self.i] if self.i < n else "(tap once more at the end of the last line)"
                         if self.i == n and self.last_end is None else "All lines tapped - press Done")
        self.nxt.setText(self.texts[self.i + 1] if self.i + 1 < n else "")

    def mark(self):
        t = self.player.position() / 1000.0
        n = len(self.texts)
        if self.i < n:
            self.starts.append(t)
            self.i += 1
        elif self.last_end is None:
            self.last_end = t
        self.show_line()

    def back(self):
        if self.last_end is not None:
            self.last_end = None
        elif self.i > 0:
            self.i -= 1
            self.starts.pop()
        self.show_line()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space:
            self.mark()
        elif e.key() == Qt.Key_Backspace:
            self.back()
        else:
            super().keyPressEvent(e)

    def done_data(self):
        self.player.stop()
        return self.starts, self.last_end


class PickerDialog(QDialog):
    """Pick one of the search results for a scene (thumbnails)."""

    def __init__(self, parent, cloud, query, kinds, orientation):
        super().__init__(parent)
        self.setWindowTitle("Choose a background")
        self.resize(760, 520)
        self.cloud, self.cands, self.chosen = cloud, [], None
        lay = QVBoxLayout(self)
        self.q = QLineEdit(query)
        go = btn("Search", self.go)
        lay.addWidget(hrow(self.q, go, stretch_first=True))
        self.lst = QListWidget()
        self.lst.setViewMode(QListWidget.IconMode)
        self.lst.setIconSize(QSize(200, 112))
        self.lst.setResizeMode(QListWidget.Adjust)
        self.lst.setSpacing(8)
        self.lst.itemDoubleClicked.connect(lambda _i: self.accept())
        lay.addWidget(self.lst, 1)
        self.msg = QLabel("Double-click a picture or clip to use it.")
        self.msg.setObjectName("muted")
        lay.addWidget(self.msg)
        lay.addWidget(hrow(btn("Use selected", self.accept, True), btn("Cancel", self.reject)))
        self.kinds, self.orient = kinds, orientation
        QTimer.singleShot(50, self.go)

    def go(self):
        self.lst.clear()
        self.cands = visuals.search(self.cloud, self.q.text().strip(), self.kinds, self.orient, 12)
        if not self.cands:
            self.msg.setText("Nothing found - try other words.")
        for c in self.cands:
            it = QListWidgetItem(("▶ " if c.kind == "video" else "") + (c.title or c.kind)[:24])
            pth = None
            if c.thumb:
                try:
                    pth = self.cloud.download(c.thumb, os.path.join(tempfile.gettempdir(), f"iwt_{abs(hash(c.thumb)) % 10**9}"))
                except CloudError:
                    pth = None
            if pth:
                it.setIcon(QIcon(QPixmap(pth)))
            self.lst.addItem(it)
        QApplication.processEvents()

    def selected(self):
        r = self.lst.currentRow()
        return self.cands[r] if 0 <= r < len(self.cands) else None


# --------------------------------------------------------------------------- main window
class Studio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  v{__version__}")
        self.resize(1480, 880)
        ic = asset_path("icon.png")
        if os.path.exists(ic):
            self.setWindowIcon(QIcon(ic))
        self.qs = QSettings("Ideawood", "IdeawoodArtists")
        self.p = Project()
        self.cloud = CloudClient(self.qs.value("api_key", "") if self.qs.value("remember", False, bool) else "")
        self.worker = None
        self._filling = False
        self._seq = 0
        self._fw = None
        self._frame_path = os.path.join(tempfile.gettempdir(), "iw_artists_preview.png")
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.refresh_preview)
        self._reg_fonts()
        self._build()
        self.load_preset("Karaoke Bold", quiet=True)

    # ---------------------------------------------------------------- fonts
    def _reg_fonts(self):
        for folder in (bundled_fonts_dir(), user_fonts_dir()):
            for f in fonts.font_files(folder):
                QFontDatabase.addApplicationFont(f)

    # ---------------------------------------------------------------- layout
    def _build(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(12, 12, 12, 12)
        h.setSpacing(12)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(190)
        for s in ("1  Song & lyrics", "2  Timing", "3  Look & fonts", "4  Visuals (AI)", "5  Export"):
            self.nav.addItem(s)
        h.addWidget(self.nav)
        self.stack = QStackedWidget()
        for page in (self.page_song(), self.page_timing(), self.page_look(), self.page_visuals(), self.page_export()):
            self.stack.addWidget(page)
        h.addWidget(self.stack, 3)
        self.nav.currentRowChanged.connect(self._nav)
        h.addWidget(self._preview_panel(), 2)
        self.nav.setCurrentRow(0)
        bar = self.statusBar()
        self.status = QLabel("Ready")
        bar.addWidget(self.status, 1)
        self.prog = QProgressBar()
        self.prog.setFixedWidth(260)
        self.prog.setVisible(False)
        bar.addPermanentWidget(self.prog)
        self.cancel_btn = btn("Cancel", self.cancel)
        self.cancel_btn.setVisible(False)
        bar.addPermanentWidget(self.cancel_btn)
        m = self.menuBar().addMenu("&Project")
        m.addAction("New", self.new_project)
        m.addAction("Open project...", self.open_project)
        m.addAction("Save project...", self.save_project)
        tm = self.menuBar().addMenu("&Theme")
        for name in THEMES:
            tm.addAction(name, lambda n=name: apply_theme(QApplication.instance(), n))

    def _nav(self, i):
        self.stack.setCurrentIndex(i)
        if i == 1:
            self.fill_table()
        if i == 3:
            self.fill_scene_table()
        self.schedule_preview()

    def _preview_panel(self):
        f, lay = card("Live preview", "Updates as you change the look. Drag the slider to check any moment.")
        self.pv = QLabel("Load a song and lyrics to see the preview")
        self.pv.setAlignment(Qt.AlignCenter)
        self.pv.setMinimumSize(380, 260)
        self.pv.setStyleSheet("background:#000; border-radius:8px; color:#888;")
        lay.addWidget(self.pv, 1)
        self.pv_slider = QSlider(Qt.Horizontal)
        self.pv_slider.setRange(0, 1000)
        self.pv_slider.valueChanged.connect(lambda _v: self.schedule_preview())
        self.pv_time = QLabel("0:00.00")
        lay.addWidget(hrow(self.pv_slider, self.pv_time, stretch_first=True))
        lay.addWidget(btn("Play a 22 s preview clip", lambda: self.start_render(preview=True)))
        return f

    # ---------------------------------------------------------------- page 1: song & lyrics
    def page_song(self):
        f1, l1 = card("1. Your song", "Any MP3 / WAV / M4A / FLAC (or a video file). Audio never leaves your PC.")
        self.audio_edit = QLineEdit()
        self.audio_edit.setPlaceholderText("Choose the song")
        self.audio_edit.editingFinished.connect(lambda: self.set_audio(self.audio_edit.text().strip(), quiet=True))
        l1.addWidget(hrow(self.audio_edit, btn("Browse...", self.browse_audio), stretch_first=True))
        self.title_edit, self.artist_edit = QLineEdit(), QLineEdit()
        self.title_edit.setPlaceholderText("Song title")
        self.artist_edit.setPlaceholderText("Artist name")
        self.genre = QComboBox()
        self.genre.setEditable(True)
        self.genre.addItems(GENRES)
        self.mood = QLineEdit()
        self.mood.setPlaceholderText("Mood for the AI visuals, e.g. warm sunset, romantic, village at dusk (optional)")
        for w in (self.title_edit, self.artist_edit, self.mood):
            w.textChanged.connect(self._meta_changed)
        self.genre.currentTextChanged.connect(self._meta_changed)
        l1.addWidget(hrow(self.title_edit, self.artist_edit))
        l1.addWidget(hrow("Genre", self.genre))
        l1.addWidget(self.mood)

        f2, l2 = card("2. Lyrics", "Paste them (blank line = new verse). [Chorus] / [Verse 1] headers are fine and are not shown. "
                      "Your spelling is always what appears on screen, in any language.")
        self.lyr_edit = QTextEdit()
        self.lyr_edit.setAcceptRichText(False)
        self.lyr_edit.setMinimumHeight(220)
        self.lyr_edit.textChanged.connect(self._lyrics_changed)
        l2.addWidget(self.lyr_edit)
        l2.addWidget(hrow(btn("Import .txt / .lrc...", self.import_lyrics), btn("Clear", lambda: self.lyr_edit.clear())))

        f3, l3 = card("3. Give the lyrics their timing",
                      "Auto-sync listens to the song on this PC and places every word. For languages speech recognition "
                      "doesn't know (e.g. Luganda, Runyankole), use Tap to sync - it takes about one listen.")
        self.model = QComboBox()
        self.lang = combo(list(asr.LANGUAGES), "Auto-detect")
        self.model_note = QLabel("")
        self.model_note.setObjectName("muted")
        self.model_note.setWordWrap(True)
        self.refresh_models()
        l3.addWidget(hrow("Speech model", self.model, "Language", self.lang, stretch_first=False))
        l3.addWidget(self.model_note)
        self.dl_btn = btn("Download model", self.download_model)
        l3.addWidget(hrow(btn("Auto-sync with AI", self.do_sync, True), btn("Tap to sync...", self.do_tap),
                          btn("Spread evenly (fix by hand)", self.do_spread), self.dl_btn))
        self.sync_msg = QLabel("")
        self.sync_msg.setObjectName("muted")
        self.sync_msg.setWordWrap(True)
        l3.addWidget(self.sync_msg)
        return scroll(f1, f2, f3)

    def refresh_models(self):
        self.model.clear()
        inst = asr.installed_models()
        for k in asr.MODELS:
            self.model.addItem(("✓ " if k in inst else "") + asr.MODELS[k][0], k)
        if inst:
            self.model.setCurrentIndex(list(asr.MODELS).index(inst[0]))
            self.model_note.setText("A speech model is ready. Music with loud instruments recognises best with Small.")
        else:
            self.model_note.setText("No speech model installed yet - download one (once) or use Tap to sync.")
        if hasattr(self, "dl_btn"):
            self.dl_btn.setVisible(not inst)

    def _meta_changed(self, *_):
        self.p.title, self.p.artist = self.title_edit.text(), self.artist_edit.text()
        self.p.genre, self.p.mood = self.genre.currentText(), self.mood.text()
        self.schedule_preview()

    def _lyrics_changed(self):
        self.p.lyrics_text = self.lyr_edit.toPlainText()

    def browse_audio(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose the song", "", AUDIO_FILTER)
        if path:
            self.set_audio(path)

    def set_audio(self, path: str, quiet=False):
        if not path or not os.path.isfile(path):
            if not quiet and path:
                QMessageBox.warning(self, APP_NAME, "That file was not found.")
            return False
        try:
            syncer.load_audio(self.p, path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, str(e))
            return False
        self.audio_edit.setText(path)
        if not self.title_edit.text():
            self.title_edit.setText(self.p.title)
        self.say(f"Loaded {os.path.basename(path)} ({fmt_t(self.p.duration)})")
        if self.p.lines:
            self.p.scenes = scn.replan_keep_media(self.p.scenes, scn.plan_scenes(self.p.lines, self.p.duration))
        self.schedule_preview()
        return True

    def import_lyrics(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import lyrics", "", "Lyrics (*.txt *.lrc *.srt);;All files (*)")
        if not path:
            return
        text = open(path, "r", encoding="utf-8", errors="replace").read()
        if path.lower().endswith(".lrc") and lyrics.parse_lrc(text, self.p.duration):
            self.p.lines = lyrics.parse_lrc(text, self.p.duration)
            self.lyr_edit.setPlainText(lyrics.lines_to_text(self.p.lines))
            self._after_timing("Imported timed lyrics from the LRC file.")
        else:
            self.lyr_edit.setPlainText(text)

    # ---------------------------------------------------------------- sync actions
    def _need_ready(self, need_lyrics=True):
        if not self.p.audio:
            QMessageBox.information(self, APP_NAME, "Choose the song first.")
            return False
        if need_lyrics and not self.p.lyrics_text.strip():
            QMessageBox.information(self, APP_NAME, "Paste the lyrics first.")
            return False
        return True

    def download_model(self):
        key = self.model.currentData()

        def fn(w):
            return asr.download_model(key, w.progress.emit, lambda: w.stop)
        self.run_worker(fn, f"Downloading the speech model ({asr.MODELS[key][2]} MB)...",
                        lambda _r: (self.refresh_models(), self.say("Model ready.")))

    def do_sync(self):
        if not self._need_ready(need_lyrics=False):
            return
        key = self.model.currentData()
        mp = asr.find_model(key)
        if not mp:
            QMessageBox.information(self, APP_NAME, "Download a speech model first (button on the right), or use Tap to sync.")
            return
        lang = asr.LANGUAGES[self.lang.currentText()]
        if lang != "auto" and not asr.MODELS[key][3]:
            lang = "en"
        eng = asr.WhisperEngine(mp)

        def fn(w):
            return syncer.auto_sync(self.p, eng, lang, w.status.emit, w.progress.emit, lambda: w.stop)

        def ok(rep):
            msg = f"Timed {rep['lines']} lines."
            if rep["mode"] == "aligned" and rep["match"] < 0.45:
                msg += (" Only part of your lyrics matched what the AI heard (accents, other languages or loud music) - "
                        "check the Timing step, or use Tap to sync for exact timing.")
            self.lyr_edit.setPlainText(lyrics.lines_to_text(self.p.lines)) if rep["mode"] == "transcribed" else None
            self._after_timing(msg)
        self.run_worker(fn, "Listening to the song on this PC...", ok)

    def do_spread(self):
        if not self._need_ready():
            return
        try:
            syncer.spread_evenly(self.p)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        self._after_timing("Lines spread evenly over the song. Fix the times in step 2.")

    def do_tap(self):
        if not self._need_ready():
            return
        lines = lyrics.parse_lyrics(self.p.lyrics_text)
        try:
            dlg = TapSync(self, self.p.audio, [l.text for l in lines])
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, f"Audio playback is not available here: {e}")
            return
        dlg.exec()
        starts, last_end = dlg.done_data()
        if not starts:
            return
        self.p.lines = lines
        syncer.apply_tap_times(self.p, starts, last_end)
        self._after_timing(f"Timed {len(starts)} of {len(lines)} lines from your taps.")

    def _after_timing(self, msg: str):
        self.sync_msg.setText(msg)
        self.say(msg)
        self.fill_table()
        self.pv_slider.setValue(self._default_preview_pos())
        self.schedule_preview()

    # ---------------------------------------------------------------- page 2: timing table
    def page_timing(self):
        f, l = card("Timing", "Edit any text or time (m:ss.xx). Words inside a line are spread over its time. "
                    "Lines in the same verse share a background, so keep blank-line breaks meaningful.")
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "Start", "End", "Lyric"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 90)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._cell_changed)
        self.table.itemSelectionChanged.connect(self._row_selected)
        l.addWidget(self.table, 1)
        shift = QDoubleSpinBox()
        shift.setRange(-30, 30)
        shift.setSingleStep(0.1)
        shift.setDecimals(2)
        shift.setSuffix(" s")
        self.shift_box = shift
        l.addWidget(hrow("Move all lines by", shift, btn("Apply", self.shift_all), btn("Merge with next", self.merge_row),
                         btn("Split line...", self.split_row), btn("Delete", self.delete_row), btn("Add line", self.add_row)))
        l.addWidget(hrow(btn("Export .lrc", lambda: self.export_text("lrc")), btn("Export .srt", lambda: self.export_text("srt")),
                         btn("Play from selected line", self.play_from_row)))
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(f, 1)
        return w

    def fill_table(self):
        self._filling = True
        self.table.setRowCount(len(self.p.lines))
        for i, ln in enumerate(self.p.lines):
            vals = [str(i + 1), fmt_t(ln.start) if ln.timed else "", fmt_t(ln.end) if ln.timed else "", ln.text]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(i, c, it)
        self._filling = False

    def _cell_changed(self, it):
        if self._filling:
            return
        r, c = it.row(), it.column()
        if r >= len(self.p.lines):
            return
        ln = self.p.lines[r]
        if c == 3:
            lyrics.retext_line(ln, it.text())
        elif c in (1, 2):
            t = parse_t(it.text())
            if t is None:
                self.fill_table()
                return
            s, e = (t, ln.end if ln.end > t else t + 2.0) if c == 1 else (ln.start if ln.start >= 0 else max(t - 2, 0), t)
            if e > s:
                lyrics.set_times(ln, s, e)
        self._replan()
        self.schedule_preview()

    def _replan(self):
        if self.p.lines:
            self.p.scenes = scn.replan_keep_media(self.p.scenes, scn.plan_scenes(self.p.lines, self.p.duration))

    def _sel(self):
        r = self.table.currentRow()
        return r if 0 <= r < len(self.p.lines) else -1

    def _row_selected(self):
        r = self._sel()
        if r >= 0 and self.p.lines[r].timed and self.p.duration:
            self.pv_slider.setValue(int(1000 * min(self.p.lines[r].start + 0.6, self.p.duration) / self.p.duration))

    def shift_all(self):
        lyrics.shift_all(self.p.lines, self.shift_box.value())
        self.fill_table()
        self._replan()
        self.schedule_preview()

    def merge_row(self):
        r = self._sel()
        if r >= 0:
            lyrics.merge_with_next(self.p.lines, r)
            self.fill_table()
            self._replan()

    def split_row(self):
        r = self._sel()
        if r < 0:
            return
        n = len(self.p.lines[r].text.split())
        k, ok = QInputDialog.getInt(self, "Split line", f"Split after word number (1 - {n - 1}):", max(1, n // 2), 1, max(1, n - 1))
        if ok:
            lyrics.split_line(self.p.lines, r, k)
            self.fill_table()
            self._replan()

    def delete_row(self):
        r = self._sel()
        if r >= 0:
            del self.p.lines[r]
            self.fill_table()
            self._replan()
            self.schedule_preview()

    def add_row(self):
        r = self._sel()
        t = self.p.lines[r].end + 0.1 if r >= 0 and self.p.lines[r].timed else 0.0
        ln = lyrics.LyricLine("New line", t, t + 2.0)
        ln.words = lyrics.even_words(ln.text, ln.start, ln.end)
        self.p.lines.insert(r + 1 if r >= 0 else len(self.p.lines), ln)
        self.fill_table()
        self._replan()

    def play_from_row(self):
        r = self._sel()
        if r < 0 or not self.p.audio:
            return
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            if not hasattr(self, "_pl"):
                self._pl, self._po = QMediaPlayer(self), QAudioOutput(self)
                self._pl.setAudioOutput(self._po)
            self._pl.setSource(QUrl.fromLocalFile(self.p.audio))
            self._pl.setPosition(int(max(self.p.lines[r].start - 0.5, 0) * 1000))
            self._pl.play()
            QTimer.singleShot(int((self.p.lines[r].end - self.p.lines[r].start + 3) * 1000), self._pl.pause)
        except Exception as e:  # noqa: BLE001
            self.say(f"Playback not available: {e}")

    def export_text(self, kind: str):
        if not [l for l in self.p.lines if l.timed]:
            QMessageBox.information(self, APP_NAME, "There are no timed lines yet.")
            return
        base = (self.p.title or "lyrics").replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(self, f"Save .{kind}", base + "." + kind, f"*.{kind}")
        if not path:
            return
        if kind == "lrc":
            text = lyrics.to_lrc(self.p.lines, self.p.title, self.p.artist, enhanced=True)
        else:
            text = asr.to_srt(lyrics.to_cues(self.p.lines))
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.say(f"Saved {path}")

    # ---------------------------------------------------------------- page 3: look
    def page_look(self):
        f0, l0 = card("Style", "Start from a preset, then fine-tune. Everything shows in the live preview.")
        self.preset = combo(list(PRESETS), "Karaoke Bold")
        self.preset.activated.connect(lambda _i: self.load_preset(self.preset.currentText()))
        l0.addWidget(hrow("Preset", self.preset))

        f1, l1 = card("Font", "15 professional fonts are built in. Add your own .ttf / .otf and it is used in the video too.")
        self.font_box = QComboBox()
        self.font_box.setEditable(True)
        self.font_note = QLabel("")
        self.font_note.setObjectName("muted")
        self.font_box.currentTextChanged.connect(self._font_changed)
        l1.addWidget(hrow("Font", self.font_box, btn("Add font file...", self.add_font), stretch_first=False))
        l1.addWidget(self.font_note)
        self.bold, self.italic, self.upper = QCheckBox("Bold"), QCheckBox("Italic"), QCheckBox("UPPERCASE")
        for c, a in ((self.bold, "bold"), (self.italic, "italic"), (self.upper, "uppercase")):
            c.toggled.connect(lambda v, a=a: self._set(a, v))
        l1.addWidget(hrow(self.bold, self.italic, self.upper))
        self.sliders = {}
        self._slider(l1, "Text size", "size", 3, 18, 100.0)
        self._slider(l1, "Vertical position", "pos_y", 10, 95, 100.0)
        self._slider(l1, "Letter spacing", "spacing", -2, 12, 1.0)

        f2, l2 = card("Colours & text effects")
        self.col_btns = {}
        row = []
        for label, attr in (("Unsung", "color_unsung"), ("Sung", "color_sung"), ("Outline", "outline_color"),
                            ("Glow", "glow_color"), ("Box", "box_color"), ("Visualiser", "viz_color")):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, a=attr: self.pick_color(a))
            self.col_btns[attr] = b
            row.append(b)
        l2.addWidget(hrow(*row))
        self._slider(l2, "Outline thickness", "outline", 0, 15, 100.0)
        self._slider(l2, "Shadow", "shadow", 0, 10, 100.0)
        self.glow, self.box = QCheckBox("Glow"), QCheckBox("Dark box behind text")
        self.glow.toggled.connect(lambda v: self._set("glow", v))
        self.box.toggled.connect(lambda v: self._set("box", v))
        l2.addWidget(hrow(self.glow, self.box))
        self._slider(l2, "Box opacity", "box_alpha", 10, 100, 100.0)

        f3, l3 = card("Motion")
        self.anim = combo(ANIMATIONS)
        self.hl = combo(HIGHLIGHTS)
        self.anim.currentTextChanged.connect(lambda v: self._set("anim_in", v))
        self.hl.currentTextChanged.connect(lambda v: self._set("highlight", v))
        l3.addWidget(hrow("Line entrance", self.anim, "Word highlight", self.hl))
        self.nextc, self.dots, self.titlec = (QCheckBox("Show next line (dimmed)"), QCheckBox("Countdown dots in long gaps"),
                                              QCheckBox("Title card at the start"))
        self.nextc.toggled.connect(lambda v: self._set("show_next", v))
        self.dots.toggled.connect(lambda v: self._set("instrumental_dots", v))
        self.titlec.toggled.connect(lambda v: self._set("title_card", v))
        l3.addWidget(hrow(self.nextc, self.dots, self.titlec))

        f4, l4 = card("Background treatment")
        self._slider(l4, "Darken background", "bg_dim", 0, 80, 100.0)
        self._slider(l4, "Blur background", "bg_blur", 0, 30, 1.0)
        self._slider(l4, "Film grain", "grain", 0, 15, 100.0)
        self.grade = combo(list(GRADES))
        self.trans = combo(TRANSITIONS)
        self.viz = combo(VIZ_MODES)
        self.grade.currentTextChanged.connect(lambda v: self._set("grade", v))
        self.trans.currentTextChanged.connect(lambda v: self._set("transition", v))
        self.viz.currentTextChanged.connect(lambda v: self._set("viz", v))
        l4.addWidget(hrow("Colour grade", self.grade, "Transition", self.trans, "Audio visualiser", self.viz))
        self.kb, self.vig = QCheckBox("Slow zoom / pan on pictures (Ken Burns)"), QCheckBox("Vignette")
        self.kb.toggled.connect(lambda v: self._set("ken_burns", v))
        self.vig.toggled.connect(lambda v: self._set("vignette", v))
        l4.addWidget(hrow(self.kb, self.vig))
        return scroll(f0, f1, f2, f3, f4)

    def _slider(self, lay, label, attr, lo, hi, scale):
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        val = QLabel("")
        val.setMinimumWidth(48)
        self.sliders[attr] = (s, scale, val)

        def changed(v):
            val.setText(f"{v / scale:.2f}" if scale != 1.0 else str(v))
            if not self._filling:
                self._set(attr, v / scale if scale != 1.0 else float(v))
        s.valueChanged.connect(changed)
        lay.addWidget(hrow(label, s, val, stretch_first=False))
        lay.itemAt(lay.count() - 1).widget().layout().setStretch(1, 1)

    def _set(self, attr, value):
        if self._filling:
            return
        setattr(self.p.style, attr, value)
        self.schedule_preview()

    def _font_changed(self, text):
        if self._filling:
            return
        ch = next((c for c in fonts.catalog() if c.label == text), None)
        if ch:
            self.p.style.font, self.p.style.bold = ch.family, ch.bold
            self.font_note.setText(ch.mood)
            self._filling = True
            self.bold.setChecked(ch.bold)
            self._filling = False
        else:
            self.p.style.font = text
            self.font_note.setText("Using an installed font by name.")
        self.schedule_preview()

    def add_font(self):
        path, _ = QFileDialog.getOpenFileName(self, "Add a font", "", "Fonts (*.ttf *.otf)")
        if not path:
            return
        try:
            fam = fonts.add_user_font(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        QFontDatabase.addApplicationFont(path)
        self.fill_fonts(select=f"{fam} (yours)")

    def fill_fonts(self, select=""):
        self._filling = True
        self.font_box.clear()
        for c in fonts.catalog():
            self.font_box.addItem(c.label)
        cur = select or next((c.label for c in fonts.catalog() if c.family == self.p.style.font), self.p.style.font)
        self.font_box.setCurrentText(cur)
        self._filling = False
        if select:
            self._font_changed(select)

    def pick_color(self, attr):
        c = QColorDialog.getColor(QColor(getattr(self.p.style, attr)), self, "Choose a colour")
        if c.isValid():
            setattr(self.p.style, attr, c.name().upper())
            self._paint_color_buttons()
            self.schedule_preview()

    def _paint_color_buttons(self):
        for attr, b in self.col_btns.items():
            col = getattr(self.p.style, attr)
            lum = QColor(col).lightness()
            b.setStyleSheet(f"background:{col}; color:{'#000' if lum > 140 else '#fff'}; border:1px solid #666;")

    def load_preset(self, name, quiet=False):
        self.p.style = PRESETS[name].copy()
        self.sync_look_widgets()
        if not quiet:
            self.schedule_preview()

    def sync_look_widgets(self):
        st = self.p.style
        self._filling = True
        self.fill_fonts()
        for attr, (s, scale, val) in self.sliders.items():
            s.setValue(int(round(getattr(st, attr) * scale)))
            val.setText(f"{getattr(st, attr):.2f}" if scale != 1.0 else str(int(getattr(st, attr))))
        for w, v in ((self.bold, st.bold), (self.italic, st.italic), (self.upper, st.uppercase), (self.glow, st.glow),
                     (self.box, st.box), (self.nextc, st.show_next), (self.dots, st.instrumental_dots),
                     (self.titlec, st.title_card), (self.kb, st.ken_burns), (self.vig, st.vignette)):
            w.setChecked(bool(v))
        for w, v in ((self.anim, st.anim_in), (self.hl, st.highlight), (self.grade, st.grade),
                     (self.trans, st.transition), (self.viz, st.viz)):
            w.setCurrentText(v)
        self.preset.setCurrentText(st.name) if st.name in PRESETS else None
        self._paint_color_buttons()
        self._filling = False

    # ---------------------------------------------------------------- page 4: visuals
    def page_visuals(self):
        f1, l1 = card("AI visuals", "AI reads your lyrics, plans a search phrase for every part of the song and fetches background "
                      "pictures or video clips (needs your API key; rendering stays on this PC). Without a key you get designed "
                      "animated gradients, and you can always use your own pictures and clips.")
        self.key_edit = QLineEdit(self.cloud.api_key)
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("Paste your API key")
        self.remember = QCheckBox("Remember on this PC")
        self.remember.setChecked(self.qs.value("remember", False, bool))
        self.key_edit.editingFinished.connect(self._key_changed)
        self.remember.toggled.connect(lambda _v: self._key_changed())
        l1.addWidget(hrow(self.key_edit, self.remember, stretch_first=True))
        self.prefer = combo(["Video clips", "Pictures", "Mix of both"], "Video clips")
        l1.addWidget(hrow("Backgrounds", self.prefer, btn("Find visuals with AI", self.ai_fill, True),
                          btn("Re-plan scenes", self.replan_scenes)))
        f2, l2 = card("Scenes", "One scene per verse / chorus; repeated choruses share a background. Double-click the search "
                      "phrase to change it, then use the buttons for the selected scene.")
        self.sc_table = QTableWidget(0, 5)
        self.sc_table.setHorizontalHeaderLabels(["", "Time", "Lyrics", "Source", "Search phrase"])
        self.sc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.sc_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.sc_table.setColumnWidth(0, 96)
        self.sc_table.setColumnWidth(1, 100)
        self.sc_table.setColumnWidth(3, 90)
        self.sc_table.verticalHeader().setVisible(False)
        self.sc_table.verticalHeader().setDefaultSectionSize(54)
        self.sc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sc_table.itemChanged.connect(self._scene_cell)
        self.sc_table.itemSelectionChanged.connect(self._scene_selected)
        l2.addWidget(self.sc_table, 1)
        l2.addWidget(hrow(btn("Pick another (AI search)...", self.pick_for_scene), btn("Use my picture / clip...", self.mine_for_scene),
                          btn("Use my files for ALL scenes...", self.mine_for_all), btn("Back to gradient", self.gradient_scene)))
        l2.addWidget(hrow(btn("Draw a cartoon for this scene...", self.toon_for_scene, True),
                          btn("AI storyboard ideas for all scenes...", self.storyboard_ai)))
        f3, l3 = card("Artist logo & credit")
        self.logo_edit = QLineEdit()
        self.logo_edit.setPlaceholderText("Optional logo (PNG with transparency works best)")
        self.logo_edit.editingFinished.connect(lambda: self._logo(self.logo_edit.text().strip()))
        self.logo_pos = combo(LOGO_POSITIONS, "Top right")
        self.logo_pos.currentTextChanged.connect(lambda v: (setattr(self.p, "logo_pos", v), self.schedule_preview()))
        self.credit = QCheckBox("Add a small 'made with Ideawood Studio for Artists' line at the end")
        self.credit.toggled.connect(lambda v: setattr(self.p, "credit", v))
        l3.addWidget(hrow(self.logo_edit, btn("Browse...", self.browse_logo), self.logo_pos, stretch_first=True))
        l3.addWidget(self.credit)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        v.addWidget(f1)
        v.addWidget(f2, 1)
        v.addWidget(f3)
        return w

    def _key_changed(self):
        self.cloud.set_key(self.key_edit.text())
        self.qs.setValue("remember", self.remember.isChecked())
        self.qs.setValue("api_key", self.cloud.api_key if self.remember.isChecked() else "")

    def _prefer(self):
        return {"Video clips": "video", "Pictures": "image", "Mix of both": "both"}[self.prefer.currentText()]

    def replan_scenes(self):
        self.p.scenes = scn.plan_scenes(self.p.lines, self.p.duration)
        self.fill_scene_table()
        self.schedule_preview()

    def fill_scene_table(self):
        if not self.p.scenes and self.p.lines:
            self.p.scenes = scn.plan_scenes(self.p.lines, self.p.duration)
        self._filling = True
        self.sc_table.setRowCount(len(self.p.scenes))
        for i, sc in enumerate(self.p.scenes):
            th = QTableWidgetItem("")
            th.setFlags(th.flags() & ~Qt.ItemIsEditable)
            if sc.kind != "gradient":
                tp = visuals.thumbnail(sc.path, sc.kind)
                if tp:
                    th.setIcon(QIcon(QPixmap(tp).scaledToWidth(90)))
            else:
                pm = QPixmap(90, 50)
                pm.fill(QColor(sc.colors[0]))
                th.setIcon(QIcon(pm))
            self.sc_table.setItem(i, 0, th)
            for c, v in ((1, f"{fmt_t(sc.start)}"), (2, sc.label), (3, {"ai": "AI", "mine": "Mine", "toon": "Cartoon"}.get(sc.source, "Gradient"
                                                                                                    if sc.kind == "gradient" else "—")),
                         (4, sc.query)):
                it = QTableWidgetItem(v)
                if c == 2 and sc.idea:
                    it.setToolTip("Storyboard idea: " + sc.idea)
                if c != 4:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.sc_table.setItem(i, c, it)
        self._filling = False

    def _scene_cell(self, it):
        if not self._filling and it.column() == 4 and it.row() < len(self.p.scenes):
            self.p.scenes[it.row()].query = it.text()

    def _scene_selected(self):
        r = self.sc_table.currentRow()
        if 0 <= r < len(self.p.scenes) and self.p.duration:
            sc = self.p.scenes[r]
            self.pv_slider.setValue(int(1000 * min(sc.start + min(3.0, sc.duration / 2), self.p.duration) / self.p.duration))

    def _srow(self):
        r = self.sc_table.currentRow()
        return r if 0 <= r < len(self.p.scenes) else -1

    def ai_fill(self):
        if not self.p.lines:
            QMessageBox.information(self, APP_NAME, "Time the lyrics first (steps 1-2).")
            return
        self._key_changed()
        if not self.p.scenes:
            self.p.scenes = scn.plan_scenes(self.p.lines, self.p.duration)

        def fn(w):
            return visuals.fill_scenes(self.cloud, self.p, self._prefer(), None, w.status.emit, w.progress.emit, lambda: w.stop)

        def ok(rep):
            self.fill_scene_table()
            self.schedule_preview()
            note = f"Filled {rep['filled']} scene(s). " + " ".join(rep["notes"][:2])
            self.say(note.strip())
        self.run_worker(fn, "Finding visuals...", ok)

    def pick_for_scene(self):
        r = self._srow()
        if r < 0:
            QMessageBox.information(self, APP_NAME, "Select a scene first.")
            return
        if not self.cloud.signed_in:
            QMessageBox.information(self, APP_NAME, "Paste your API key to search stock pictures and clips.")
            return
        sc = self.p.scenes[r]
        q = sc.query or visuals.fallback_query(visuals.scene_text(self.p, sc), self.p.mood, self.p.genre, r)
        dlg = PickerDialog(self, self.cloud, q, visuals._kinds_for(self._prefer(), r), self.p.orientation)
        if dlg.exec() != QDialog.Accepted or not dlg.selected():
            return
        cand = dlg.selected()
        sc.query = dlg.q.text().strip()

        def fn(w):
            return visuals.download(self.cloud, cand, os.path.join(visuals.media_dir(), f"pick_{abs(hash(cand.url)) % 10**8}"))

        def ok(path):
            sc.kind, sc.path, sc.credit, sc.source, sc.toon = cand.kind, path, cand.credit, "ai", ""
            scn.share_by_key(self.p.scenes)
            self.fill_scene_table()
            self.schedule_preview()
        self.run_worker(fn, "Downloading...", ok)

    def storyboard_ai(self):
        """One text-only AI call: a storyboard idea for every scene, shown in the cartoon editor. Uses a small
        amount of the board service's monthly credit, so it asks first."""
        if not self.p.lines or not self.p.scenes:
            QMessageBox.information(self, APP_NAME, "Time the lyrics first (steps 1-2), then plan scenes.")
            return
        key = (self.qs.value("toon_api_key", "") or "").strip()
        if not key:
            key, ok = QInputDialog.getText(self, APP_NAME, "Paste your board API key (for the cartoon / board service):",
                                           QLineEdit.Password)
            key = key.strip()
            if not ok or not key:
                return
            if self.remember.isChecked():
                self.qs.setValue("toon_api_key", key)
        if QMessageBox.question(self, APP_NAME, "This sends your lyrics to the AI once and uses a small amount of your "
                                "monthly credit. Continue?") != QMessageBox.Yes:
            return
        text = "\n".join(ln.text for ln in self.p.lines)
        n, dur, mood = len(self.p.scenes), round(self.p.duration), self.p.mood or ""

        def fn(w):
            return self.cloud.toon_storyboard(text, dur, n, context=mood, api_key=key)

        def ok(resp):
            items = parse_storyboard(resp)
            got = scn.apply_storyboard(self.p.scenes, items)
            self.fill_scene_table()
            if got:
                self.say(f"Storyboard ideas added to {got} scene(s) - hover a scene's lyrics, or open its cartoon editor.")
            else:
                QMessageBox.information(self, APP_NAME, "The service answered, but there were no scene ideas in the reply.")
        self.run_worker(fn, "Writing the storyboard...", ok)

    def toon_for_scene(self):
        r = self._srow()
        if r < 0:
            QMessageBox.information(self, APP_NAME, "Select a scene first.")
            return
        dlg = ToonEditor(self, self.p, r)
        if dlg.exec() != QDialog.Accepted or not dlg.result_clip:
            return
        sc, clip = self.p.scenes[r], dlg.result_clip
        sc.kind, sc.path, sc.source, sc.credit, sc.toon = "video", clip.video, "toon", "", clip.folder
        scn.share_by_key(self.p.scenes)
        self.fill_scene_table()
        self.schedule_preview()
        self.say("Cartoon saved as this scene's background.")

    def mine_for_scene(self):
        r = self._srow()
        if r < 0:
            QMessageBox.information(self, APP_NAME, "Select a scene first.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choose a picture or video", "",
                                              "Pictures and videos (*.jpg *.jpeg *.png *.webp *.mp4 *.mov *.mkv *.webm)")
        if path:
            visuals.assign_local(self.p.scenes, [path], only=[r])
            self.fill_scene_table()
            self.schedule_preview()

    def mine_for_all(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose your pictures and clips", "",
                                                "Pictures and videos (*.jpg *.jpeg *.png *.webp *.mp4 *.mov *.mkv *.webm)")
        if paths:
            visuals.assign_local(self.p.scenes, paths)
            self.fill_scene_table()
            self.schedule_preview()

    def gradient_scene(self):
        r = self._srow()
        if r >= 0:
            sc = self.p.scenes[r]
            sc.kind, sc.path, sc.source, sc.credit, sc.toon = "gradient", "", "auto", "", ""
            self.fill_scene_table()
            self.schedule_preview()

    def browse_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a logo", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            self._logo(path)

    def _logo(self, path):
        self.p.logo = path if path and os.path.isfile(path) else ""
        self.logo_edit.setText(self.p.logo)
        self.schedule_preview()

    # ---------------------------------------------------------------- page 5: export
    def page_export(self):
        f1, l1 = card("Output")
        self.fmt = combo(list(FORMATS), self.p.fmt)
        self.qual = combo(list(QUALITIES), self.p.quality)
        self.fmt.currentTextChanged.connect(lambda v: (setattr(self.p, "fmt", v), self.schedule_preview()))
        self.qual.currentTextChanged.connect(lambda v: setattr(self.p, "quality", v))
        self.norm = QCheckBox("Normalise loudness for YouTube / Spotify (-14 LUFS). Leave off for already-mastered songs.")
        self.norm.toggled.connect(lambda v: setattr(self.p, "normalize_audio", v))
        l1.addWidget(hrow("Shape", self.fmt, "Quality", self.qual))
        l1.addWidget(self.norm)
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Where to save the MP4")
        l1.addWidget(hrow(self.out_edit, btn("Browse...", self.browse_out), stretch_first=True))
        f2, l2 = card("Make it", "Tip: render a 22 s preview clip first. A full 1080p video takes roughly 0.5-2x the song length "
                      "on a normal laptop.")
        self.render_btn = btn("Render lyric video", lambda: self.start_render(False), True)
        l2.addWidget(hrow(self.render_btn, btn("Open output folder", self.open_folder), btn("Save project...", self.save_project)))
        self.result = QLabel("")
        self.result.setObjectName("muted")
        self.result.setWordWrap(True)
        l2.addWidget(self.result)
        return scroll(f1, f2)

    def browse_out(self):
        base = (self.p.title or "lyric_video").replace(" ", "_") + ".mp4"
        path, _ = QFileDialog.getSaveFileName(self, "Save video as", base, "MP4 video (*.mp4)")
        if path:
            self.out_edit.setText(path if path.lower().endswith(".mp4") else path + ".mp4")

    def open_folder(self):
        p = self.out_edit.text().strip()
        if p:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(os.path.abspath(p))))

    def start_render(self, preview=False):
        if not self._need_ready(need_lyrics=False):
            return
        if not [l for l in self.p.lines if l.timed]:
            QMessageBox.information(self, APP_NAME, "Time the lyrics first (steps 1-2).")
            return
        if not self.p.scenes:
            self.p.scenes = scn.plan_scenes(self.p.lines, self.p.duration)
        out = self.out_edit.text().strip()
        if preview:
            out = os.path.join(tempfile.gettempdir(), "iw_artists_clip.mp4")
        elif not out:
            self.browse_out()
            out = self.out_edit.text().strip()
            if not out:
                return

        def fn(w):
            return render.render(self.p, out, w.progress.emit, w.status.emit, lambda: w.stop, preview=preview)

        def ok(r):
            if preview:
                QDesktopServices.openUrl(QUrl.fromLocalFile(r["path"]))
                self.say("Preview clip opened in your video player.")
            else:
                credits = visuals.credits_text(self.p)
                if credits:
                    with open(os.path.splitext(out)[0] + ".credits.txt", "w", encoding="utf-8") as f:
                        f.write(credits)
                self.result.setText(f"Saved: {out}" + ("  (media credits saved next to it)" if credits else ""))
                self.say("Your lyric video is ready.")
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(os.path.abspath(out))))
        self.run_worker(fn, "Rendering...", ok)

    # ---------------------------------------------------------------- projects
    def new_project(self):
        self.p = Project()
        for w in (self.audio_edit, self.title_edit, self.artist_edit, self.mood):
            w.clear()
        self.lyr_edit.clear()
        self.load_preset("Karaoke Bold", quiet=True)
        self.fill_table()
        self.fill_scene_table()

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save project", (self.p.title or "project") + ".iwlyric", "Ideawood lyric project (*.iwlyric)")
        if path:
            self.p.save(path)
            self.say(f"Saved {path}")

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", "Ideawood lyric project (*.iwlyric)")
        if path:
            self.load_project(path)

    def load_project(self, path):
        self.p = Project.load(path)
        self.audio_edit.setText(self.p.audio)
        self.title_edit.setText(self.p.title)
        self.artist_edit.setText(self.p.artist)
        self.genre.setCurrentText(self.p.genre)
        self.mood.setText(self.p.mood)
        self.lyr_edit.setPlainText(self.p.lyrics_text)
        self.fmt.setCurrentText(self.p.fmt)
        self.qual.setCurrentText(self.p.quality)
        self.logo_edit.setText(self.p.logo)
        self.sync_look_widgets()
        self.fill_table()
        self.fill_scene_table()
        self.schedule_preview()

    # ---------------------------------------------------------------- preview
    def _default_preview_pos(self):
        timed = [l for l in self.p.lines if l.timed]
        if not timed or not self.p.duration:
            return 0
        ln = timed[min(1, len(timed) - 1)]
        return int(1000 * (ln.start + (ln.end - ln.start) * 0.6) / self.p.duration)

    def schedule_preview(self):
        self.debounce.start(350)

    def refresh_preview(self):
        timed = [l for l in self.p.lines if l.timed]
        if not timed or not self.p.duration:
            return
        if not self.p.scenes:
            self.p.scenes = scn.plan_scenes(self.p.lines, self.p.duration)
        t = self.pv_slider.value() / 1000.0 * self.p.duration
        self.pv_time.setText(fmt_t(t))
        if self._fw is not None and self._fw.isRunning():
            self.debounce.start(300)
            return
        self._seq += 1
        import copy
        self._fw = FrameWorker(self._seq, copy.deepcopy(self.p), t, self._frame_path)
        self._fw.ready.connect(self._frame_ready)
        self._fw.start()

    def _frame_ready(self, seq, path):
        if path.startswith("ERR:"):
            self.pv.setText("Preview unavailable: " + path[4:][:160])
            return
        pm = QPixmap(path)
        self.pv.setPixmap(pm.scaled(self.pv.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if seq != self._seq:
            self.schedule_preview()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if os.path.exists(self._frame_path) and self.pv.pixmap() is not None and not self.pv.pixmap().isNull():
            self.pv.setPixmap(QPixmap(self._frame_path).scaled(self.pv.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # ---------------------------------------------------------------- workers / status
    def say(self, text):
        self.status.setText(text)

    def run_worker(self, fn, label, on_done):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, APP_NAME, "Please wait for the current task to finish (or cancel it).")
            return
        w = Worker(fn)
        self.worker = w
        self.say(label)
        self.prog.setValue(0)
        self.prog.setVisible(True)
        self.cancel_btn.setVisible(True)
        w.status.connect(self.say)
        w.progress.connect(lambda v: self.prog.setValue(int(v)))

        def finish():
            self.prog.setVisible(False)
            self.cancel_btn.setVisible(False)

        def done(r):
            finish()
            on_done(r)

        def failed(msg):
            finish()
            if msg != "Cancelled":
                QMessageBox.warning(self, APP_NAME, msg)
            self.say(msg if msg == "Cancelled" else "Something went wrong.")
        w.done.connect(done)
        w.failed.connect(failed)
        w.start()

    def cancel(self):
        if self.worker:
            self.worker.stop = True
            self.say("Cancelling...")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    qs = QSettings("Ideawood", "IdeawoodArtists")
    apply_theme(app, qs.value("theme", "Midnight"), base_pt=10)
    w = Studio()
    w.show()
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".iwlyric") and os.path.exists(sys.argv[1]):
        w.load_project(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
