"""Orchestrates "give my lyrics their timing": offline speech recognition + alignment, or an even spread. No Qt."""
from __future__ import annotations

import os
from typing import Callable, Optional

from . import asr
from .lyrics import (align_lyrics, distribute_evenly, finalize_timing, lines_from_transcript, parse_lyrics)
from .mediautil import media_info
from .project import Project
from .scenes import plan_scenes, replan_keep_media


def load_audio(p: Project, path: str) -> float:
    info = media_info(path)
    if not info["has_audio"] or info["duration"] <= 0:
        raise RuntimeError("This file has no audio I can read. Choose an MP3, WAV, M4A, FLAC or a video file.")
    p.audio, p.duration = path, info["duration"]
    if not p.title:
        p.title = os.path.splitext(os.path.basename(path))[0].replace("_", " ").replace("-", " ").strip().title()
    return p.duration


def _hint(lyrics_text: str) -> str:
    """First words of the lyrics nudge Whisper toward the right spelling/vocabulary."""
    words = lyrics_text.replace("\n", " ").split()
    return " ".join(words[:45])


def auto_sync(p: Project, engine: asr.WhisperEngine, language: str = "auto",
              on_status: Callable[[str], None] = lambda s: None,
              on_progress: Callable[[float], None] = lambda v: None,
              should_cancel: Callable[[], bool] = lambda: False) -> dict:
    """Transcribe the song offline and fit the (pasted or recognised) lyrics to it. Returns a small report."""
    if not p.audio:
        raise RuntimeError("Choose the song first.")
    tr = asr.transcribe_file(p.audio, engine, language, _hint(p.lyrics_text), on_status, on_progress, should_cancel)
    heard = sum(len(s.words) for s in tr.segments)
    pasted = parse_lyrics(p.lyrics_text)
    if pasted:
        lines = align_lyrics(pasted, tr, p.duration)
        matched = _match_rate(pasted, tr)
        report = {"mode": "aligned", "heard": heard, "lines": len(lines), "match": matched}
    else:
        lines = lines_from_transcript(tr)
        report = {"mode": "transcribed", "heard": heard, "lines": len(lines), "match": 1.0}
    if not lines:
        raise RuntimeError("No singing or speech was recognised. Try 'Tap to sync', or a different language.")
    p.lines = finalize_timing(lines, p.duration)
    p.scenes = replan_keep_media(p.scenes, plan_scenes(p.lines, p.duration))
    return report


def _match_rate(lines, tr) -> float:
    """Share of lyric words that exactly matched a recognised word (a hint of how much to trust the timing)."""
    from difflib import SequenceMatcher
    from .lyrics import norm_word
    a = [norm_word(w) for l in lines for w in l.text.split() if norm_word(w)]
    b = [norm_word(w.text) for s in tr.segments for w in s.words if norm_word(w.text)]
    if not a or not b:
        return 0.0
    sm = SequenceMatcher(a=a, b=b, autojunk=False)
    return sum(m.size for m in sm.get_matching_blocks()) / len(a)


def spread_evenly(p: Project) -> None:
    """Fallback: no recognition possible. Lines are spread over the song; fix them in the timing table."""
    lines = parse_lyrics(p.lyrics_text)
    if not lines:
        raise RuntimeError("Paste the lyrics first.")
    lead = min(6.0, p.duration * 0.05)
    p.lines = finalize_timing(distribute_evenly(lines, max(p.duration - 2.0, 5.0), lead=lead), p.duration)
    p.scenes = replan_keep_media(p.scenes, plan_scenes(p.lines, p.duration))


def apply_tap_times(p: Project, starts: list, last_end: Optional[float] = None) -> None:
    """Tap-to-sync result: ``starts[i]`` is when the artist tapped for line i."""
    from .lyrics import even_words
    lines = p.lines or parse_lyrics(p.lyrics_text)
    n = min(len(lines), len(starts))
    for i in range(n):
        ln = lines[i]
        ln.start = starts[i]
        nxt = starts[i + 1] if i + 1 < n else None
        est = max(1.2, 0.38 * len(ln.text.split()))
        end = ln.start + est
        if nxt is not None:
            end = min(end, nxt - 0.05)
        elif last_end:
            end = max(end, last_end)
        ln.end = max(end, ln.start + 0.5)
        ln.words = even_words(ln.text, ln.start, ln.end)
    p.lines = finalize_timing(lines[:n], p.duration) + lines[n:]
    p.scenes = replan_keep_media(p.scenes, plan_scenes([l for l in p.lines if l.timed], p.duration))
