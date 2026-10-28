import os
import subprocess

import pytest

from conftest import needs_ffmpeg
from ideawood_artists import lyrics as L
from ideawood_artists.project import Project, Scene
from ideawood_artists.scenes import plan_scenes
from ideawood_artists.toon import ToonClip, export_mp4


def test_clip_frame_operations(tmp_path):
    c = ToonClip.new(640, 360, 12, str(tmp_path / "c"))
    assert len(c) == 1
    i = c.insert_blank(0)
    assert i == 1 and len(c) == 2
    with open(c.frame_path(0), "wb") as f:
        f.write(b"png")
    j = c.duplicate(0)
    assert j == 1 and os.path.isfile(c.frame_path(1)) and c.order[0] != c.order[1]
    dup_id = c.order[1]
    assert c.delete(1) == 1 and not os.path.exists(c.path_of(dup_id))
    c.extend_to(2.0)
    assert len(c) == 24
    c.save_meta()
    again = ToonClip.load(str(tmp_path / "c"))
    assert again.order == c.order and again.fps == 12 and again.next_id == c.next_id


def test_never_deletes_last_frame(tmp_path):
    c = ToonClip.new(320, 180, 12, str(tmp_path / "c"))
    assert c.delete(0) == 0 and len(c) == 1


@needs_ffmpeg
def test_export_and_render_with_toon_scene(tmp_path):
    from ideawood_artists.mediautil import media_info
    from ideawood_artists.render import render
    c = ToonClip.new(320, 180, 12, str(tmp_path / "c"))
    c.extend_to(1.0)
    blank = bytes([255, 255, 255, 255]) * (c.w * c.h)
    red = bytes([0, 0, 255, 255]) * (c.w * c.h)               # BGRA red
    out = export_mp4(c, (blank if k % 2 else red for k in range(len(c))))
    info = media_info(out)
    assert info["w"] == 320 and abs(info["duration"] - 1.0) < 0.2

    song = str(tmp_path / "s.mp3")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=6", song], check=True)
    p = Project(audio=song, duration=6.0, title="T", quality="480p (fast draft)")
    p.lines = L.finalize_timing(L.distribute_evenly(L.parse_lyrics("one two\nthree four"), 6.0, lead=1.0), 6.0)
    p.scenes = [Scene(0, 6, "video", out, source="toon", toon=c.folder)]   # 1 s clip loops across 6 s
    q = Project.from_dict(p.to_dict())
    assert q.scenes[0].toon == c.folder and q.scenes[0].source == "toon"
    res = render(p, str(tmp_path / "o.mp4"))
    assert abs(media_info(res["path"])["duration"] - 6.0) < 0.5


def test_editor_draws_saves_and_undoes(tmp_path):
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPointF
    from PySide6.QtWidgets import QApplication
    from ideawood_artists.toon_editor import ToonEditor
    app = QApplication.instance() or QApplication([])
    p = Project(audio="", duration=10.0)
    p.lines = L.finalize_timing(L.distribute_evenly(L.parse_lyrics("hello there"), 10.0, lead=1.0), 10.0)
    p.scenes = plan_scenes(p.lines, 10.0)
    ed = ToonEditor(None, p, 0)
    b = ed.board
    b.pointer_down(QPointF(50, 50))
    b.pointer_move(QPointF(300, 200))
    b.pointer_up(QPointF(300, 200))
    ed.add_frame()
    b.pointer_down(QPointF(60, 60))
    b.pointer_move(QPointF(320, 220))
    b.pointer_up(QPointF(320, 220))
    ed.fill_scene()
    assert len(ed.clip) >= int(round(p.scenes[0].duration * ed.clip.fps))
    ed.goto(0)
    ed.flush_all()
    assert os.path.isfile(ed.clip.frame_path(0)) and os.path.isfile(ed.clip.frame_path(1))
    assert ed.guide_text() in ("", "hello there")
    ed.goto(0)
    ed.undo()                                      # undo restores frame 0 to blank
    assert ed.img_at(0).pixelColor(100, 100).alpha() == 0
    ed.stop()
