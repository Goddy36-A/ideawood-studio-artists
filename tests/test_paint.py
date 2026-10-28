import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

from ideawood_artists import lyrics as L
from ideawood_artists import paint
from ideawood_artists.project import Project
from ideawood_artists.scenes import plan_scenes

app = QApplication.instance() or QApplication([])


def opaque(im: QImage) -> int:
    n = 0
    for y in range(0, im.height()):
        for x in range(0, im.width()):
            if im.pixelColor(x, y).alpha() > 0:
                n += 1
    return n


@pytest.mark.parametrize("kind", paint.BRUSH_TYPES)
def test_every_brush_paints(kind):
    frame = paint.new_image(200, 120)
    s = paint.Stroke(200, 120, kind, QColor("#c00000"))
    s.begin(QPointF(20, 60), 12)
    for x in range(20, 180, 10):
        s.add(QPointF(x, 60), QPointF(x + 10, 62), 12)
    s.commit(frame, 1.0)
    assert opaque(frame) > 30, kind


def test_marker_is_see_through_and_stroke_has_uniform_opacity():
    frame = paint.new_image(120, 60)
    s = paint.Stroke(120, 60, "Marker", QColor("#0000ff"))
    s.begin(QPointF(20, 30), 10)
    for _ in range(3):                                   # going over the same spot must not get darker inside one stroke
        s.add(QPointF(20, 30), QPointF(100, 30), 10)
    s.commit(frame, 1.0)
    a = frame.pixelColor(60, 30).alpha()
    assert 100 < a < 200


def test_erase_segment():
    frame = paint.new_image(100, 100)
    frame.fill(QColor("red"))
    paint.erase_segment(frame, QPointF(10, 50), QPointF(90, 50), 20)
    assert frame.pixelColor(50, 50).alpha() == 0 and frame.pixelColor(50, 5).alpha() == 255


def outline_box(w=300, h=200):
    im = paint.new_image(w, h)
    p = QPainter(im)
    p.setPen(QPen(QColor("black"), 6))
    p.drawRect(60, 40, 180, 120)
    p.end()
    return im


def test_flood_fill_stays_inside_the_outline_and_leaves_no_halo():
    im = outline_box()
    n = paint.flood_fill(im, 150, 100, QColor("#00cc00"), 48)
    assert n > 15000
    assert im.pixelColor(150, 100).green() == 204 and im.pixelColor(150, 100).alpha() == 255
    assert im.pixelColor(10, 10).alpha() == 0                      # outside untouched
    # the outline itself keeps its colour; no bright halo between line and fill
    assert im.pixelColor(60, 100).red() < 60 and im.pixelColor(60, 100).alpha() == 255


def test_flood_fill_blank_canvas_speed():
    im = paint.new_image(1280, 720)
    t = time.time()
    n = paint.flood_fill(im, 10, 10, QColor("#336699"), 0)
    assert n == 1280 * 720
    assert time.time() - t < 6.0


@pytest.mark.parametrize("kind", paint.SHAPES)
@pytest.mark.parametrize("mode", paint.SHAPE_MODES)
def test_shapes_draw(kind, mode):
    im = paint.new_image(200, 200)
    p = QPainter(im)
    paint.draw_shape(p, kind, QPointF(30, 30), QPointF(170, 150), QColor("black"), QColor("red"), 5, mode)
    p.end()
    if kind in ("Line", "Arrow") and mode != "Outline":
        return
    assert opaque(im) > 50


def test_constrain():
    q = paint.constrain("Rectangle", QPointF(10, 10), QPointF(110, 40))
    assert abs(q.x() - 10) == abs(q.y() - 10)
    q = paint.constrain("Line", QPointF(0, 0), QPointF(100, 12))
    assert abs(q.y()) < 1e-6


def test_text_and_picker_helpers():
    im = paint.new_image(300, 100)
    f = QFont()
    f.setPixelSize(40)
    paint.draw_text(im, QPointF(10, 10), "Hi\nthere", f, QColor("black"))
    assert opaque(im) > 100
    c = paint.visible_color(paint.new_image(10, 10), 5, 5, QColor("#123456"))
    assert c.name() == "#123456"


# ------------------------------------------------------------------ the board inside the editor
@pytest.fixture()
def ed():
    from ideawood_artists.toon_editor import ToonEditor
    p = Project(audio="", duration=10.0)
    p.lines = L.finalize_timing(L.distribute_evenly(L.parse_lyrics("hello there"), 10.0, lead=1.0), 10.0)
    p.scenes = plan_scenes(p.lines, 10.0)
    e = ToonEditor(None, p, 0)
    e.resize(1200, 800)
    yield e
    e.stop()


