import os

from ideawood_artists import lyrics as L
from ideawood_artists import visuals as V
from ideawood_artists.cloud import CloudError
from ideawood_artists.project import Project
from ideawood_artists.scenes import plan_scenes


class FakeCloud:
    signed_in = True

    def __init__(self, fail_compose=False):
        self.fail_compose, self.searched = fail_compose, []

    def compose(self, prompt):
        if self.fail_compose:
            raise CloudError("down")
        return {"items": [{"visual": f"ocean sunset {i}"} for i in range(10)], "backgroundQuery": "calm"}

    def media_items(self, kind, query, orientation=None, page=1):
        self.searched.append((kind, query))
        return [{"url": "http://x/clip", "thumb": "", "title": "t", "credit": "Pexels / Someone"}]

    def download(self, url, dest):
        open(dest + ".mp4", "wb").write(b"x")
        return dest + ".mp4"


def proj():
    p = Project(title="Song", artist="Me", duration=60.0)
    p.lines = L.finalize_timing(L.distribute_evenly(L.parse_lyrics("rain on my window\ncold night\n\nsun and ocean waves\nwarm light"), 60.0), 60.0)
    p.scenes = plan_scenes(p.lines, 60.0, min_len=5.0)
    return p


def test_fallback_queries_are_filmable():
    assert V.fallback_query("the rain keeps falling") == "rain on window"
    assert V.fallback_query("nothing special", genre="Reggae") == "sunset beach palm"
    assert "reggae" not in V.keywords("the the and love love fire", 2)


def test_prompt_lists_every_scene():
    p = proj()
    pr = V.build_plan_prompt(p, p.scenes)
    assert f"exactly {len(p.scenes)} items" in pr and "rain on my window" in pr


def test_ai_plan_used_and_falls_back_offline():
    p = proj()
    assert V.plan_queries(FakeCloud(), p, p.scenes)[0].startswith("ocean sunset")
    q = V.plan_queries(FakeCloud(fail_compose=True), p, p.scenes)
    assert q[0] == "rain on window" and all(x and not x.startswith("ocean sunset") for x in q)


def test_fill_scenes_downloads_and_records_credit(tmp_path):
    p = proj()
    rep = V.fill_scenes(FakeCloud(), p, "video", workdir=str(tmp_path))
    assert rep["filled"] == len(p.scenes)
    assert all(s.kind == "video" and os.path.isfile(s.path) and s.source == "ai" for s in p.scenes)
    assert "Pexels" in V.credits_text(p)


def test_no_key_keeps_gradients(tmp_path):
    p = proj()
    c = FakeCloud()
    c.signed_in = False
    rep = V.fill_scenes(c, p, workdir=str(tmp_path))
    assert rep["filled"] == 0 and all(s.kind == "gradient" for s in p.scenes) and p.scenes[0].query


def test_own_files_are_kept_by_ai_fill(tmp_path):
    p = proj()
    img = tmp_path / "a.jpg"
    img.write_bytes(b"x")
    V.assign_local(p.scenes, [str(img)], only=[0])
    V.fill_scenes(FakeCloud(), p, workdir=str(tmp_path))
    assert p.scenes[0].source == "mine" and p.scenes[0].path == str(img)
