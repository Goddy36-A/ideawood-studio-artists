"""Left-hand toolbox of the cartoon editor: tool buttons, options for the active tool, colours and zoom."""
from __future__ import annotations

from typing import Callable, Dict, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFileDialog, QFontComboBox, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox, QToolButton, QVBoxLayout,
                               QWidget)

from . import paint
from .toon_board import PaintBoard

PALETTE = ["#000000", "#3b3b3b", "#7f7f7f", "#c3c3c3", "#ffffff", "#880015", "#ed1c24", "#ff7f27",
           "#fff200", "#ffe5a8", "#22b14c", "#b5e61d", "#00a2e8", "#99d9ea", "#3f48cc", "#7092be",
           "#a349a4", "#c8bfe7", "#b97a57", "#ffaec9", "#8a5a2b", "#f5c6a5", "#0b3d2e", "#ff4fa3"]

TOOL_LABELS: Tuple[Tuple[str, str, str], ...] = (
    ("brush", "Brush", "B"), ("eraser", "Eraser", "E"), ("fill", "Fill", "F"), ("shape", "Shapes", "U"),
    ("text", "Text", "T"), ("select", "Select", "M"), ("picker", "Picker", "I"), ("hand", "Hand", "H"))

# which option groups are visible for each tool
TOOL_GROUPS = {"brush": ("brush", "size", "opacity", "smooth"), "eraser": ("size",), "fill": ("fill", "opacity"),
               "shape": ("shape", "size", "opacity"), "text": ("text", "opacity"), "select": ("sel",),
               "picker": ("hint_picker",), "hand": ("hint_hand",)}


