"""Look presets for the lyric text and the background treatment. Plain data, JSON-serialisable, no Qt."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

GRADES = {
    "None": "",
    "Cinematic": "colorbalance=rs=-0.06:bs=0.07:rh=0.07:bh=-0.07,eq=contrast=1.08:saturation=1.12",
    "Warm film": "colorbalance=rs=0.07:bs=-0.07:rm=0.05:bm=-0.05,eq=saturation=1.1",
    "Cool night": "colorbalance=rs=-0.06:bs=0.09:rm=-0.04:bm=0.06,eq=contrast=1.05",
    "Vibrant": "eq=saturation=1.4:contrast=1.08",
    "Faded vintage": "curves=preset=vintage",
    "Black & white": "hue=s=0,eq=contrast=1.12",
}
TRANSITIONS = ["fade", "dissolve", "fadeblack", "smoothleft", "slideleft", "wipeleft", "circleopen", "radial", "none"]
ANIMATIONS = ["fade", "pop", "slide", "blur", "none"]
HIGHLIGHTS = ["sweep", "word", "none"]
VIZ_MODES = ["none", "wave", "bars"]


@dataclass
class LyricStyle:
    name: str = "Karaoke Bold"
    # --- text
    font: str = "Poppins"
    bold: bool = True
    italic: bool = False
    uppercase: bool = False
    size: float = 0.075            # fraction of min(height, 0.9 * width)
    spacing: float = 0.0           # letter spacing in px at 1080p
    pos_y: float = 0.5             # centre of the lyric block, 0 = top .. 1 = bottom
    max_chars: int = 0             # 0 = automatic wrap for the video shape
    # --- colours (#RRGGBB)
    color_unsung: str = "#FFFFFF"
    color_sung: str = "#FFD84D"
    outline_color: str = "#000000"
    outline: float = 0.05          # fraction of font size
    shadow: float = 0.03
    glow: bool = False
    glow_color: str = "#00E5FF"
    box: bool = False
    box_color: str = "#000000"
    box_alpha: float = 0.5
    # --- motion
    anim_in: str = "fade"
    anim_ms: int = 280
    highlight: str = "sweep"
    show_next: bool = True
    next_alpha: float = 0.55
    instrumental_dots: bool = True
    # --- background treatment
    bg_dim: float = 0.30
    bg_blur: float = 0.0
    vignette: bool = True
    grain: float = 0.0
    grade: str = "Cinematic"
    ken_burns: bool = True
    transition: str = "fade"
    transition_sec: float = 1.0
    viz: str = "none"
    viz_color: str = "#FFFFFF"
    # --- title card
    title_card: bool = True
    title_sec: float = 4.0

    def copy(self) -> "LyricStyle":
        return dataclasses.replace(self)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "LyricStyle":
        names = {f.name for f in dataclasses.fields(LyricStyle)}
        return LyricStyle(**{k: v for k, v in (d or {}).items() if k in names})


def _p(**kw) -> LyricStyle:
    return LyricStyle(**kw)


PRESETS = {
    "Karaoke Bold": _p(name="Karaoke Bold"),
    "Neon Night": _p(name="Neon Night", font="Righteous", bold=False, size=0.08, color_unsung="#EAFBFF",
                     color_sung="#FF3DCB", outline=0.03, shadow=0.0, glow=True, glow_color="#18E6FF",
                     anim_in="blur", highlight="sweep", bg_dim=0.45, grade="Cool night", viz="bars",
                     viz_color="#18E6FF", grain=0.03),
    "Cinematic Gold": _p(name="Cinematic Gold", font="DM Serif Display", bold=False, size=0.07,
                         color_unsung="#F4EBDD", color_sung="#F2C14E", outline=0.035, shadow=0.05,
                         anim_in="fade", anim_ms=600, highlight="sweep", bg_dim=0.40, grade="Warm film",
                         transition="fadeblack", transition_sec=1.4, grain=0.04, pos_y=0.78),
    "Street Poster": _p(name="Street Poster", font="Anton", bold=False, uppercase=True, size=0.105,
                        color_unsung="#FFFFFF", color_sung="#FF2E2E", outline=0.04, shadow=0.0, anim_in="pop",
                        anim_ms=200, highlight="word", show_next=False, bg_dim=0.5, grade="Black & white",
                        transition="wipeleft", transition_sec=0.5, grain=0.06),
    "Soul & Script": _p(name="Soul & Script", font="Great Vibes", bold=False, size=0.13,
                        color_unsung="#FFF6EE", color_sung="#FFB3C7", outline=0.03, shadow=0.05, glow=True,
                        glow_color="#FF8FB1", anim_in="fade", anim_ms=700, highlight="sweep",
                        bg_dim=0.35, grade="Warm film", transition="dissolve", transition_sec=1.6),
    "Retro Tape": _p(name="Retro Tape", font="Bungee", bold=False, size=0.07, color_unsung="#FFF1D0",
                     color_sung="#FF8A3D", outline=0.05, shadow=0.06, anim_in="slide", highlight="word",
                     bg_dim=0.35, grade="Faded vintage", grain=0.08, transition="slideleft"),
    "Clean Minimal": _p(name="Clean Minimal", font="Poppins", bold=False, size=0.052, color_unsung="#FFFFFF",
                        color_sung="#FFFFFF", outline=0.0, shadow=0.0, box=True, box_alpha=0.45,
                        anim_in="fade", highlight="none", show_next=False, pos_y=0.86, bg_dim=0.15,
                        grade="None", vignette=False, title_card=False),
    "Reggae Sunrise": _p(name="Reggae Sunrise", font="Staatliches", bold=False, size=0.10, uppercase=True,
                         color_unsung="#FFF3C4", color_sung="#3DDC84", outline=0.045, shadow=0.04,
                         anim_in="pop", anim_ms=240, highlight="sweep", bg_dim=0.32, grade="Vibrant",
                         transition="smoothleft", transition_sec=1.2, grain=0.03),
}
DEFAULT_PRESET = "Karaoke Bold"
