import os
import subprocess

import pytest
from PIL import Image, ImageChops

from conftest import needs_ffmpeg
from ideawood_artists import lyrics as L
from ideawood_artists.mediautil import media_info
from ideawood_artists.project import Project, Scene
from ideawood_artists.render import preview_frame, render
from ideawood_artists.scenes import plan_scenes
from ideawood_artists.styles import PRESETS

pytestmark = needs_ffmpeg


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    d = tmp_path_factory.mktemp("r")
    song = str(d / "s.mp3")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=14", song], check=True)
    img = str(d / "bg.jpg")
    Image.new("RGB", (800, 450), (30, 90, 160)).save(img)
    p = Project(audio=song, duration=14.0, title="Test Song", artist="Tester", quality="480p (fast draft)")
    p.lines = L.finalize_timing(L.distribute_evenly(L.parse_lyrics("Hello bright world\nWe sing together\n\nLouder and louder"), 14.0, lead=4.0), 14.0)
    p.scenes = [Scene(0, 7, "image", img, key="a"), Scene(7, 14, "gradient", key="b")]
    p.style = PRESETS["Karaoke Bold"].copy()
    p.style.transition_sec = 0.8
    return p


def test_frame_has_text_only_while_singing(project, tmp_path):
    a, b = str(tmp_path / "a.png"), str(tmp_path / "b.png")
    preview_frame(project, 0.5, a)                    # before the first line (title card is off at 0.5 s? fade-in)
    preview_frame(project, project.lines[0].start + 0.8, b)
    diff = ImageChops.difference(Image.open(a).convert("RGB"), Image.open(b).convert("RGB")).getbbox()
    assert diff is not None


def test_karaoke_fill_progresses(project, tmp_path):
    ln = project.lines[0]
    f1, f2 = str(tmp_path / "1.png"), str(tmp_path / "2.png")
    preview_frame(project, ln.start + (ln.end - ln.start) * 0.2, f1)
    preview_frame(project, ln.end - 0.1, f2)

    def sung_pixels(path):                            # count yellow (sung colour #FFD84D) pixels
        im = Image.open(path).convert("RGB")
        return sum(1 for r, g, b in im.getdata() if r > 220 and 180 < g < 235 and b < 130)
    assert sung_pixels(f2) > sung_pixels(f1) + 100


def test_full_render_with_transition_and_viz(project, tmp_path):
    project.style.viz = "bars"
    out = str(tmp_path / "o.mp4")
    r = render(project, out)
    info = media_info(out)
    assert info["has_video"] and info["has_audio"] and abs(info["duration"] - 14.0) < 0.3
    project.style.viz = "none"


def test_vertical_format_and_preview_clip(project, tmp_path):
    project.fmt = "Portrait 9:16 (Reels / TikTok / Shorts)"
    out = str(tmp_path / "v.mp4")
    render(project, out, preview=True)
    info = media_info(out)
    assert info["h"] > info["w"] and info["duration"] <= 22.5
    project.fmt = "Landscape 16:9 (YouTube)"


def test_cancel(project, tmp_path):
    from ideawood_artists.render import Cancelled
    with pytest.raises(Cancelled):
        render(project, str(tmp_path / "c.mp4"), should_cancel=lambda: True, on_progress=lambda v: None)