def _button(text: str, fn: Callable, tip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setAutoDefault(False)
    b.setFocusPolicy(Qt.NoFocus)
    b.clicked.connect(lambda _=False: fn())
    if tip:
        b.setToolTip(tip)
    return b


class Swatch(QToolButton):
    """Palette colour: left click = primary colour, right click = secondary colour."""
    picked = Signal(str, bool)

    def __init__(self, color: str):
        super().__init__()
        self.color = color
        self.setFixedSize(24, 24)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet(f"background:{color}; border:1px solid #666;")

    def mousePressEvent(self, e):
        if e.button() in (Qt.LeftButton, Qt.RightButton):
            self.picked.emit(self.color, e.button() == Qt.RightButton)


class ToolPanel(QWidget):
    def __init__(self, board: PaintBoard):
        super().__init__()
        self.board = board
        self.tool_buttons: Dict[str, QPushButton] = {}
        self.groups: Dict[str, QWidget] = {}
        self.setFixedWidth(250)
        self.setStyleSheet("QPushButton:checked { background: palette(highlight); color: palette(highlighted-text); }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(8)

        grid = QGridLayout()
        grid.setSpacing(4)
        for i, (name, label, key) in enumerate(TOOL_LABELS):
            b = QPushButton(f"{label}  ({key})")
            b.setCheckable(True)
            b.setAutoDefault(False)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, n=name: board.set_tool(n))
            self.tool_buttons[name] = b
            grid.addWidget(b, i // 2, i % 2)
        lay.addLayout(grid)

        # ---- option groups (shown per tool)
        self.brush_combo = QComboBox()
        self.brush_combo.addItems(paint.BRUSH_TYPES)
        self.brush_combo.currentTextChanged.connect(lambda v: setattr(board, "brush", v))
        self._group("brush", "Brush type", self.brush_combo)
        w, self.size_slider = self._slider("Size", 1, 200, board.size, lambda v: setattr(board, "size", v), " px")
        self._group("size", None, w)
        w, _ = self._slider("Opacity", 5, 100, int(board.opacity * 100), lambda v: setattr(board, "opacity", v / 100.0), "%")
        self._group("opacity", None, w)
        w, _ = self._slider("Smoothing", 0, 90, int(board.stab * 100), lambda v: setattr(board, "stab", v / 100.0), "%")
        self._group("smooth", None, w)
        w, _ = self._slider("Tolerance", 0, 128, board.tolerance, lambda v: setattr(board, "tolerance", v))
        self._group("fill", "Fill bucket", w)

        self.shape_combo = QComboBox()
        self.shape_combo.addItems(paint.SHAPES)
        self.shape_combo.setCurrentText(board.shape)
        self.shape_combo.currentTextChanged.connect(lambda v: setattr(board, "shape", v))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(paint.SHAPE_MODES)
        self.mode_combo.currentTextChanged.connect(lambda v: setattr(board, "shape_mode", v))
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.shape_combo)
        bl.addWidget(self.mode_combo)
        hint = QLabel("Outline uses the primary colour, fill the secondary. Hold Shift for a perfect square / circle / 45-degree line.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        bl.addWidget(hint)
        self._group("shape", "Shape", box)

        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(board.font)
        self.font_combo.currentFontChanged.connect(self._font_changed)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 400)
        self.font_size.setValue(board.font.pixelSize())
        self.font_size.valueChanged.connect(self._font_changed)
        self.bold = QCheckBox("Bold")
        self.italic = QCheckBox("Italic")
        self.bold.toggled.connect(self._font_changed)
        self.italic.toggled.connect(self._font_changed)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.font_combo)
        row = QHBoxLayout()
        row.addWidget(QLabel("Size"))
        row.addWidget(self.font_size)
        row.addWidget(self.bold)
        row.addWidget(self.italic)
        bl.addLayout(row)
        bl.addWidget(QLabel("Click on the picture, then type."))
        self._group("text", "Text", box)

        box = QWidget()
        sl = QGridLayout(box)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(4)
        acts = (("Select all", board.select_all), ("Delete", board.delete_selection), ("Copy", board.copy),
                ("Cut", board.cut), ("Paste", board.paste), ("Insert picture...", self.insert_picture),
                ("Flip horizontal", lambda: board.flip(True)), ("Flip vertical", lambda: board.flip(False)),
                ("Rotate left", lambda: board.rotate90(False)), ("Rotate right", lambda: board.rotate90(True)))
        for i, (t, fn) in enumerate(acts):
            sl.addWidget(_button(t, fn), i // 2, i % 2)
        hint = QLabel("Drag to select, drag inside to move (Ctrl = copy), drag the corner square to resize "
                      "(Shift keeps the shape). Esc places it.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        sl.addWidget(hint, len(acts) // 2 + 1, 0, 1, 2)
        self._group("sel", "Selection", box)

        for name, text in (("hint_picker", "Click to pick a colour from the picture: left click = primary, right click = "
                            "secondary. Alt+click works with any tool."),
                           ("hint_hand", "Drag to move the picture around. Scroll wheel zooms. Hold Space with any "
                            "tool to move it.")):
            h = QLabel(text)
            h.setWordWrap(True)
            h.setObjectName("muted")
            self._group(name, None, h)

        # ---- colours
        self.primary_btn, self.secondary_btn = QPushButton(), QPushButton()
        for b, which in ((self.primary_btn, False), (self.secondary_btn, True)):
            b.setFixedSize(46, 34)
            b.setAutoDefault(False)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, s=which: self.choose_color(s))
        self.primary_btn.setToolTip("Primary colour (left mouse button)")
        self.secondary_btn.setToolTip("Secondary colour (right mouse button)")
        cap = QLabel("Colours  (left click = primary, right click = secondary)")
        cap.setWordWrap(True)
        cap.setStyleSheet("font-weight: 600;")
        lay.addWidget(cap)
        row = QHBoxLayout()
        row.addWidget(self.primary_btn)
        sw = _button("swap", board.swap_colors, "Swap primary and secondary (X)")
        sw.setMinimumWidth(56)
        row.addWidget(sw)
        row.addWidget(self.secondary_btn)
        row.addStretch(1)
        lay.addLayout(row)
        pal = QGridLayout()
        pal.setSpacing(2)
        for i, c in enumerate(PALETTE):
            s = Swatch(c)
            s.picked.connect(self.use_color)
            pal.addWidget(s, i // 8, i % 8)
        lay.addLayout(pal)
        lay.addWidget(_button("More colours...", lambda: self.choose_color(False)))

        # ---- zoom
        self.zoom_lbl = QLabel("100%")
        self.zoom_lbl.setFixedWidth(52)
        self.zoom_lbl.setAlignment(Qt.AlignCenter)
        zr = QHBoxLayout()
        zr.addWidget(_button("-", lambda: board.zoom_at(1 / 1.25), "Zoom out (Ctrl+-)"))
        zr.addWidget(self.zoom_lbl)
        zr.addWidget(_button("+", lambda: board.zoom_at(1.25), "Zoom in (Ctrl++)"))
        zr.addWidget(_button("Fit", board.fit_view, "Fit to window (Ctrl+0)"))
        lay.addLayout(zr)
        lay.addStretch(1)

        board.toolChanged.connect(self.show_tool)
        board.colorsChanged.connect(self.paint_colors)
        board.viewChanged.connect(self.paint_zoom)
        self.show_tool(board.tool)
        self.paint_colors()

    # ------------------------------------------------------------------ building blocks
    def _group(self, name: str, title, widget: QWidget):
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        if title:
            t = QLabel(title)
            t.setStyleSheet("font-weight: 600;")
            v.addWidget(t)
        v.addWidget(widget)
        self.groups[name] = box
        self.layout().addWidget(box)

    def _slider(self, label, lo, hi, value, setter, suffix=""):
        w = QWidget()
        l = QHBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(label)
        lab.setFixedWidth(64)
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(value)
        s.setFocusPolicy(Qt.NoFocus)
        val = QLabel(f"{value}{suffix}")
        val.setFixedWidth(52)

        def changed(x):
            setter(x)
            val.setText(f"{x}{suffix}")
        s.valueChanged.connect(changed)
        l.addWidget(lab)
        l.addWidget(s, 1)
        l.addWidget(val)
        return w, s

    # ------------------------------------------------------------------ reactions
    def show_tool(self, name: str):
        for n, b in self.tool_buttons.items():
            b.setChecked(n == name)
        visible = TOOL_GROUPS.get(name, ())
        for g, box in self.groups.items():
            box.setVisible(g in visible)

    def set_size(self, v: int):
        self.size_slider.setValue(max(self.size_slider.minimum(), min(self.size_slider.maximum(), v)))

    def paint_colors(self):
        self.primary_btn.setStyleSheet(f"background:{self.board.primary.name()}; border:2px solid #999;")
        self.secondary_btn.setStyleSheet(f"background:{self.board.secondary.name()}; border:2px solid #999;")

    def paint_zoom(self):
        s, _, _ = self.board._fit()
        self.zoom_lbl.setText(f"{int(round(s * 100))}%")

    def use_color(self, color: str, secondary: bool):
        if secondary:
            self.board.secondary = QColor(color)
        else:
            self.board.primary = QColor(color)
        self.paint_colors()

    def choose_color(self, secondary: bool):
        cur = self.board.secondary if secondary else self.board.primary
        c = QColorDialog.getColor(cur, self)
        if c.isValid():
            self.use_color(c.name(), secondary)

    def _font_changed(self, *_):
        f = QFont(self.font_combo.currentFont())
        f.setPixelSize(self.font_size.value())
        f.setBold(self.bold.isChecked())
        f.setItalic(self.italic.isChecked())
        self.board.font = f

    def insert_picture(self):
        path, _ = QFileDialog.getOpenFileName(self, "Insert a picture", "",
                                              "Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if path:
            from PySide6.QtGui import QImage
            im = QImage(path)
            if not im.isNull():
                self.board.paste(im)
