import json
import os
import subprocess

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from conftest import needs_ffmpeg
from ideawood_artists import cloud, lipsync
from ideawood_artists import lyrics as L
from ideawood_artists import scenes as scn
from ideawood_artists.project import Project, Scene
from ideawood_artists.toon import ToonClip

app = QApplication.instance() or QApplication([])

RHUBARB_JSON = json.dumps({"metadata": {"duration": 2.0}, "mouthCues": [
    {"start": 0.0, "end": 0.5, "value": "X"}, {"start": 0.5, "end": 1.0, "value": "D"},
    {"start": 1.0, "end": 1.5, "value": "B"}, {"start": 1.5, "end": 2.0, "value": "Z"}]})


def test_parse_cues_and_shape_at():
    cues = lipsync.parse_cues(RHUBARB_JSON)
    assert [c[2] for c in cues] == ["X", "D", "B", "X"]          # unknown letter becomes resting
    assert lipsync.shape_at(cues, 0.7) == "D" and lipsync.shape_at(cues, 1.2) == "B"
    assert lipsync.shape_at(cues, 5.0) == "X" and lipsync.shape_at([], 1.0) == "X" and lipsync.shape_at(cues, -1) == "X"


def test_cues_roundtrip(tmp_path):
    cues = lipsync.parse_cues(RHUBARB_JSON)
    lipsync.save_cues(str(tmp_path), cues, 12.0, 2.0)
    assert lipsync.load_cues(str(tmp_path)) == cues
    assert lipsync.load_cues(str(tmp_path / "nothing")) == []


def test_mouth_position_inherits_from_earlier_frames(tmp_path):
    c = ToonClip.new(640, 360, 12, str(tmp_path / "c"))
    c.extend_to(1.0)
    assert c.mouth_pos(3) == (320.0, 360 * 0.55)
    c.set_mouth_pos(2, 100, 120)
    c.set_mouth_pos(6, 400, 200)
    assert c.mouth_pos(1) == (320.0, 360 * 0.55) and c.mouth_pos(4) == (100.0, 120.0) and c.mouth_pos(9) == (400.0, 200.0)
    c.mouth["on"] = True
    c.save_meta()
    again = ToonClip.load(c.folder)
    assert again.mouth["on"] and again.mouth_pos(9) == (400.0, 200.0)


def test_storyboard_request_and_parser(monkeypatch):
    seen = {}

    def fake(self, url, payload, headers=None):
        seen.update(url=url, payload=payload, headers=headers)
        return {"storyboard": {"title": "T", "scenes": [
            {"section": "Verse 1", "lyric": "We chase the moon", "actionDescription": "A bear chases a paper moon.",
             "camera": "pan left", "moodPrompt": "storybook, warm"},
            {"section": "Chorus", "description": "They fly.", "camera": ""}, {"junk": 1}, "bad"]}}
    monkeypatch.setattr(cloud.CloudClient, "_post_json", fake)
    res = cloud.CloudClient("quotetube-key").toon_storyboard("l1\nl2", 30, 4, api_key="board-key")
    assert seen["url"] == "https://dooddraw.lovable.app/api/public/v1/toon"
    assert seen["headers"] == {"x-api-key": "board-key"}
    assert seen["payload"] == {"task": "storyboard", "lyrics": "l1\nl2", "duration": 30, "sceneCount": 4,
                               "style": "storybook", "context": ""}
    items = cloud.parse_storyboard(res)
    assert len(items) == 2 and items[0]["action"].startswith("A bear") and items[1]["action"] == "They fly."
    with pytest.raises(cloud.NotSignedIn):
        cloud.CloudClient("k").toon_storyboard("x", 10, 2, api_key="")
    assert cloud.parse_storyboard({"scenes": [{"action": "x"}]})[0]["action"] == "x" and cloud.parse_storyboard(None) == []


def test_apply_storyboard_and_replan_keeps_ideas():
    scenes = [Scene(0, 8, key="a"), Scene(8, 16, key="b"), Scene(16, 24, key="a")]
    n = scn.apply_storyboard(scenes, [{"section": "Verse", "action": "Bear walks.", "camera": "pan", "mood": "warm"},
                                      {"action": "Bear flies."}])
    assert n == 3 and scenes[0].idea.startswith("Verse: Bear walks. Camera: pan. Look: warm.")
    assert scenes[2].idea == "Bear flies."                           # 2 ideas spread over 3 scenes
    new = scn.replan_keep_media(scenes, [Scene(0, 8, key="a"), Scene(8, 16, key="b")])
    assert new[0].idea == scenes[0].idea and new[1].idea == scenes[1].idea
    assert Project.from_dict(Project(scenes=scenes).to_dict()).scenes[0].idea == scenes[0].idea


@pytest.fixture()
def song(tmp_path):
    path = str(tmp_path / "s.mp3")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=6", path], check=True)
    return path


@needs_ffmpeg
def test_editor_lipsync_overlay_and_full_length_export(tmp_path, song, monkeypatch):
    from ideawood_artists import toon_editor as te
    from ideawood_artists.mediautil import media_info
    p = Project(audio=song, duration=6.0)
    p.lines = L.finalize_timing(L.distribute_evenly(L.parse_lyrics("hello there"), 6.0, lead=0.5), 6.0)
    p.scenes = [Scene(0, 6, "gradient", idea="Bear waves.")]
    ed = te.ToonEditor(None, p, 0)
    assert ed.mouth_overlay() is None                      # off by default
    ed.board.set_tool("mouth")
    ed.board.pointer_down(QPointF(500, 300))               # clicking with the lip-sync tool switches the mouth on
    ed.board.pointer_move(QPointF(520, 310))
    ed.board.pointer_up(QPointF(520, 310))
    img, rect = ed.mouth_overlay()
    assert ed.clip.mouth["on"] and abs(rect.center().x() - 520) < 1 and img.width() == 240
    ed.cues = lipsync.parse_cues(RHUBARB_JSON)
    assert ed.mouth_overlay(0, 0.7)[0].cacheKey() != ed.mouth_overlay(0, 0.2)[0].cacheKey()      # D differs from X
    shown = ed.composite(0, 0.7)
    assert shown.pixelColor(520, 310).red() < 120          # dark mouth drawn over the white background
    # export: lip-sync on -> the clip covers the whole 6 s scene even though only 1 frame was drawn
    monkeypatch.setattr(te.QProgressDialog, "wasCanceled", lambda self: False)
    ed.save_and_close()
    assert ed.result_clip is not None
    assert abs(media_info(ed.clip.video)["duration"] - 6.0) < 0.3


@needs_ffmpeg
def test_rhubarb_real_binary_if_present(tmp_path, song):
    try:
        lipsync.find_rhubarb()
    except FileNotFoundError:
        pytest.skip("rhubarb not installed here")
    cues = lipsync.analyze(song, 1.0, 3.0, "hello there")
    assert cues and all(c[2] in lipsync.SHAPES and c[1] >= c[0] for c in cues)
