import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("IDEAWOOD_ARTISTS_DATA", tempfile.mkdtemp(prefix="iw_test_"))

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg") and not os.path.exists("bin/ffmpeg.exe"), reason="ffmpeg missing")
