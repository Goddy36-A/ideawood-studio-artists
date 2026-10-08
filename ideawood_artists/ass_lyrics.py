"""Turns timed lyric lines + a LyricStyle into an ASS script (libass renders it inside ffmpeg).

Why ASS: it gives broadcast-quality text (outlines, glow, karaoke sweep fill, per-word timing, animations) while
rendering in one ffmpeg pass - no per-frame Python drawing, so it is fast and the GUI stays responsive.

Layout of the script
  Main    the line being sung; words fill from ``color_unsung`` to ``color_sung`` as they are sung (\\kf sweep or \\k snap)
  Next    the following line, smaller and dimmed, so singers/viewers can read ahead
  Dots    "● ● ●" countdown that lights up before the vocals return after a long instrumental gap
  Title / Artist   opening title card (only when the vocals start late enough for it to fit)
  Credit  optional small line at the end
No Qt imports.
"""
from __future__ import annotations

import math
from typing import List

from .asr import _ass_escape, _ass_time
from .lyrics import LyricLine, even_words, gaps
from .styles import LyricStyle

READABLE = {"Poppins", "Poppins ExtraBold", "Archivo Black", "DM Serif Display", "Righteous", "Abril Fatface",
            "Alfa Slab One"}
LINE_H = 1.22          # line height as a multiple of the font size
LEAD = 0.10            # a line appears this long before its first word
HOLD = 0.45            # and lingers this long after its last word (when there is room)


# average glyph width as a fraction of the font size (used only to decide where lines wrap)
FONT_WIDTH = {"Anton": 0.44, "Bebas Neue": 0.40, "Staatliches": 0.44, "Great Vibes": 0.36, "Lobster": 0.50,
              "Pacifico": 0.56, "Monoton": 0.72, "Bungee": 0.68, "Archivo Black": 0.62, "Alfa Slab One": 0.66,
              "Righteous": 0.56, "Poppins": 0.58, "Poppins ExtraBold": 0.60, "Abril Fatface": 0.52,
              "DM Serif Display": 0.50}
CAPS_FONTS = {"Anton", "Bebas Neue", "Staatliches", "Bungee", "Monoton"}


def font_px(w: int, h: int, size: float) -> int:
    base = min(h, w * (0.9 if w >= h else 1.15))       # portrait videos get relatively bigger text
    return max(18, int(base * size))


def auto_max_chars(w: int, h: int, fs: int, uppercase: bool = False, font: str = "") -> int:
    per_char = fs * FONT_WIDTH.get(font, 0.56)
    if uppercase and font not in CAPS_FONTS:
        per_char *= 1.12
    return int(max(12, min(48, (w * 0.84) / per_char)))


def bgr(hex_color: str) -> str:
    c = (hex_color or "#FFFFFF").lstrip("#")
    c = (c + "000000")[:6]
    return c[4:6] + c[2:4] + c[0:2]


def ass_color(hex_color: str, alpha: float = 0.0) -> str:
    """&HAABBGGRR - alpha 0 = opaque, 1 = invisible."""
    return f"&H{int(max(0, min(1, alpha)) * 255):02X}{bgr(hex_color)}"


def tag_color(n: int, hex_color: str) -> str:
    return f"\\{n}c&H{bgr(hex_color)}&"


def wrap_balanced(words: List[str], max_chars: int, max_lines: int = 3) -> List[int]:
    """Indices of the words *after which* a line break goes, giving evenly sized lines."""
    text_len = sum(len(w) for w in words) + max(len(words) - 1, 0)
    n_lines = min(max_lines, max(1, math.ceil(text_len / max_chars)))
    if n_lines == 1:
        return []
    target = text_len / n_lines
    breaks, cur = [], 0
    for i, w in enumerate(words[:-1]):
        cur += len(w) + (1 if cur else 0)
        remaining_lines = n_lines - len(breaks) - 1
        if remaining_lines > 0 and cur >= target * 0.92 and (len(words) - i - 1) >= remaining_lines:
            breaks.append(i)
            cur = 0
        if len(breaks) == n_lines - 1:
            break
    return breaks


class _Geom:
    def __init__(self, w: int, h: int, st: LyricStyle):
        self.w, self.h, self.st = w, h, st
        self.fs = font_px(w, h, st.size)
        self.max_chars = st.max_chars or auto_max_chars(w, h, self.fs, st.uppercase, st.font)
        self.x = w // 2
        self.scale = h / 1080.0

    def block_h(self, n_lines: int, fs=None) -> float:
        return n_lines * (fs or self.fs) * LINE_H

    def top_y(self, n_lines: int) -> float:
        """Top of the lyric block so that it is centred on pos_y (clamped inside the safe area)."""
        bh = self.block_h(n_lines)
        y = self.st.pos_y * self.h - bh / 2
        return max(self.h * 0.04, min(y, self.h * 0.96 - bh))


