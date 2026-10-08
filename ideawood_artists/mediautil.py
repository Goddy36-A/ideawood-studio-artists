"""Small ffmpeg/ffprobe helpers (probe + a cancellable progress-reporting job). No Qt."""
from __future__ import annotations

import json
import subprocess
from typing import Callable, Optional

from .paths import find_tool, no_window_flags


def probe(path: str) -> dict:
    r = subprocess.run([find_tool("ffprobe"), "-v", "error", "-print_format", "json", "-show_format",
                        "-show_streams", path], capture_output=True, text=True, errors="replace",
                       creationflags=no_window_flags())
    if r.returncode != 0:
        raise RuntimeError("Cannot read this file: " + (r.stderr or "").strip()[-200:])
    return json.loads(r.stdout or "{}")


def media_info(path: str) -> dict:
    d = probe(path)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    dur = float((d.get("format") or {}).get("duration", 0) or 0)
    w = h = 0
    if v:
        w, h = int(v.get("width", 0)), int(v.get("height", 0))
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        rot = rot or int((v.get("tags") or {}).get("rotate", 0) or 0)
        if abs(rot) in (90, 270):
            w, h = h, w
    return {"has_video": v is not None, "has_audio": a is not None, "w": w, "h": h, "duration": dur}


class Job:
    """Runs one ffmpeg process (``-progress pipe:1``), reporting 0..100."""

    def __init__(self, cmd: list[str], duration: float, cwd: Optional[str] = None):
        self.cmd, self.duration, self.cwd = cmd, max(duration, 0.1), cwd
        self.proc: Optional[subprocess.Popen] = None
        self.cancelled = False

    def run(self, on_progress: Callable[[float], None] = lambda p: None) -> None:
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                     encoding="utf-8", errors="replace", creationflags=no_window_flags(),
                                     cwd=self.cwd)
        tail: list[str] = []
        for line in self.proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    on_progress(min(99.0, int(line.split("=")[1]) / 1_000_000 / self.duration * 100))
                except ValueError:
                    pass
            elif "=" not in line:
                tail = (tail + [line])[-15:]
        self.proc.wait()
        if self.cancelled:
            raise RuntimeError("Cancelled")
        if self.proc.returncode != 0:
            raise RuntimeError("ffmpeg failed:\n" + "\n".join(tail))
        on_progress(100.0)

    def cancel(self):
        self.cancelled = True
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
