"""AI mode for supporting visuals: pick background pictures / video clips that fit the lyrics of every scene.

Online (needs the API key, same cloud as the main Ideawood Studio):
  1. ``compose`` is asked for one short stock-footage search phrase per scene (it sees the mood and the lyrics).
  2. Each phrase is searched with ``media`` (video and/or image) and the first usable result is downloaded.
  3. If supported, the dedicated background-visual provider is called with the actual lyric lines and returns ready-made scene visuals.
Offline fallback (no key, or the cloud fails): search phrases are built from the lyrics themselves with a small
mood lexicon, and anything that cannot be fetched stays a designed animated gradient - the video always renders.

Artists can also use their own pictures/clips (``assign_local``). Repeated stanzas share one background.
No Qt imports; the cloud client is injected so everything is testable with a fake.
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .cloud import CloudClient, CloudError
from .lyrics import LyricLine
from .project import Project, Scene
from .scenes import share_by_key

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi")

STOP = set("""a about above after again all also am an and any are as at be because been before being below between both
but by can could did do does doing down during each few for from further had has have having he her here hers herself him
himself his how i if in into is it its itself just let me more most my myself no nor not now of off on once only or other
our ours out over own same she should so some such than that the their theirs them then there these they this those
through to too under until up very was we were what when where which while who whom why will with would you your yours
oh yeah yes na la ooh hey gonna wanna cause got get go going know like say said baby""".split())

# lyric word -> something that can actually be filmed
LEXICON = {
    "love": "romantic warm light", "heart": "romantic warm light", "kiss": "romantic sunset", "night": "city night lights",
    "fire": "fire sparks", "burn": "fire sparks", "sun": "golden sunlight", "sunshine": "golden sunlight",
    "sunrise": "sunrise horizon", "morning": "sunrise horizon", "rain": "rain on window", "storm": "storm clouds",
    "ocean": "ocean waves", "sea": "ocean waves", "wave": "ocean waves", "river": "river flowing", "water": "water ripples",
    "mountain": "mountain landscape", "hill": "green hills", "village": "village landscape", "home": "countryside home",
    "dance": "dance floor lights", "party": "party lights", "club": "club lights", "city": "city street night",
    "street": "city street night", "road": "road driving", "car": "road driving", "money": "city skyline night",
    "god": "heavenly light rays", "pray": "heavenly light rays", "heaven": "heavenly clouds", "angel": "heavenly clouds",
    "star": "starry sky", "stars": "starry sky", "moon": "moon night sky", "sky": "sky clouds", "flower": "flowers bloom",
    "garden": "garden flowers", "forest": "forest light", "tree": "forest light", "bird": "birds flying",
    "freedom": "birds flying sky", "fly": "birds flying sky", "tears": "rain on window", "cry": "rain on window",
    "smile": "sunlight bokeh", "gold": "golden bokeh", "light": "light rays bokeh", "dream": "dreamy clouds",
    "summer": "summer beach", "beach": "summer beach", "wind": "grass in wind", "lake": "calm lake sunrise",
}
GENRE_DEFAULT = {"reggae": "sunset beach palm", "gospel": "heavenly light rays", "hip hop": "city night street",
                 "rap": "city night street", "afrobeats": "colorful lights dance", "rock": "stage lights smoke",
                 "pop": "colorful bokeh lights", "rnb": "city night rain", "r&b": "city night rain",
                 "worship": "heavenly light rays", "acoustic": "golden hour field"}
GENERIC = ["abstract light bokeh", "cinematic clouds", "golden particles", "city lights night", "calm ocean sunset"]


# --------------------------------------------------------------------------- text helpers
def scene_lines(p: Project, sc: Scene) -> List[LyricLine]:
    return [l for l in p.lines if l.timed and l.start < sc.end and l.end > sc.start]


def scene_text(p: Project, sc: Scene) -> str:
    return " ".join(l.text for l in scene_lines(p, sc))


def keywords(text: str, k: int = 4) -> List[str]:
    counts: Dict[str, int] = {}
    for w in re.findall(r"[A-Za-z']+", text.lower()):
        w = w.strip("'")
        if len(w) > 2 and w not in STOP:
            counts[w] = counts.get(w, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:k]


def fallback_query(text: str, mood: str = "", genre: str = "", salt: int = 0) -> str:
    """A filmable search phrase from the lyrics (offline)."""
    hits: List[str] = []
    for w in re.findall(r"[a-z']+", text.lower()):
        q = LEXICON.get(w.strip("'"))
        if q and q not in hits:
            hits.append(q)
    if hits:
        return hits[0]
    if mood.strip():
        return f"{mood.strip()} cinematic background"[:60]
    g = genre.strip().lower()
    for key, q in GENRE_DEFAULT.items():
        if key in g:
            return q
    return GENERIC[salt % len(GENERIC)]


def build_plan_prompt(p: Project, scenes: List[Scene]) -> str:
    parts = [f"Plan background visuals for a lyric video of the song \"{p.title or 'Untitled'}\""
             + (f" by {p.artist}" if p.artist else "") + ".",
             f"Genre: {p.genre or 'not given'}. Mood the artist wants: {p.mood or 'match the lyrics'}.",
             f"Return exactly {len(scenes)} items, one per scene in order. For each item: text = the theme of that part "
             f"in at most 8 words; visual = a 2-4 word search phrase for stock footage - concrete and filmable "
             f"(landscapes, skies, water, city lights, textures, bokeh), no close-up faces, no text, no logos. "
             f"Keep the look consistent across scenes (set backgroundQuery to the overall vibe, backgroundKind to video).",
             "Scenes:"]
    for i, sc in enumerate(scenes, 1):
        t = scene_text(p, sc)
        parts.append(f"{i}. [{sc.start:.0f}s-{sc.end:.0f}s] {t[:160] or '(instrumental)'}")
    return "\n".join(parts)[:3800]


# --------------------------------------------------------------------------- planning with AI (one call)
def plan_queries(cloud: Optional[CloudClient], p: Project, scenes: List[Scene],
                 on_status: Callable[[str], None] = lambda s: None) -> List[str]:
    """One search phrase per scene. Uses the AI plan when available, the lyric-based fallback otherwise."""
    ai: List[str] = []
    if cloud is not None and cloud.signed_in and scenes:
        try:
            on_status("Asking the AI to plan visuals for each part of the song...")
            plan = cloud.compose(build_plan_prompt(p, scenes))
            items = plan.get("items") or []
            ai = [str(it.get("visual") or "").strip() for it in items]
            base = str(plan.get("backgroundQuery") or "").strip()
            ai = [q or base for q in ai]
        except CloudError as e:
            on_status(f"AI planning unavailable ({e}); using the lyrics instead.")
    out: List[str] = []
    for i, sc in enumerate(scenes):
        q = ai[i] if i < len(ai) and ai[i] else ""
        out.append(q or fallback_query(scene_text(p, sc), p.mood, p.genre, i))
    return out


# --------------------------------------------------------------------------- searching and downloading
@dataclass
class Candidate:
    kind: str
    url: str
    thumb: str
    title: str
    credit: str


def _visuals_provider_candidates(cloud: CloudClient, p: Project, sc: Scene, prefer: str, style: str = "cinematic") -> List[Candidate]:
    """Use the dedicated lyric-visual API if the client supports it; returns [] if it is unavailable."""
    if getattr(cloud, "background_visuals", None) is None:
        return []
    try:
        lines = [l.text.strip() for l in scene_lines(p, sc) if l.text and l.text.strip()]
        if not lines:
            lines = [scene_text(p, sc).strip()]
        payload = cloud.background_visuals(lines, media=prefer, style=style or "cinematic")
    except (CloudError, TypeError, ValueError):
        return []
    out: List[Candidate] = []
    for item in payload or []:
        if not isinstance(item, dict):
            continue
        url = item.get("url") or item.get("download_url")
        if not url:
            continue
        kind = str(item.get("kind") or item.get("media") or prefer or "image").lower()
        if kind not in {"image", "video"}:
            kind = "video" if url.lower().endswith((".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv")) else "image"
        out.append(Candidate(kind, url, item.get("thumb") or "", item.get("title") or item.get("line") or "", item.get("credit") or ""))
    return out


def search(cloud: CloudClient, query: str, kinds, orientation: Optional[str], limit: int = 8) -> List[Candidate]:
    out: List[Candidate] = []
    for kind in kinds:
        for orient in ([orientation, None] if orientation else [None]):
            try:
                items = cloud.media_items(kind, query, orientation=orient)
            except CloudError:
                continue                               # e.g. orientation value not accepted -> retry without it
            for it in items:
                if it.get("url"):
                    out.append(Candidate(kind, it["url"], it.get("thumb") or "", it.get("title") or "",
                                         it.get("credit") or ""))
            if items:
                break
    return out[:limit]


def download(cloud: CloudClient, cand: Candidate, dest_no_ext: str) -> str:
    urls = [cand.url] + ([cand.thumb] if cand.kind == "image" and cand.thumb else [])
    last: Optional[Exception] = None
    for u in urls:
        try:
            return cloud.download(u, dest_no_ext)
        except CloudError as e:
            last = e
    raise CloudError(str(last) if last else "Download failed.")


def media_dir() -> str:
    from .paths import user_data_dir
    d = os.path.join(user_data_dir(), "media")
    os.makedirs(d, exist_ok=True)
    return d


def _kinds_for(prefer: str, i: int) -> List[str]:
    if prefer == "image":
        return ["image", "video"]
    if prefer == "both":
        return ["video", "image"] if i % 2 == 0 else ["image", "video"]
    return ["video", "image"]


def fill_scenes(cloud: Optional[CloudClient], p: Project, prefer: str = "video",
                only: Optional[List[int]] = None, on_status: Callable[[str], None] = lambda s: None,
                on_progress: Callable[[float], None] = lambda v: None,
                should_cancel: Callable[[], bool] = lambda: False, workdir: Optional[str] = None) -> dict:
    """Search + download a background for every scene that is not the artist's own file.

    Scenes with the same ``key`` (repeated chorus) reuse one download. Returns {"filled": n, "notes": [...]}.
    """
    notes: List[str] = []
    scenes = p.scenes
    idxs = [i for i in (only if only is not None else range(len(scenes))) if scenes[i].source not in ("mine", "toon")]
    if not idxs:
        return {"filled": 0, "notes": ["Nothing to fill (all scenes use your own files)."]}
    wd = workdir or media_dir()
    if only is None:
        queries = plan_queries(cloud, p, [scenes[i] for i in idxs], on_status)
        for i, q in zip(idxs, queries):
            scenes[i].query = q
    else:
        for i in idxs:
            if not scenes[i].query:
                scenes[i].query = fallback_query(scene_text(p, scenes[i]), p.mood, p.genre, i)
    if cloud is None or not cloud.signed_in:
        notes.append("No API key: kept the animated gradients. Paste your key to get AI pictures and clips.")
        return {"filled": 0, "notes": notes}

    done_by_key: Dict[str, Scene] = {}
    filled = 0
    for n, i in enumerate(idxs):
        if should_cancel():
            break
        sc = scenes[i]
        on_progress(100.0 * n / len(idxs))
        twin = done_by_key.get(sc.key)
        if twin is not None and only is None:
            sc.kind, sc.path, sc.credit, sc.source = twin.kind, twin.path, twin.credit, "ai"
            filled += 1
            continue
        on_status(f"Finding visuals {n + 1}/{len(idxs)}: \"{sc.query}\"")
        got = None
        for cand in _visuals_provider_candidates(cloud, p, sc, prefer, style=p.mood or p.genre or "cinematic"):
            try:
                path = download(cloud, cand, os.path.join(wd, f"scene_{abs(hash((cand.url, i))) % 10**8}"))
                got = (cand, path)
                break
            except CloudError:
                continue
        if not got:
            for q in [sc.query, fallback_query(scene_text(p, sc), p.mood, p.genre, i)]:
                for cand in search(cloud, q, _kinds_for(prefer, i), p.orientation, limit=4):
                    try:
                        path = download(cloud, cand, os.path.join(wd, f"scene_{abs(hash((q, i))) % 10**8}"))
                        got = (cand, path)
                        break
                    except CloudError:
                        continue
                if got:
                    break
        if got:
            cand, path = got
            sc.kind, sc.path, sc.credit, sc.source = cand.kind, path, cand.credit, "ai"
            done_by_key[sc.key] = sc
            filled += 1
        else:
            notes.append(f"Scene {i + 1}: nothing found for \"{sc.query}\" - kept the gradient.")
    on_progress(100.0)
    if only is None:
        share_by_key(scenes)
    return {"filled": filled, "notes": notes}


def credits_text(p: Project) -> str:
    cr = sorted({s.credit for s in p.scenes if s.credit})
    return ("Media credits\n\n" + "\n".join(cr) + "\n") if cr else ""


# --------------------------------------------------------------------------- the artist's own files
def classify(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else ""


def assign_local(scenes: List[Scene], paths: List[str], only: Optional[List[int]] = None):
    """Spread the artist's pictures/clips over the scenes in order (repeating if there are fewer files)."""
    files = [(pth, classify(pth)) for pth in paths if classify(pth)]
    if not files:
        return 0
    idxs = list(only) if only is not None else list(range(len(scenes)))
    seen: Dict[str, tuple] = {}
    n = 0
    for i in idxs:
        sc = scenes[i]
        if only is None and sc.key in seen:
            pth, kind = seen[sc.key]
        else:
            pth, kind = files[n % len(files)]
            n += 1
            seen[sc.key] = (pth, kind)
        sc.kind, sc.path, sc.source, sc.credit, sc.toon = kind, pth, "mine", "", ""
    return len(idxs)


def thumbnail(path: str, kind: str, out_png: Optional[str] = None, width: int = 240) -> Optional[str]:
    """A small PNG for the scene table (first frame of a video / the picture itself)."""
    import subprocess
    from .paths import find_tool, no_window_flags
    if not path or not os.path.isfile(path):
        return None
    out_png = out_png or os.path.join(tempfile.gettempdir(), f"iw_thumb_{abs(hash(path)) % 10**9}.png")
    if os.path.exists(out_png):
        return out_png
    cmd = [find_tool("ffmpeg"), "-y", "-nostdin", "-v", "error", "-i", path, "-frames:v", "1",
           "-vf", f"scale={width}:-2", out_png]
    r = subprocess.run(cmd, capture_output=True, creationflags=no_window_flags())
    return out_png if r.returncode == 0 and os.path.exists(out_png) else None


__all__ = [
    "Candidate",
    "assign_local",
    "build_plan_prompt",
    "classify",
    "credits_text",
    "download",
    "fallback_query",
    "fill_scenes",
    "keywords",
    "media_dir",
    "plan_queries",
    "scene_lines",
    "scene_text",
    "search",
    "thumbnail",
]
