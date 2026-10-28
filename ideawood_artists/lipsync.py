"""Mouth timing for lip-sync, powered by Rhubarb Lip Sync (bundled in the EXE under bin/rhubarb/). No Qt.

Rhubarb listens to the audio and returns which mouth shape is needed when, using the standard Preston Blair set:
A closed (M B P) | B slightly open, teeth together (K S T EE) | C open (EH AE) | D wide open (AA) |
E rounded (AO ER) | F puckered (OO W) | G teeth on lip (F V) | H tongue up (L) | X resting.
Everything runs on this PC, so it costs no AI credits. It works best on clear vocals; a full mix with loud music is
less accurate. Passing the lyrics as the "dialog" makes it noticeably better.
"""
from __future__ import annotations

import bisect
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import List, Sequence, Tuple

from .paths import find_tool, no_window_flags

SHAPES = "ABCDEFGHX"
MEANING = {"A": "closed (M, B, P)", "B": "teeth together (K, S, T, EE)", "C": "open (EH, AE)", "D": "wide open (AA)",
           "E": "rounded (AO, ER)", "F": "puckered (OO, W)", "G": "teeth on lip (F, V)", "H": "tongue up (L)",
           "X": "resting"}
CUES = "cues.json"

Cue = Tuple[float, float, str]


def find_rhubarb() -> str:
    exe = "rhubarb" + (".exe" if os.name == "nt" else "")
    cands = []
    env = os.environ.get("IDEAWOOD_RHUBARB")
    if env:
        cands.append(env)
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cands.append(os.path.join(base, "bin", "rhubarb", exe))
    cands.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "bin", "rhubarb", exe))
    cands.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "rhubarb", exe))
    for c in cands:
        if os.path.isfile(c):
            return c
    found = shutil.which("rhubarb")
    if found:
        return found
    raise FileNotFoundError("Rhubarb Lip Sync was not found. It is bundled in the Windows app; when running from "
                            "source put it in bin/rhubarb/ or on PATH.")


def parse_cues(text: str) -> List[Cue]:
    """Rhubarb's ``-f json`` output -> [(start, end, shape)] sorted, with unknown shapes treated as resting."""
    d = json.loads(text)
    out = []
    for c in d.get("mouthCues", []):
        v = str(c.get("value", "X")).upper()
        out.append((float(c["start"]), float(c["end"]), v if v in SHAPES else "X"))
    out.sort(key=lambda c: c[0])
    return out


def shape_at(cues: Sequence[Cue], t: float) -> str:
    """The mouth shape to show at time ``t`` (seconds from the start of the analysed audio)."""
    if not cues or t < 0:
        return "X"
    i = bisect.bisect_right([c[0] for c in cues], t) - 1
    if i < 0:
        return "X"
    return cues[i][2] if t < cues[i][1] + 0.02 else "X"


def analyze(audio: str, start: float, duration: float, dialog: str = "", timeout: int = 900) -> List[Cue]:
    """Cue list for ``audio[start : start + duration]``; times are relative to ``start``."""
    rb = find_rhubarb()
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "scene.wav")
        r = subprocess.run([find_tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{max(0.0, start):.3f}", "-t",
                            f"{max(0.1, duration):.3f}", "-i", audio, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav],
                           capture_output=True, creationflags=no_window_flags(), timeout=timeout)
        if r.returncode != 0 or not os.path.isfile(wav):
            raise RuntimeError("Could not read the song for lip-sync.\n" + r.stderr.decode("utf-8", "replace")[-300:])
        out = os.path.join(td, "cues.json")
        cmd = [rb, "-f", "json", "-q", "-o", out, wav]
        if dialog.strip():
            dlg = os.path.join(td, "dialog.txt")
            with open(dlg, "w", encoding="utf-8") as f:
                f.write(dialog.strip())
            cmd += ["--dialogFile", dlg]
        r = subprocess.run(cmd, capture_output=True, creationflags=no_window_flags(), timeout=timeout)
        if r.returncode != 0 or not os.path.isfile(out):
            raise RuntimeError("Lip-sync analysis failed.\n" + r.stderr.decode("utf-8", "replace")[-300:])
        with open(out, "r", encoding="utf-8") as f:
            return parse_cues(f.read())


def save_cues(folder: str, cues: Sequence[Cue], start: float, duration: float):
    with open(os.path.join(folder, CUES), "w", encoding="utf-8") as f:
        json.dump({"start": start, "duration": duration, "cues": [list(c) for c in cues]}, f)


def load_cues(folder: str) -> List[Cue]:
    try:
        with open(os.path.join(folder, CUES), "r", encoding="utf-8") as f:
            return [(float(a), float(b), str(v)) for a, b, v in json.load(f).get("cues", [])]
    except (OSError, ValueError):
        return []
