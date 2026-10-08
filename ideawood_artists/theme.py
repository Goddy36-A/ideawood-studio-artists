"""Colour themes + the Qt stylesheet generator (so the UI looks consistent and is re-colourable)."""
import os
import tempfile

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPixmap, QPolygonF

THEMES = {
    "Midnight": dict(bg="#0E1120", panel="#151933", card="#1C2142", text="#E9EBF8", muted="#8E95BA",
                     border="#2B3158", accent="#7C6CFF", accent2="#22D3C5"),
    "Graphite": dict(bg="#111214", panel="#1A1C20", card="#23262C", text="#ECEDEF", muted="#8D929C",
                     border="#30343C", accent="#4C9AFF", accent2="#7DE3C3"),
    "Ocean": dict(bg="#0A1A2A", panel="#0F2335", card="#15314A", text="#E5F1FA", muted="#83A2BB",
                  border="#1E4262", accent="#19C3B1", accent2="#4C9AFF"),
    "Sunset": dict(bg="#190F17", panel="#231620", card="#2D1D2B", text="#F6EAF0", muted="#B28DA2",
                   border="#432A3E", accent="#FF7A59", accent2="#FFC857"),
    "Forest": dict(bg="#0D1712", panel="#13221A", card="#1A2E23", text="#E7F3EC", muted="#86A593",
                   border="#264135", accent="#3FD08A", accent2="#C6E65B"),
    "Light": dict(bg="#EEF1F8", panel="#FFFFFF", card="#F4F6FC", text="#1B1F3B", muted="#6A7096",
                  border="#D9DDEC", accent="#5B4BEA", accent2="#12B5A5"),
}

ACCENT_PRESETS = {"Violet": "#7C6CFF", "Blue": "#4C9AFF", "Teal": "#19C3B1", "Green": "#3FD08A",
                  "Orange": "#FF7A59", "Pink": "#F25CA8", "Red": "#F0506E", "Gold": "#F5B83D"}

QSS = """
QWidget { color: @text; font-family: "Segoe UI", "Inter", "Noto Sans", Arial, sans-serif; font-size: @fs pt; }
QMainWindow, QDialog, QWidget#root { background: @bg; }
QLabel { background: transparent; }
QLabel#muted { color: @muted; }
QLabel#title { font-size: @fsXL pt; font-weight: 700; }
QLabel#h { font-size: @fsL pt; font-weight: 600; }
QLabel#badge { background: @accentSoft; color: @accent; border-radius: 9px; padding: 2px 9px; font-weight: 600; }
QFrame#card { background: @panel; border: 1px solid @border; border-radius: 12px; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QStackedWidget { background: transparent; }
QToolTip { background: @panel; color: @text; border: 1px solid @border; padding: 5px; }

QListWidget#nav { background: @panel; border: 1px solid @border; border-radius: 12px; padding: 8px; outline: 0; }
QListWidget#nav::item { padding: 11px 12px; border-radius: 8px; color: @muted; margin: 1px 0; }
QListWidget#nav::item:hover { background: @card; color: @text; }
QListWidget#nav::item:selected, QListWidget#nav::item:selected:!active { background: @accentSoft; color: @accent; }
QListWidget#queue { background: @card; border: 1px solid @border; border-radius: 10px; padding: 4px; outline: 0; }
QListWidget#queue::item { padding: 8px 10px; border-radius: 6px; }
QListWidget#queue::item:selected, QListWidget#queue::item:selected:!active { background: @accentSoft; color: @text; }

QPushButton { background: @card; border: 1px solid @border; border-radius: 8px; padding: 7px 14px; }
QPushButton:hover { border-color: @accent; }
QPushButton:pressed { background: @accentSoft; }
QPushButton:disabled { color: @muted; border-color: @border; background: transparent; }
QPushButton#primary { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @accent, stop:1 @accent2);
    border: none; color: #FFFFFF; font-weight: 700; padding: 11px 20px; }
QPushButton#primary:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @accent2, stop:1 @accent); }
QPushButton#primary:disabled { background: @border; color: @muted; }
QPushButton#ghost { background: transparent; border: none; color: @muted; padding: 7px 10px; }
QPushButton#ghost:hover { color: @accent; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit {
    background: @card; border: 1px solid @border; border-radius: 8px; padding: 6px 9px; selection-background-color: @accent; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid @accent; }
QTextEdit { padding: 6px; font-family: Consolas, "Cascadia Mono", monospace; font-size: @fsS pt; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url(@arrow_down); width: 9px; height: 6px; }
QComboBox QAbstractItemView { background: @panel; border: 1px solid @border; selection-background-color: @accent;
    selection-color: #FFFFFF; outline: 0; padding: 4px; }
QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: none; background: transparent; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: none; background: transparent; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url(@arrow_up); width: 9px; height: 6px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url(@arrow_down); width: 9px; height: 6px; }

QCheckBox { spacing: 9px; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid @border; background: @card; }
QCheckBox::indicator:hover { border-color: @accent; }
QCheckBox::indicator:checked { background: @accent; border-color: @accent; image: url(@check); }

QSlider::groove:horizontal { height: 6px; background: @border; border-radius: 3px; }
QSlider::sub-page:horizontal { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @accent, stop:1 @accent2); border-radius: 3px; }
QSlider::handle:horizontal { background: @accent; border: 3px solid @panel; width: 12px; height: 12px; margin: -7px 0; border-radius: 9px; }
QSlider::handle:horizontal:hover { background: @accent2; }

QProgressBar { background: @card; border: 1px solid @border; border-radius: 8px; text-align: center; min-height: 16px; color: @text; }
QProgressBar::chunk { border-radius: 7px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 @accent, stop:1 @accent2); }

QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: @border; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: @muted; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:horizontal { background: @border; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QMenu { background: @panel; border: 1px solid @border; padding: 6px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: @accentSoft; }
"""


