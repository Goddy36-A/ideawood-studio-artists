"""The lyric-video project: song, lyrics, look, background scenes, output format. Saved as a ``.iwlyric`` JSON file."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import List, Optional

from .lyrics import LyricLine
from .styles import PRESETS, DEFAULT_PRESET, LyricStyle

# name -> (aspect w, aspect h, media-search orientation or None)
FORMATS = {
    "Landscape 16:9 (YouTube)": (16, 9, "horizontal"),
    "Portrait 9:16 (Reels / TikTok / Shorts)": (9, 16, "vertical"),
    "Square 1:1": (1, 1, None),
    "Portrait 4:5 (Instagram feed)": (4, 5, "vertical"),
}
QUALITIES = {"480p (fast draft)": 480, "720p (HD)": 720, "1080p (Full HD)": 1080, "1440p (2K)": 1440, "2160p (4K)": 2160}
CRF = {480: 27, 720: 23, 1080: 20, 1440: 19, 2160: 18}
LOGO_POSITIONS = ["Top left", "Top right", "Bottom left", "Bottom right"]


def frame_size(fmt: str, short_side: int) -> tuple:
    aw, ah, _ = FORMATS[fmt]
    if aw >= ah:
        h = short_side
        w = int(round(h * aw / ah / 2)) * 2
    else:
        w = short_side
        h = int(round(w * ah / aw / 2)) * 2
    return w + (w % 2), h + (h % 2)


@dataclass
class Scene:
    start: float
    end: float
    kind: str = "gradient"          # "image" | "video" | "gradient"
    path: str = ""
    query: str = ""                 # search phrase used for AI visuals
    source: str = "auto"            # "auto" | "ai" | "mine"
    credit: str = ""
    key: str = ""                   # identical stanzas (the chorus) share a key and therefore a background
    colors: List[str] = field(default_factory=lambda: ["#141E30", "#243B55"])
    label: str = ""                 # first words of the lyrics in this scene (for the table)

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)


@dataclass
class Project:
    audio: str = ""
    duration: float = 0.0
    title: str = ""
    artist: str = ""
    genre: str = ""
    mood: str = ""
    lyrics_text: str = ""
    lines: List[LyricLine] = field(default_factory=list)
    style: LyricStyle = field(default_factory=lambda: PRESETS[DEFAULT_PRESET].copy())
    scenes: List[Scene] = field(default_factory=list)
    fmt: str = "Landscape 16:9 (YouTube)"
    quality: str = "1080p (Full HD)"
    logo: str = ""
    logo_pos: str = "Top right"
    logo_size: float = 0.12
    credit: bool = False
    normalize_audio: bool = False
    language: str = "auto"

    def to_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}
        d["lines"] = [l.to_dict() for l in self.lines]
        d["style"] = self.style.to_dict()
        d["scenes"] = [dataclasses.asdict(s) for s in self.scenes]
        d["version"] = 1
        return d

    @staticmethod
    def from_dict(d: dict) -> "Project":
        p = Project()
        for f in dataclasses.fields(Project):
            if f.name in ("lines", "style", "scenes") or f.name not in d:
                continue
            setattr(p, f.name, d[f.name])
        p.lines = [LyricLine.from_dict(x) for x in d.get("lines", [])]
        p.style = LyricStyle.from_dict(d.get("style", {}))
        names = {f.name for f in dataclasses.fields(Scene)}
        p.scenes = [Scene(**{k: v for k, v in s.items() if k in names}) for s in d.get("scenes", [])]
        return p

    def save(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)

    @staticmethod
    def load(path: str) -> "Project":
        with open(path, "r", encoding="utf-8") as f:
            return Project.from_dict(json.load(f))

    @property
    def orientation(self) -> Optional[str]:
        return FORMATS[self.fmt][2]