def drag(b, pts, button=Qt.LeftButton):
    b.pointer_down(QPointF(*pts[0]), button)
    for q in pts[1:]:
        b.pointer_move(QPointF(*q))
    b.pointer_up(QPointF(*pts[-1]))


def test_brush_eraser_undo_redo(ed):
    b = ed.board
    b.set_tool("brush")
    drag(b, [(100, 100), (300, 140), (500, 100)])
    assert opaque(ed.img_at(0)) > 200
    b.set_tool("eraser")
    drag(b, [(100, 100), (500, 100)])
    after_erase = opaque(ed.img_at(0))
    ed.undo()
    assert opaque(ed.img_at(0)) > after_erase
    ed.undo()
    assert opaque(ed.img_at(0)) == 0
    ed.redo()
    assert opaque(ed.img_at(0)) > 200


def test_fill_shape_text_and_picker(ed):
    b = ed.board
    b.set_tool("shape")
    b.shape, b.shape_mode = "Rectangle", "Outline"
    b.primary = QColor("#000000")
    drag(b, [(200, 150), (600, 450)])
    b.set_tool("fill")
    b.primary = QColor("#ff0000")
    b.pointer_down(QPointF(400, 300))
    assert ed.img_at(0).pixelColor(400, 300).red() == 255
    assert ed.img_at(0).pixelColor(20, 20).alpha() == 0
    b.set_tool("picker")
    b.pointer_down(QPointF(400, 300))
    assert b.primary.name() == "#ff0000"
    b.set_tool("text")
    b.primary = QColor("#0000ff")
    b.do_text(QPointF(700, 100), text="Hello")
    assert ed.img_at(0).pixelColor(0, 0).alpha() == 0
    assert opaque(ed.img_at(0)) > 100


def test_secondary_button_draws_with_secondary_colour(ed):
    b = ed.board
    b.set_tool("brush")
    b.primary, b.secondary = QColor("#ff0000"), QColor("#00ff00")
    drag(b, [(100, 100), (200, 100)], Qt.RightButton)
    c = ed.img_at(0).pixelColor(150, 100)
    assert c.green() == 255 and c.red() == 0


def test_selection_move_copy_flip_and_undo(ed):
    b = ed.board
    b.set_tool("brush")
    b.primary = QColor("#000000")
    drag(b, [(100, 100), (160, 100)])
    b.set_tool("select")
    drag(b, [(60, 60), (220, 160)])
    assert b.has_selection()
    before = opaque(ed.img_at(0))
    drag(b, [(150, 100), (450, 300)])                       # move the selection
    assert b.has_float()
    b.commit_selection()
    assert ed.img_at(0).pixelColor(110, 100).alpha() == 0   # left its old place
    assert opaque(ed.img_at(0)) > before * 0.8
    ed.undo()                                               # one undo puts everything back
    assert ed.img_at(0).pixelColor(130, 100).alpha() > 0
    b.select_all()
    b.copy()
    b.paste()
    assert b.has_float()
    b.flip(True)
    b.rotate90(True)
    b.commit_selection()


def test_zoom_pan_and_frame_change_commits_selection(ed):
    b = ed.board
    b.zoom_at(2.0)
    assert b.zoom == pytest.approx(2.0)
    b.fit_view()
    assert b.zoom == 1.0
    b.set_tool("brush")
    drag(b, [(100, 100), (200, 100)])
    b.set_tool("select")
    drag(b, [(80, 80), (220, 120)])
    drag(b, [(150, 100), (250, 200)])
    ed.add_frame()                                          # must place the floating pixels first
    assert not b.has_float() and ed.cur == 1
    ed.goto(0)
    assert opaque(ed.img_at(0)) > 100


def test_toolbox_tool_switch_and_colours(ed):
    pnl = ed.panel
    ed.board.set_tool("shape")
    assert pnl.tool_buttons["shape"].isChecked() and not pnl.tool_buttons["brush"].isChecked()
    pnl.use_color("#336699", False)
    pnl.use_color("#aa0000", True)
    assert ed.board.primary.name() == "#336699" and ed.board.secondary.name() == "#aa0000"
    ed.board.swap_colors()
    assert ed.board.primary.name() == "#aa0000"


def test_flip_really_flips(ed):
    b = ed.board
    b.set_tool("brush")
    b.primary = QColor("#000000")
    drag(b, [(100, 100), (130, 100)])                 # a short bar on the left side of the selection
    b.set_tool("select")
    drag(b, [(90, 80), (290, 120)])
    b.flip(True)
    b.commit_selection()
    assert ed.img_at(0).pixelColor(110, 100).alpha() == 0
    assert ed.img_at(0).pixelColor(270, 100).alpha() > 0