def _prepare(line: LyricLine, st: LyricStyle, g: _Geom):
    """-> (tokens, break_after_index_set, word_times[(start, end)])"""
    text = line.text.upper() if st.uppercase else line.text
    toks = text.split()
    if not toks:
        return [], set(), []
    ws = line.words if len(line.words) == len(toks) else even_words(line.text, line.start, line.end)
    times = [(w.start, w.end) for w in ws]
    return toks, set(wrap_balanced(toks, g.max_chars)), times


def _anim_tags(st: LyricStyle, x: int, y: float, fs: int, fade_out_ms: int) -> str:
    ms = max(0, int(st.anim_ms))
    base = f"\\an8\\pos({x},{y:.0f})"
    if st.anim_in == "none":
        return base
    fad = f"\\fad({ms},{fade_out_ms})"
    if st.anim_in == "pop":
        return base + fad + f"\\fscx82\\fscy82\\t(0,{ms},\\fscx100\\fscy100)"
    if st.anim_in == "slide":
        return f"\\an8\\move({x},{y + fs * 0.55:.0f},{x},{y:.0f},0,{ms})" + fad
    if st.anim_in == "blur":
        return base + fad + f"\\blur14\\t(0,{ms},\\blur0)"
    return base + fad


def _karaoke_text(toks, breaks, times, st: LyricStyle, show_start: float) -> str:
    """Words with \\kf (sweep) / \\k (snap) timing, or plain text when highlighting is off."""
    if st.highlight == "none":
        out = ""
        for i, t in enumerate(toks):
            out += _ass_escape(t) + ("\\N" if i in breaks else (" " if i < len(toks) - 1 else ""))
        return out
    tag = "\\kf" if st.highlight == "sweep" else "\\k"
    out, cursor = "", show_start
    for i, t in enumerate(toks):
        s, e = times[i]
        s = max(s, cursor)
        pre = int(round((s - cursor) * 100))
        dur = max(1, int(round(max(e - s, 0.05) * 100)))
        piece = (f"{{\\k{pre}}}" if pre > 0 else "") + f"{{{tag}{dur}}}" + _ass_escape(t)
        sep = "\\N" if i in breaks else (" " if i < len(toks) - 1 else "")
        out += piece + sep
        cursor = s + dur / 100.0
    return out


def _style_row(name: str, st: LyricStyle, fs: int, g: _Geom, *, unsung: str, sung: str, outline_px: float,
               shadow_px: float, box: bool, bold=None, italic=None, font=None) -> str:
    bold = st.bold if bold is None else bold
    italic = st.italic if italic is None else italic
    border_style = 3 if box else 1
    out_col = ass_color(st.box_color, 1 - st.box_alpha) if box else ass_color(st.outline_color)
    pad = fs * 0.22 if box else outline_px
    ml = int(g.w * 0.07)
    # ASS: PrimaryColour = already sung, SecondaryColour = not yet sung
    return (f"Style: {name},{font or st.font},{fs},{ass_color(sung)},{ass_color(unsung)},{out_col},"
            f"{ass_color('#000000', 0.35)},{-1 if bold else 0},{-1 if italic else 0},0,0,100,100,"
            f"{st.spacing * g.scale:.1f},0,{border_style},{pad:.1f},{0 if box else shadow_px:.1f},8,{ml},{ml},0,1")


