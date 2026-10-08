from ideawood_artists import ass_lyrics as A
from ideawood_artists import lyrics as L
from ideawood_artists.project import Project, frame_size
from ideawood_artists.scenes import plan_scenes
from ideawood_artists.styles import PRESETS, LyricStyle


def lines(text="Walking through the city lights\nEvery shadow sings\n\nOmuramba waitu\nDancing in the sun", dur=40.0):
    ls = L.distribute_evenly(L.parse_lyrics(text), dur, lead=5.0)
    return L.finalize_timing(ls, dur)


def test_ass_has_karaoke_styles_and_events():
    ass = A.build_ass(lines(), PRESETS["Karaoke Bold"], 1920, 1080, 40.0, "Song", "Artist")
    assert "PlayResX: 1920" in ass and "Style: Main,Poppins" in ass
    assert "\\kf" in ass and "Dialogue: 1" in ass and "Song" in ass


def test_highlight_word_mode_and_none():
    st = PRESETS["Street Poster"].copy()
    assert "\\k" in A.build_ass(lines(), st, 1920, 1080, 40.0)
    st.highlight = "none"
    assert "\\kf" not in A.build_ass(lines(), st, 1920, 1080, 40.0)


def test_uppercase_and_glow_layer():
    ass = A.build_ass(lines(), PRESETS["Neon Night"], 1920, 1080, 40.0)
    assert "Dialogue: 0" in ass                     # glow layer under the text
    assert "WALKING" in A.build_ass(lines(), PRESETS["Street Poster"], 1920, 1080, 40.0)


def test_special_characters_are_escaped():
    ls = lines("Love {is} blind\\ever")
    assert "{is}" not in A.build_ass(ls, LyricStyle(), 1280, 720, 40.0)


def test_no_two_lines_overlap_in_time():
    ass = A.build_ass(lines(), LyricStyle(show_next=False, title_card=False, instrumental_dots=False), 1280, 720, 40.0)
    ev = [e for e in ass.splitlines() if e.startswith("Dialogue: 1")]
    ts = [tuple(x.split(",")[1:3]) for x in ev]
    assert ts == sorted(ts)


def test_instrumental_dots_in_long_gap():
    ls = [L.LyricLine("first line here", 5, 8), L.LyricLine("after solo", 30, 33)]
    ass = A.build_ass(L.finalize_timing(ls, 40.0), LyricStyle(), 1280, 720, 40.0)
    assert "Style: Dots" in ass and "Dialogue: 1,0:00:2" in ass


def test_frame_sizes():
    assert frame_size("Landscape 16:9 (YouTube)", 1080) == (1920, 1080)
    assert frame_size("Portrait 9:16 (Reels / TikTok / Shorts)", 1080) == (1080, 1920)
    assert frame_size("Square 1:1", 720) == (720, 720)


def test_scenes_tile_song_and_choruses_share_key():
    text = "[Verse]\nl1 a b\nl2 c d\n\n[Chorus]\nsing it loud\nsing it proud\n\n[Verse 2]\nl3 e f\nl4 g h\n\n[Chorus]\nsing it loud\nsing it proud"
    ls = L.finalize_timing(L.distribute_evenly(L.parse_lyrics(text), 80.0), 80.0)
    sc = plan_scenes(ls, 80.0, min_len=5.0)
    assert sc[0].start == 0 and abs(sc[-1].end - 80.0) < 1e-6
    assert all(abs(a.end - b.start) < 1e-6 for a, b in zip(sc, sc[1:]))
    keys = [s.key for s in sc]
    assert len(keys) > len(set(keys))              # the chorus came back with the same key


def test_project_roundtrip(tmp_path):
    p = Project(title="T", artist="A", lines=lines())
    p.style = PRESETS["Soul & Script"].copy()
    p.scenes = plan_scenes(p.lines, 40.0)
    f = tmp_path / "x.iwlyric"
    p.save(str(f))
    q = Project.load(str(f))
    assert q.title == "T" and q.style.font == "Great Vibes" and len(q.lines) == len(p.lines) and len(q.scenes) == len(p.scenes)
