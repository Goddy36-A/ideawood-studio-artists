"""Plan background scenes from the timed lyrics: one scene per stanza / group of stanzas (8-24 s each).

Identical stanzas (the chorus coming back) get the same ``key`` so they share the same background - which is what
makes a lyric video feel designed instead of random. No Qt.
"""
from __future__ import annotations

import hashlib
from typing import List

from .lyrics import LyricLine, norm_word
from .project import Scene

PALETTES = [("#141E30", "#243B55"), ("#42275A", "#734B6D"), ("#0F2027", "#2C5364"), ("#B24592", "#F15F79"),
            ("#134E5E", "#71B280"), ("#232526", "#414345"), ("#3A1C71", "#D76D77"), ("#1D4350", "#A43931")]


def _key(lines: List[LyricLine]) -> str:
    words = " ".join(norm_word(w) for l in lines for w in l.text.split())
    return hashlib.md5(words.encode("utf-8")).hexdigest()[:10]


def _groups(lines: List[LyricLine], max_len: float) -> List[List[LyricLine]]:
    """Consecutive lines of the same stanza; stanzas longer than max_len are cut at line boundaries."""
    out: List[List[LyricLine]] = []
    for ln in lines:
        if out and out[-1][0].stanza == ln.stanza and ln.end - out[-1][0].start <= max_len:
            out[-1].append(ln)
        else:
            out.append([ln])
    return out


def plan_scenes(lines: List[LyricLine], duration: float, min_len: float = 8.0, max_len: float = 24.0) -> List[Scene]:
    timed = sorted((l for l in lines if l.timed), key=lambda l: l.start)
    if duration <= 0:
        duration = (timed[-1].end + 2.0) if timed else 30.0
    if not timed:
        n = max(1, int(round(duration / 15.0)))
        return [Scene(duration * i / n, duration * (i + 1) / n, key=f"t{i}", colors=list(PALETTES[i % len(PALETTES)]))
                for i in range(n)]
    groups: List[List[LyricLine]] = []
    for g in _groups(timed, max_len):
        span = g[-1].end - g[0].start
        if groups and span < min_len and (g[-1].end - groups[-1][0].start) <= max_len:
            groups[-1].extend(g)                       # too short on its own: join the previous scene
        elif groups and (groups[-1][-1].end - groups[-1][0].start) < min_len * 0.6 \
                and (g[-1].end - groups[-1][0].start) <= max_len:
            groups[-1].extend(g)
        else:
            groups.append(list(g))
    scenes: List[Scene] = []
    pal_idx: dict = {}
    for i, g in enumerate(groups):
        k = _key(g)
        pal_idx.setdefault(k, len(pal_idx))
        a = 0.0 if i == 0 else (groups[i - 1][-1].end + g[0].start) / 2
        b = duration if i == len(groups) - 1 else (g[-1].end + groups[i + 1][0].start) / 2
        label = " ".join(g[0].text.split()[:5])
        scenes.append(Scene(a, max(b, a + 0.5), key=k, label=label,
                            colors=list(PALETTES[pal_idx[k] % len(PALETTES)])))
    return scenes


def replan_keep_media(old: List[Scene], new: List[Scene]) -> List[Scene]:
    """After lyric edits: keep pictures/clips for scenes whose lyrics did not change (same key), else by position."""
    by_key = {s.key: s for s in old if s.kind != "gradient"}
    for i, s in enumerate(new):
        src = by_key.get(s.key) or (old[i] if i < len(old) and old[i].kind != "gradient" and
                                    abs(old[i].start - s.start) < 3.0 else None)
        if src:
            s.kind, s.path, s.query, s.source, s.credit = src.kind, src.path, src.query, src.source, src.credit
            s.toon = src.toon
    return new


def share_by_key(scenes: List[Scene]):
    """Make repeated stanzas use the first occurrence's media."""
    first = {}
    for s in scenes:
        if s.kind != "gradient" and s.key not in first:
            first[s.key] = s
    for s in scenes:
        f = first.get(s.key)
        if f and s.kind == "gradient" and s is not f:
            s.kind, s.path, s.query, s.source, s.credit = f.kind, f.path, f.query, f.source, f.credit
            s.toon = f.toon
