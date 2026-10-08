"""Professional fonts for lyric videos.

* 15 open-licence (SIL OFL) display fonts ship in ``assets/fonts`` so the render looks the same on every PC.
* Anything the artist drops into the user fonts folder (or picks with "Add font file") is available too.
* Installed system fonts can be typed in as well - libass uses them directly.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import List

from .paths import bundled_fonts_dir, user_fonts_dir

FONT_EXT = (".ttf", ".otf")


@dataclass(frozen=True)
class FontChoice:
    family: str          # name libass/Qt use to find it
    label: str           # shown in the picker
    mood: str            # one-line "when to use"
    bold: bool = False   # ASS bold flag (only for families that ship a Bold file, like Poppins)


# Curated, in the order an artist would reach for them.
CURATED: List[FontChoice] = [
    FontChoice("Poppins", "Poppins Bold", "Clean modern pop / afrobeats / R&B", True),
    FontChoice("Poppins ExtraBold", "Poppins ExtraBold", "Heavy karaoke look, very readable", False),
    FontChoice("Bebas Neue", "Bebas Neue", "Tall poster caps - hip-hop, drill, dancehall", False),
    FontChoice("Anton", "Anton", "Loud condensed headline - trap, street", False),
    FontChoice("Staatliches", "Staatliches", "Retro poster caps - reggae, funk", False),
    FontChoice("Archivo Black", "Archivo Black", "Solid grotesque - rap, rock", False),
    FontChoice("Alfa Slab One", "Alfa Slab One", "Chunky slab - gospel, country, vintage", False),
    FontChoice("Abril Fatface", "Abril Fatface", "High-contrast fashion serif - soul, ballads", False),
    FontChoice("DM Serif Display", "DM Serif Display", "Elegant serif - acoustic, cinematic", False),
    FontChoice("Great Vibes", "Great Vibes", "Formal calligraphy - wedding, worship, love songs", False),
    FontChoice("Lobster", "Lobster", "Friendly retro script - pop, feel-good", False),
    FontChoice("Pacifico", "Pacifico", "Surf-style script - summer, tropical", False),
    FontChoice("Righteous", "Righteous", "Futuristic rounded - EDM, synth", False),
    FontChoice("Bungee", "Bungee", "Signage block - dance, hype", False),
    FontChoice("Monoton", "Monoton", "Neon multi-line - nightlife, disco (use big, short lines)", False),
]


def _family_of(path: str) -> str:
    try:
        from PIL import ImageFont
        return ImageFont.truetype(path, 24).getname()[0]
    except Exception:  # noqa: BLE001
        return os.path.splitext(os.path.basename(path))[0].split("-")[0]


def font_files(folder: str) -> List[str]:
    if not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(FONT_EXT))


def user_fonts() -> List[FontChoice]:
    seen, out = set(), []
    for p in font_files(user_fonts_dir()):
        fam = _family_of(p)
        if fam not in seen:
            seen.add(fam)
            out.append(FontChoice(fam, f"{fam} (yours)", "Added by you"))
    return out


def catalog() -> List[FontChoice]:
    return CURATED + user_fonts()


def add_user_font(path: str) -> str:
    """Copy a .ttf/.otf into the user fonts folder; returns the family name."""
    if not path.lower().endswith(FONT_EXT):
        raise ValueError("Please choose a .ttf or .otf font file.")
    dest = os.path.join(user_fonts_dir(), os.path.basename(path))
    shutil.copyfile(path, dest)
    return _family_of(dest)


def prepare_fontsdir(workdir: str) -> str:
    """Copy bundled + user fonts into ``<workdir>/fonts`` and return that *relative* name.

    Running ffmpeg with cwd=workdir and ``fontsdir=fonts`` avoids every Windows path-escaping problem.
    """
    d = os.path.join(workdir, "fonts")
    os.makedirs(d, exist_ok=True)
    for src in font_files(bundled_fonts_dir()) + font_files(user_fonts_dir()):
        dst = os.path.join(d, os.path.basename(src))
        if not os.path.exists(dst):
            shutil.copyfile(src, dst)
    return "fonts"
