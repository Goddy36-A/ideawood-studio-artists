from ideawood_artists import lyrics as L
from ideawood_artists.asr import Segment, Transcript, Word


def tr(words, t0=1.0, step=0.5):
    ws = [Word(t0 + i * step, t0 + i * step + 0.4, w) for i, w in enumerate(words)]
    return Transcript([Segment(ws[0].start, ws[-1].end, " ".join(words), ws)])


def test_parse_sections_and_stanzas():
    lines = L.parse_lyrics("[Verse 1]\nHello world\nSecond line\n\n[Chorus]\nSing it loud\n")
    assert [l.text for l in lines] == ["Hello world", "Second line", "Sing it loud"]
    assert lines[0].section == "Verse 1" and lines[2].section == "Chorus"
    assert lines[0].stanza == lines[1].stanza != lines[2].stanza


def test_long_line_is_split():
    parts = L.split_long("word " * 40)
    assert len(parts) >= 2 and all(len(p) <= 70 for p in parts)


def test_align_uses_audio_timing_but_artist_spelling():
    lines = L.parse_lyrics("Omuramba waitu we are one\nDancing in the sun")
    heard = tr("omuramba wa itu we are one dancing in the sun".split())     # ASR mangled the first word
    out = L.align_lyrics(lines, heard, 20.0)
    assert out[0].text == "Omuramba waitu we are one"
    assert out[0].start < out[1].start < out[1].end <= 20.0
    assert all(w.end >= w.start for l in out for w in l.words)


def test_unmatched_words_are_interpolated_and_ordered():
    lines = L.parse_lyrics("alpha beta gamma\ndelta epsilon zeta")
    out = L.align_lyrics(lines, tr(["alpha", "zeta"]), 30.0)
    starts = [w.start for l in out for w in l.words]
    assert starts == sorted(starts) and out[0].timed and out[1].timed


def test_no_recognition_spreads_evenly():
    out = L.align_lyrics(L.parse_lyrics("one two\nthree four"), Transcript([]), 40.0)
    assert out[0].end <= out[1].start and out[1].end <= 40.0


def test_lrc_roundtrip_and_enhanced():
    lines = L.parse_lyrics("a b c\nd e f")
    L.distribute_evenly(lines, 20.0)
    text = L.to_lrc(lines, "T", "A", enhanced=True)
    back = L.parse_lrc(text, 20.0)
    assert [l.text for l in back] == ["a b c", "d e f"]
    assert abs(back[0].start - lines[0].start) < 0.02 and len(back[0].words) == 3


def test_edit_helpers():
    lines = L.parse_lyrics("one two three four")
    L.distribute_evenly(lines, 10.0)
    L.split_line(lines, 0, 2)
    assert [l.text for l in lines] == ["one two", "three four"] and lines[0].end <= lines[1].start + 1e-6
    L.merge_with_next(lines, 0)
    assert lines[0].text == "one two three four"
    t = lines[0].start
    L.shift_all(lines, 1.0)
    assert abs(lines[0].start - (t + 1.0)) < 1e-6


def test_finalize_never_overlaps():
    a, b = L.LyricLine("x", 1.0, 5.0), L.LyricLine("y", 3.0, 6.0)
    L.finalize_timing([a, b], 10.0)
    assert a.end <= b.start
