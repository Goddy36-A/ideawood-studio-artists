"""Lyrics: parse pasted text, line them up with the audio, edit timings, import/export LRC and SRT.

How timing works
  * If the artist pastes lyrics, the audio is transcribed offline (whisper.cpp, word timestamps) and every lyric
    word is matched to the recognised words with a sequence alignment (difflib). Words the recogniser got wrong,
    missed, or that are in a language Whisper does not know are interpolated between the matched neighbours, so
    the artist's *spelling* is always what appears on screen and only the *timing* comes from the audio.
  * Without pasted lyrics, the transcript itself becomes the lyrics (one line per phrase) to be edited.
  * LRC files (``[01:23.45] text``) can be imported/exported; the timing table in the app edits everything.

No Qt imports: unit-testable.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .asr import Cue, Transcript, Word

SECTION_RE = re.compile(r"^\s*[\[\(]\s*(verse|chorus|hook|bridge|intro|outro|pre[- ]?chorus|refrain|interlude|"
                        r"break|drop|rap|spoken|ad[- ]?lib|instrumental)[^\]\)]*[\]\)]\s*$", re.I)
_NORM = re.compile(r"[^\w']+", re.UNICODE)
MAX_LINE_CHARS = 60


@dataclass
class LyricLine:
    text: str
    start: float = -1.0                       # < 0 means "not timed yet"
    end: float = -1.0
    words: List[Word] = field(default_factory=list)
    section: str = ""                         # e.g. "Chorus" - from a [Chorus] header
    stanza: int = 0                           # blank-line separated block number

    @property
    def timed(self) -> bool:
        return self.start >= 0 and self.end > self.start

    def to_dict(self) -> dict:
        return {"text": self.text, "start": round(self.start, 3), "end": round(self.end, 3),
                "section": self.section, "stanza": self.stanza,
                "words": [[round(w.start, 3), round(w.end, 3), w.text] for w in self.words]}

    @staticmethod
    def from_dict(d: dict) -> "LyricLine":
        return LyricLine(d.get("text", ""), float(d.get("start", -1)), float(d.get("end", -1)),
                         [Word(float(a), float(b), t) for a, b, t in d.get("words", [])],
                         d.get("section", ""), int(d.get("stanza", 0)))


def norm_word(w: str) -> str:
    return _NORM.sub("", w.lower().replace("’", "'"))


# --------------------------------------------------------------------------- parsing
def parse_lyrics(text: str) -> List[LyricLine]:
    """Pasted lyrics -> lines. Blank line = new stanza; ``[Chorus]`` style headers label the lines after them
    (and are not shown on screen). Very long lines are split at the nearest comma/space."""
    lines: List[LyricLine] = []
    stanza, section, pending_blank = 0, "", False
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        s = raw.strip()
        if not s:
            pending_blank = True
            continue
        if SECTION_RE.match(s):
            section = re.sub(r"[\[\]\(\)]", "", s).strip().title()
            pending_blank = True
            continue
        if pending_blank and lines:
            stanza += 1
        pending_blank = False
        for piece in split_long(s):
            lines.append(LyricLine(piece, section=section, stanza=stanza))
    return lines


def split_long(s: str, limit: int = MAX_LINE_CHARS) -> List[str]:
    if len(s) <= limit:
        return [s]
    cut = max((m.end() for m in re.finditer(r"[,;:–—]\s", s[:limit + 1])), default=0)
    if cut < limit * 0.4:
        cut = s.rfind(" ", 0, limit)
    if cut <= 0:
        cut = limit
    return [s[:cut].strip()] + split_long(s[cut:].strip(), limit)


# --------------------------------------------------------------------------- alignment
def _flatten(tr: Transcript) -> List[Word]:
    out: List[Word] = []
    for seg in tr.segments:
        out.extend(w for w in seg.words if norm_word(w.text))
    return out


def align_lyrics(lines: List[LyricLine], tr: Transcript, audio_duration: float = 0.0) -> List[LyricLine]:
    """Give every lyric line (and word) a time, using the recognised words as anchors."""
    heard = _flatten(tr)
    toks: List[tuple] = []                    # (line index, word index in line, text)
    for li, ln in enumerate(lines):
        for wi, w in enumerate(ln.text.split()):
            if norm_word(w):
                toks.append((li, wi, w))
    if not toks:
        return lines
    if not heard:
        return distribute_evenly(lines, audio_duration or 60.0)

    a = [norm_word(t[2]) for t in toks]
    b = [norm_word(w.text) for w in heard]
    t0: List[Optional[float]] = [None] * len(toks)
    t1: List[Optional[float]] = [None] * len(toks)
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            t0[blk.a + k], t1[blk.a + k] = heard[blk.b + k].start, heard[blk.b + k].end
    # fuzzy rescue inside the gaps between exact blocks (ASR spells things its own way)
    _fuzzy_fill(a, b, heard, t0, t1, sm.get_matching_blocks())
    _interpolate(t0, t1, audio_duration or (heard[-1].end + 1.0), heard[0].start)

    per_line: dict = {}
    for k, (li, wi, text) in enumerate(toks):
        per_line.setdefault(li, []).append(Word(t0[k], max(t1[k], t0[k] + 0.04), text))
    for li, ln in enumerate(lines):
        ws = per_line.get(li)
        if not ws:
            continue
        ln.words = ws
        ln.start, ln.end = ws[0].start, ws[-1].end
    return finalize_timing(lines, audio_duration)


def _fuzzy_fill(a, b, heard, t0, t1, blocks):
    """Inside the gaps between exact matches, pair up words that are *nearly* equal (ASR spells them its own way)."""
    for k, blk in enumerate(blocks):
        a_lo = 0 if k == 0 else blocks[k - 1].a + blocks[k - 1].size
        b_lo = 0 if k == 0 else blocks[k - 1].b + blocks[k - 1].size
        gap_b = list(range(b_lo, blk.b))
        if not gap_b or blk.a <= a_lo:
            continue
        j0 = 0
        for i in range(a_lo, blk.a):
            best, best_j = 0.0, -1
            for j in range(j0, len(gap_b)):
                if a[i] and b[gap_b[j]]:
                    r = difflib.SequenceMatcher(None, a[i], b[gap_b[j]]).ratio()
                    if r > best:
                        best, best_j = r, j
            if best >= 0.6:
                t0[i], t1[i] = heard[gap_b[best_j]].start, heard[gap_b[best_j]].end
                j0 = best_j + 1


def _interpolate(t0, t1, duration, first_start):
    n = len(t0)
    known = [i for i in range(n) if t0[i] is not None]
    if not known:
        step = duration / n
        for i in range(n):
            t0[i], t1[i] = i * step, (i + 1) * step * 0.95
        return
    for i in range(0, known[0]):                      # before the first anchor
        span = max(t0[known[0]] - 0.0, 0.5)
        t0[i] = max(0.0, t0[known[0]] - span * (known[0] - i) / (known[0] + 1))
        t1[i] = t0[i] + span / (known[0] + 1) * 0.9
    for a_i, b_i in zip(known, known[1:]):            # between anchors
        gap = b_i - a_i - 1
        if gap <= 0:
            continue
        lo, hi = t1[a_i], t0[b_i]
        if hi <= lo:
            hi = lo + 0.25 * gap
        step = (hi - lo) / gap
        for k in range(gap):
            t0[a_i + 1 + k] = lo + step * k
            t1[a_i + 1 + k] = lo + step * (k + 0.9)
    last = known[-1]                                  # after the last anchor
    tail = n - last - 1
    for k in range(tail):
        t0[last + 1 + k] = t1[last] + 0.3 * k
        t1[last + 1 + k] = t0[last + 1 + k] + 0.3


def distribute_evenly(lines: List[LyricLine], duration: float, lead: float = 0.0) -> List[LyricLine]:
    """Last resort (no recognised words): spread lines over the song by length. The artist then fixes the table."""
    weights = [max(len(l.text), 4) for l in lines]
    total, t = sum(weights), lead
    span = max(duration - lead, 1.0)
    for ln, wt in zip(lines, weights):
        d = span * wt / total
        ln.start, ln.end = t, t + d * 0.95
        ln.words = even_words(ln.text, ln.start, ln.end)
        t += d
    return lines


def even_words(text: str, start: float, end: float) -> List[Word]:
    ws = text.split()
    if not ws:
        return []
    total = sum(max(len(w), 1) for w in ws)
    t, out = start, []
    for w in ws:
        d = (end - start) * max(len(w), 1) / total
        out.append(Word(t, t + d, w))
        t += d
    return out


def lines_from_transcript(tr: Transcript, max_chars: int = 46) -> List[LyricLine]:
    """No lyrics pasted: one line per recognised phrase (split when long)."""
    out: List[LyricLine] = []
    stanza, last_end = 0, 0.0
    for seg in tr.segments:
        words = [w for w in seg.words if w.text.strip()] or even_words(seg.text, seg.start, seg.end)
        if not words:
            continue
        if out and words[0].start - last_end > 4.0:
            stanza += 1
        cur: List[Word] = []
        for w in words:
            cur.append(w)
            if len(" ".join(x.text for x in cur)) >= max_chars:
                out.append(_line_from_words(cur, stanza))
                cur = []
        if cur:
            out.append(_line_from_words(cur, stanza))
        last_end = words[-1].end
    return finalize_timing(out)


def _line_from_words(ws: List[Word], stanza: int) -> LyricLine:
    return LyricLine(" ".join(w.text for w in ws), ws[0].start, ws[-1].end, list(ws), stanza=stanza)


# --------------------------------------------------------------------------- timing hygiene
def finalize_timing(lines: List[LyricLine], duration: float = 0.0, min_dur: float = 0.6,
                    tail: float = 0.0) -> List[LyricLine]:
    """Keep lines in order, never overlapping, at least ``min_dur`` long and inside the song."""
    timed = [l for l in lines if l.start >= 0]
    prev_end = 0.0
    for i, ln in enumerate(timed):
        ln.start = max(ln.start, prev_end if ln.start < prev_end else ln.start)
        nxt = timed[i + 1].start if i + 1 < len(timed) else None
        ln.end = max(ln.end, ln.start + min_dur)
        if nxt is not None and nxt >= 0 and ln.end > nxt:
            ln.end = max(ln.start + 0.2, nxt - 0.02)
        if duration:
            ln.end = min(ln.end, duration)
            ln.start = min(ln.start, max(duration - 0.2, 0))
        prev_end = ln.end
        _fit_words(ln)
    return lines


def _fit_words(ln: LyricLine):
    """Keep per-word times inside the line and in order (the karaoke fill follows them)."""
    ws = ln.words
    if not ws:
        return
    prev = ln.start
    for w in ws:
        w.start = min(max(w.start, prev), ln.end - 0.02)
        w.end = min(max(w.end, w.start + 0.03), ln.end)
        prev = w.start
    for i in range(len(ws) - 1):                     # a word lasts until the next one starts (smooth sweep)
        ws[i].end = max(ws[i].start + 0.03, min(ws[i].end if ws[i].end > ws[i].start else ws[i + 1].start,
                                                ws[i + 1].start))
    ws[-1].end = max(ws[-1].end, min(ln.end, ws[-1].start + 0.3))


def retext_line(ln: LyricLine, text: str):
    """The artist edited the text in the table: keep the timing, re-spread the words over the same span."""
    ln.text = text.strip()
    if ln.timed:
        ln.words = even_words(ln.text, ln.start, ln.end)


def set_times(ln: LyricLine, start: float, end: float):
    """Move/resize a line (words are scaled with it)."""
    if ln.words and ln.timed and ln.end > ln.start:
        k = (end - start) / (ln.end - ln.start)
        for w in ln.words:
            w.start = start + (w.start - ln.start) * k
            w.end = start + (w.end - ln.start) * k
    ln.start, ln.end = start, end
    if not ln.words:
        ln.words = even_words(ln.text, start, end)


def shift_all(lines: List[LyricLine], delta: float):
    for ln in lines:
        if ln.start < 0:
            continue
        ln.start, ln.end = max(0.0, ln.start + delta), max(0.0, ln.end + delta)
        for w in ln.words:
            w.start, w.end = max(0.0, w.start + delta), max(0.0, w.end + delta)


def merge_with_next(lines: List[LyricLine], i: int):
    if i + 1 >= len(lines):
        return
    a, b = lines[i], lines[i + 1]
    a.text = f"{a.text} {b.text}".strip()
    a.words = a.words + b.words
    if b.end > 0:
        a.end = b.end
    del lines[i + 1]


def split_line(lines: List[LyricLine], i: int, at_word: int):
    ln = lines[i]
    ws = ln.text.split()
    if not (0 < at_word < len(ws)):
        return
    if ln.timed and len(ln.words) == len(ws):
        a_words, b_words = ln.words[:at_word], ln.words[at_word:]
    else:
        a_words = b_words = []
    first = LyricLine(" ".join(ws[:at_word]), ln.start, ln.end, a_words, ln.section, ln.stanza)
    second = LyricLine(" ".join(ws[at_word:]), ln.start, ln.end, b_words, ln.section, ln.stanza)
    if ln.timed:
        mid = a_words[-1].end if a_words else (ln.start + (ln.end - ln.start) * at_word / len(ws))
        first.end = max(mid, ln.start + 0.2)
        second.start = min(max(b_words[0].start if b_words else mid, first.end), ln.end - 0.1)
        if not a_words:
            first.words = even_words(first.text, first.start, first.end)
            second.words = even_words(second.text, second.start, second.end)
    lines[i:i + 1] = [first, second]


def gaps(lines: List[LyricLine], duration: float):
    """[(start, end)] of the quiet stretches (intro, solos, outro) - used for instrumental dots / title card."""
    out, t = [], 0.0
    for ln in sorted((l for l in lines if l.timed), key=lambda l: l.start):
        if ln.start > t:
            out.append((t, ln.start))
        t = max(t, ln.end)
    if duration > t:
        out.append((t, duration))
    return out


# --------------------------------------------------------------------------- LRC / SRT
_LRC_TS = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_LRC_WORD = re.compile(r"<(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?>")


def _ts_to_s(m) -> float:
    frac = (m.group(3) or "0")
    return int(m.group(1)) * 60 + int(m.group(2)) + int(frac) / (10 ** len(frac))


def parse_lrc(text: str, duration: float = 0.0) -> List[LyricLine]:
    """Standard LRC (and enhanced LRC with <mm:ss.xx> word times). Multiple timestamps on a line are supported."""
    raw: List[tuple] = []
    for row in (text or "").splitlines():
        stamps = list(_LRC_TS.finditer(row))
        if not stamps:
            continue
        body = row[stamps[-1].end():].strip()
        wtimes = [(_ts_to_s(m), m.start()) for m in _LRC_WORD.finditer(body)]
        clean = _LRC_WORD.sub("", body).strip()
        if not clean:
            continue
        for st in stamps:
            raw.append((_ts_to_s(st), clean, wtimes))
    raw.sort(key=lambda r: r[0])
    out: List[LyricLine] = []
    for i, (t, txt, wt) in enumerate(raw):
        end = raw[i + 1][0] if i + 1 < len(raw) else (duration or t + 4.0)
        ln = LyricLine(txt, t, max(min(end - 0.05, t + 8.0), t + 0.5))
        ws = txt.split()
        if wt and len(wt) == len(ws):
            ln.words = [Word(wt[k][0], (wt[k + 1][0] if k + 1 < len(wt) else ln.end), ws[k]) for k in range(len(ws))]
        else:
            ln.words = even_words(txt, ln.start, ln.end)
        out.append(ln)
    stanza = 0
    for i in range(1, len(out)):
        if out[i].start - out[i - 1].end > 3.0:
            stanza += 1
        out[i].stanza = stanza
    return finalize_timing(out, duration)


def to_lrc(lines: List[LyricLine], title: str = "", artist: str = "", enhanced: bool = False) -> str:
    def stamp(t, ang="["):
        m, s = divmod(max(t, 0.0), 60)
        close = "]" if ang == "[" else ">"
        return f"{ang}{int(m):02d}:{s:05.2f}{close}"

    head = []
    if title:
        head.append(f"[ti:{title}]")
    if artist:
        head.append(f"[ar:{artist}]")
    head.append("[by:Ideawood Studio for Artists]")
    body = []
    for ln in lines:
        if not ln.timed:
            continue
        if enhanced and ln.words:
            body.append(stamp(ln.start) + " " + " ".join(f"{stamp(w.start, '<')}{w.text}" for w in ln.words))
        else:
            body.append(f"{stamp(ln.start)}{ln.text}")
    return "\n".join(head + body) + "\n"


def to_cues(lines: List[LyricLine]) -> List[Cue]:
    return [Cue(l.start, l.end, l.text, list(l.words)) for l in lines if l.timed]


def lines_to_text(lines: List[LyricLine]) -> str:
    """Back to pasteable lyrics (blank line between stanzas, [Section] headers kept)."""
    out, last_stanza, last_section = [], None, ""
    for ln in lines:
        if last_stanza is not None and ln.stanza != last_stanza:
            out.append("")
        if ln.section and ln.section != last_section and (last_stanza is None or ln.stanza != last_stanza):
            out.append(f"[{ln.section}]")
        out.append(ln.text)
        last_stanza, last_section = ln.stanza, ln.section
    return "\n".join(out)
