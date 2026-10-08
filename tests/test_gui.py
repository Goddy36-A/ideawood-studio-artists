import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from conftest import needs_ffmpeg


@needs_ffmpeg
def test_gui_flow(tmp_path):
    import subprocess
    from PySide6.QtWidgets import QApplication
    from ideawood_artists.gui import Studio
    from ideawood_artists.theme import apply_theme
    song = str(tmp_path / "s.mp3")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=12", song], check=True)
    app = QApplication.instance() or QApplication([])
    apply_theme(app, "Midnight")
    w = Studio()
    assert w.set_audio(song)
    w.lyr_edit.setPlainText("[Verse]\nfirst line here\nsecond line here\n\n[Chorus]\nsing along now")
    w.do_spread()
    assert len(w.p.lines) == 3 and w.p.scenes
    for i in range(5):
        w.nav.setCurrentRow(i)
    w.load_preset("Cinematic Gold")
    assert w.p.style.font == "DM Serif Display"
    w.p.save(str(tmp_path / "p.iwlyric"))
    w.load_project(str(tmp_path / "p.iwlyric"))
    assert len(w.p.lines) == 3