def build_ass(lines: List[LyricLine], st: LyricStyle, w: int, h: int, duration: float, title: str = "",
              artist: str = "", credit: str = "") -> str:
    g = _Geom(w, h, st)
    fs = g.fs
    outline_px = st.outline * fs
    shadow_px = st.shadow * fs
    highlight = st.highlight != "none"
    unsung, sung = st.color_unsung, (st.color_sung if highlight else st.color_unsung)

    next_fs = max(14, int(fs * 0.62))
    title_fs = int(fs * 1.25)
    rows = [
        _style_row("Main", st, fs, g, unsung=unsung, sung=sung, outline_px=outline_px, shadow_px=shadow_px, box=st.box),
        _style_row("Next", st, next_fs, g, unsung=st.color_unsung, sung=st.color_unsung,
                   outline_px=outline_px * 0.6, shadow_px=shadow_px * 0.6, box=False, bold=False,
                   font=st.font if st.font in READABLE else "Poppins"),
        _style_row("Dots", st, int(fs * 1.5), g, unsung=st.color_unsung, sung=st.color_sung,
                   outline_px=outline_px * 0.8, shadow_px=shadow_px, box=False, bold=True, font="Poppins"),
        _style_row("Title", st, title_fs, g, unsung=st.color_unsung, sung=st.color_unsung, outline_px=outline_px,
                   shadow_px=shadow_px, box=False),
        _style_row("Artist", st, int(title_fs * 0.5), g, unsung=st.color_sung, sung=st.color_sung,
                   outline_px=outline_px * 0.7, shadow_px=shadow_px, box=False),
        _style_row("Credit", st, max(14, int(fs * 0.34)), g, unsung="#FFFFFF", sung="#FFFFFF", outline_px=1.2,
                   shadow_px=0.0, box=False, bold=False, font="Poppins"),
    ]
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 2\n"
            f"ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n" + "\n".join(rows) + "\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")

    timed = sorted((l for l in lines if l.timed and l.text.strip()), key=lambda l: l.start)
    ev: List[str] = []

    def add(layer, a, b, style, text):
        if b - a >= 0.04:
            ev.append(f"Dialogue: {layer},{_ass_time(a)},{_ass_time(b)},{style},,0,0,0,,{text}")

    prev_ev_end = 0.0
    for i, ln in enumerate(timed):
        toks, breaks, times = _prepare(ln, st, g)
        if not toks:
            continue
        n_lines = len(breaks) + 1
        nxt = timed[i + 1] if i + 1 < len(timed) else None
        room = (nxt.start - ln.end) if nxt else HOLD
        end = ln.end + max(0.0, min(HOLD, room - LEAD - 0.03))
        end = min(end, duration) if duration else end
        start = min(max(ln.start - LEAD, prev_ev_end, 0.0), ln.start)     # never draw two lines on top of each other
        prev_ev_end = end
        y = g.top_y(n_lines)
        fade_out = int(min(260, max(60, (end - ln.end) * 1000)))   # never fade words that are still being sung
        anim = _anim_tags(st, g.x, y, fs, fade_out)
        text = _karaoke_text(toks, breaks, [(max(a, start), b) for a, b in times], st, start)
        if st.glow:
            glow_tags = (f"{anim}\\bord{fs * 0.20:.1f}\\blur{fs * 0.20:.1f}{tag_color(3, st.glow_color)}"
                         f"\\1a&HFF&\\3a&H30&\\shad0")
            glow_txt = "".join(_ass_escape(t) + ("\\N" if k in breaks else " ") for k, t in enumerate(toks)).rstrip()
            add(0, start, end, "Main", f"{{{glow_tags}}}{glow_txt}")
        add(1, start, end, "Main", f"{{{anim}}}{text}")

        # next-line preview (reading ahead) while this line is up
        if st.show_next and nxt and nxt.start - ln.end < 4.0:
            ntoks = (nxt.text.upper() if st.uppercase else nxt.text).split()
            if ntoks:
                nbreaks = set(wrap_balanced(ntoks, int(g.max_chars * fs / next_fs)))
                ny = y + g.block_h(n_lines) + fs * 0.18
                ntext = "".join(_ass_escape(t) + ("\\N" if k in nbreaks else " ") for k, t in enumerate(ntoks)).rstrip()
                a_hex = f"{int((1 - st.next_alpha) * 255):02X}"
                nstart = start
                nend = min(nxt.start, end)
                add(1, nstart, nend, "Next",
                    f"{{\\an8\\pos({g.x},{ny:.0f})\\fad({max(120, st.anim_ms // 2)},120)\\1a&H{a_hex}&"
                    f"\\3a&H{a_hex}&\\4a&HFF&}}{ntext}")

    # instrumental countdown dots + title card
    first_start = timed[0].start if timed else duration
    title_on = bool(st.title_card and (title or artist) and first_start >= 2.8)
    title_end = min(st.title_sec, first_start - 0.4) if title_on else 0.0
    if title_on:
        ty = h * 0.40
        t0 = 0.35
        fade = f"\\fad(500,500)"
        if title:
            add(1, t0, title_end, "Title", f"{{\\an8\\pos({g.x},{ty:.0f}){fade}}}{_ass_escape(title.upper() if st.uppercase else title)}")
        if artist:
            add(1, t0 + 0.25, title_end, "Artist",
                f"{{\\an8\\pos({g.x},{ty + title_fs * LINE_H:.0f}){fade}}}{_ass_escape(artist)}")
    if st.instrumental_dots:
        for a, b in gaps(timed, duration):
            if b >= duration - 0.01 or b - a < 5.5:
                continue
            d0, d1 = max(a + 1.0, b - 3.4), b - 0.15
            if title_on and d0 < title_end:
                d0 = title_end + 0.2
            if d1 - d0 < 1.2:
                continue
            third = max(0.2, (d1 - d0) / 3.0)
            cs = int(round(third * 100))
            dots = "".join(f"{{\\kf{cs}}}• " for _ in range(3)).rstrip()
            y = g.top_y(1)
            add(1, d0, d1, "Dots", f"{{\\an8\\pos({g.x},{y:.0f})\\fad(300,300)}}{dots}")
    if credit and duration > 6:
        add(2, max(duration - 5.0, 0), duration, "Credit",
            f"{{\\an2\\pos({g.x},{h * 0.965:.0f})\\fad(400,400)\\1a&H40&}}{_ass_escape(credit)}")
    return head + "\n".join(ev) + "\n"
