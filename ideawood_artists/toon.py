"""Toon clips: frame-by-frame cartoons drawn inside the app and used as a scene background. No Qt.

A clip lives in its own folder:  meta.json + one PNG per drawn frame (blank frames have no file) + clip.mp4.
Frames are listed by id in ``order`` so inserting / duplicating / deleting never renames files. The exported
``clip.mp4`` is an ordinary video, so the one-pass FFmpeg render treats it like any other background clip and
loops it to fill the scene.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional

from .paths import find_tool, no_window_flags, user_data_dir

META = "meta.json"
CLIP = "clip.mp4"


def toons_root() -> str:
    d = os.path.join(user_data_dir(), "toons")
    os.makedirs(d, exist_ok=True)
    return d


@dataclass
class ToonClip:
    folder: str
    w: int = 1280
    h: int = 720
    fps: int = 12
    bg: str = "#ffffff"
    order: List[int] = field(default_factory=lambda: [1])
    next_id: int = 2
    # lip-sync mouth: on/off, width in px, per-frame position {frame id: [x, y]} (a frame without one inherits the
    # previous frame's), and an optional folder with your own A.png ... H.png, X.png
    mouth: dict = field(default_factory=lambda: {"on": False, "size": 240, "pos": {}, "kit": ""})

    # ---------------------------------------------------------------- creation / persistence
    @staticmethod
    def new(w: int, h: int, fps: int = 12, folder: Optional[str] = None) -> "ToonClip":
        folder = folder or os.path.join(toons_root(), uuid.uuid4().hex[:10])
        os.makedirs(folder, exist_ok=True)
        c = ToonClip(folder, w - w % 2, h - h % 2, fps)
        c.save_meta()
        return c

    @staticmethod
    def load(folder: str) -> "ToonClip":
        with open(os.path.join(folder, META), "r", encoding="utf-8") as f:
            d = json.load(f)
        c = ToonClip(folder, d["w"], d["h"], d["fps"], d.get("bg", "#ffffff"),
                     list(d.get("order") or [1]), int(d.get("next_id", 2)))
        c.mouth.update(d.get("mouth") or {})
        return c

    def save_meta(self):
        with open(os.path.join(self.folder, META), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "w": self.w, "h": self.h, "fps": self.fps, "bg": self.bg,
                       "order": self.order, "next_id": self.next_id, "mouth": self.mouth}, f)

    # ---------------------------------------------------------------- frames
    def __len__(self) -> int:
        return len(self.order)

    @property
    def seconds(self) -> float:
        return len(self.order) / float(self.fps)

    def path_of(self, fid: int) -> str:
        return os.path.join(self.folder, f"f_{fid:05d}.png")

    def frame_path(self, i: int) -> str:
        return self.path_of(self.order[i])

    def has_art(self, i: int) -> bool:
        return os.path.isfile(self.frame_path(i))

    def _new_id(self) -> int:
        fid = self.next_id
        self.next_id += 1
        return fid

    def insert_blank(self, after: int) -> int:
        """Insert a blank frame after index ``after`` (-1 = at the start); returns its index."""
        self.order.insert(after + 1, self._new_id())
        return after + 1

    def duplicate(self, i: int) -> int:
        fid = self._new_id()
        if self.has_art(i):
            shutil.copyfile(self.frame_path(i), self.path_of(fid))
        self.order.insert(i + 1, fid)
        return i + 1

    def delete(self, i: int) -> int:
        """Delete frame i (never the last one); returns the index to show afterwards."""
        if len(self.order) <= 1:
            return 0
        fid = self.order.pop(i)
        try:
            os.remove(self.path_of(fid))
        except OSError:
            pass
        return min(i, len(self.order) - 1)

    def extend_to(self, seconds: float) -> int:
        """Append blank frames until the clip lasts ``seconds``; returns how many were added."""
        need = int(round(seconds * self.fps)) - len(self.order)
        for _ in range(max(0, need)):
            self.order.append(self._new_id())
        return max(0, need)

    # ---------------------------------------------------------------- lip-sync mouth placement
    def mouth_pos(self, i: int):
        """Where the mouth sits on frame i: its own position, else the nearest earlier one, else the middle."""
        pos = self.mouth.get("pos") or {}
        for k in range(min(i, len(self.order) - 1), -1, -1):
            v = pos.get(str(self.order[k]))
            if v:
                return float(v[0]), float(v[1])
        return self.w / 2.0, self.h * 0.55

    def set_mouth_pos(self, i: int, x: float, y: float):
        self.mouth.setdefault("pos", {})[str(self.order[i])] = [round(float(x), 1), round(float(y), 1)]

    @property
    def video(self) -> str:
        return os.path.join(self.folder, CLIP)


def export_mp4(clip: ToonClip, frames: Iterable[bytes], out: Optional[str] = None,
               on_progress: Callable[[int], None] = lambda n: None, should_cancel: Callable[[], bool] = lambda: False) -> str:
    """Pipe raw BGRA frames (clip.w x clip.h, already composited on the background) into FFmpeg -> clip.mp4."""
    out = out or clip.video
    tmp = out + ".part.mp4"
    cmd = [find_tool("ffmpeg"), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{clip.w}x{clip.h}",
           "-r", str(clip.fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", tmp]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=no_window_flags())
    n = 0
    try:
        for fr in frames:
            if should_cancel():
                proc.kill()
                raise RuntimeError("Cancelled")
            proc.stdin.write(fr)
            n += 1
            on_progress(n)
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        proc.wait()
    except BrokenPipeError:
        err = proc.stderr.read().decode("utf-8", "replace")
        proc.wait()
    if proc.returncode != 0 or not os.path.isfile(tmp):
        raise RuntimeError("Could not make the cartoon clip.\n" + err[-300:])
    os.replace(tmp, out)
    return out