def _rgba(hex_color: str, a: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{int(a * 255)})"


def _make_icons(muted: str):
    d = os.path.join(tempfile.gettempdir(), "ideawood_ui")
    os.makedirs(d, exist_ok=True)
    tag = muted.lstrip("#")
    paths = {}

    def tri(name, up):
        pm = QPixmap(18, 12)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(muted))
        pts = [QPointF(3, 9), QPointF(9, 3), QPointF(15, 9)] if up else [QPointF(3, 3), QPointF(9, 9), QPointF(15, 3)]
        p.drawPolygon(QPolygonF(pts))
        p.end()
        path = os.path.join(d, f"{name}_{tag}.png")
        pm.save(path)
        paths[name] = path.replace("\\", "/")

    tri("arrow_up", True)
    tri("arrow_down", False)
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("#FFFFFF"), 2.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPolyline([QPointF(4.5, 9.5), QPointF(7.7, 12.7), QPointF(13.5, 5.5)])
    p.end()
    cp = os.path.join(d, "check.png")
    pm.save(cp)
    paths["check"] = cp.replace("\\", "/")
    return paths


def apply_theme(app, name: str, accent: str = "", accent2: str = "", base_pt: int = 10):
    p = dict(THEMES.get(name, THEMES["Midnight"]))
    if accent:
        p["accent"] = accent
    if accent2:
        p["accent2"] = accent2
    icons = _make_icons(p["muted"])
    tokens = dict(p, accentSoft=_rgba(p["accent"], 0.18), fs=str(base_pt), fsS=str(base_pt - 1),
                  fsL=str(base_pt + 1), fsXL=str(base_pt + 7), **icons)
    qss = QSS
    for k in sorted(tokens, key=len, reverse=True):
        qss = qss.replace("@" + k, tokens[k])
    app.setStyle("Fusion")
    pal = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.WindowText, "text"), (QPalette.Base, "card"),
                      (QPalette.AlternateBase, "panel"), (QPalette.Text, "text"), (QPalette.Button, "card"),
                      (QPalette.ButtonText, "text"), (QPalette.ToolTipBase, "panel"), (QPalette.ToolTipText, "text")):
        pal.setColor(role, QColor(p[key]))
    pal.setColor(QPalette.Highlight, QColor(p["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.PlaceholderText, QColor(p["muted"]))
    app.setPalette(pal)
    app.setStyleSheet(qss)
    return p
