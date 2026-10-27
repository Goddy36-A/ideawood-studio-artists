"""Client for the QuoteTube cloud API (AI ideas, narration, media search).

Video rendering stays 100% local (FFmpeg). Only these three things go online:
  * ideas  - AI writing (quotes, full reel plans, trend ideas)
  * tts    - AI narration (MP3)
  * media  - image / video / music search

Every request needs a valid API key from the QuoteTube web app, sent as
``Authorization: Bearer <key>``. Treat the key like a password.

No Qt imports here so it can be tested and reused from scripts.
"""
import base64
import json
import os
import urllib.error
import urllib.request

# Override via env for staging.
API_BASE = os.environ.get("IDEAWOOD_API_BASE") or os.environ.get("VOXCUT_API_BASE") or "https://quotetube.lovable.app".rstrip("/")

MEDIA_KINDS = ("image", "video", "music")
IDEA_KINDS = ("quote",)  # extend as the server adds more
TIMEOUT = 60
try:
    from . import __version__ as _v
except Exception:  # noqa: BLE001
    _v = "0"
USER_AGENT = f"IdeawoodStudio/{_v} (Artists, Windows desktop app)"


def _server_message(raw: str) -> str:
    """Short, safe text from a JSON error body ({"error": "..."}); never echoes HTML pages."""
    try:
        d = json.loads(raw)
        m = d.get("error") or d.get("message") or ""
        if isinstance(m, dict):
            m = m.get("message", "")
        return f": {str(m)[:160]}" if m else ""
    except Exception:  # noqa: BLE001
        return ""


class CloudError(Exception):
    """Any sign-in / network / API failure, with a message safe to show the user."""


class NotSignedIn(CloudError):
    pass


class CloudClient:
    """Authenticates with a QuoteTube API key sent as ``Authorization: Bearer <key>``."""

    def __init__(self, api_key="", api_base=API_BASE):
        self.api_base = api_base.rstrip("/")
        self.api_key = (api_key or "").strip()

    # ---------------- auth
    @property
    def signed_in(self):  # kept for GUI wording; True when a key is set
        return bool(self.api_key)

    def set_key(self, key):
        k = (key or "").strip().strip("\"'").strip()
        if k.lower().startswith("bearer "):  # people sometimes paste the whole header value
            k = k[7:].strip()
        self.api_key = k
        return self.api_key

    def clear_key(self):
        self.api_key = ""

    def access_token(self):
        if not self.api_key:
            raise NotSignedIn("Please paste your API key first.")
        return self.api_key

    # ---------------- HTTP
    def _post(self, path, payload):
        req = urllib.request.Request(
            f"{self.api_base}{path}",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": USER_AGENT, "Authorization": f"Bearer {self.access_token()}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            msg = _server_message(raw)
            if e.code == 401:
                raise NotSignedIn(f"The server rejected the API key (401){msg} - check it is current, "
                                  "complete and not revoked.") from e
            if e.code == 403:
                raise CloudError(f"Access denied (403){msg}. If your key is valid, the server or its firewall "
                                 "blocked this request.") from e
            raise CloudError(f"Server error {e.code}{msg}") from e
        except urllib.error.URLError as e:
            raise CloudError(f"Cannot reach the server: {e.reason}") from e
        except json.JSONDecodeError as e:
            raise CloudError("The server sent an unreadable response.") from e

    # ---------------- endpoints
    def ideas(self, topic, count=5, kind="quote"):
        return self._post("/api/public/v1/ideas",
                          {"action": "ideas", "topic": topic, "kind": kind, "count": int(count)})

    def compose(self, prompt):
        """Full reel plan."""
        return self._post("/api/public/v1/ideas", {"action": "compose", "prompt": prompt})

    def trends(self, niche, platform, count=5):
        """Suggest formats. platform e.g. 'reels', 'tiktok', 'shorts'."""
        return self._post("/api/public/v1/ideas",
                          {"action": "trends", "niche": niche, "platform": platform, "count": int(count)})

    def tts(self, text, voice="alloy"):
        """Returns raw MP3 bytes. Server replies {"audioBase64": "...", "mime": "audio/mpeg"}."""
        res = self._post("/api/public/v1/tts", {"text": text, "voice": voice})
        b64 = res.get("audioBase64")
        if not b64:
            raise CloudError(f"No audio in response (keys: {sorted(res)}).")
        return base64.b64decode(b64)

    def toon_storyboard(self, lyrics, bpm=0, mood="", style="storybook toon"):
        """Scene-by-scene storyboard for a song (text only, a tiny credit cost). Returns the server's
        {"storyboard": {...}} dict. NOTE: request field names follow the toon API notes - confirm against the server."""
        return self._post("/api/public/v1/toon", {"action": "storyboard", "lyrics": lyrics, "bpm": bpm,
                                                  "mood": mood, "style": style})

    def toon_character_rig(self, prompt, style="storybook toon"):
        """Character portrait + mouth kit (image generation, once per character). Returns {"characterRig": {...}}.
        NOTE: request field names follow the toon API notes - confirm against the server."""
        return self._post("/api/public/v1/toon", {"action": "character-rig", "prompt": prompt, "style": style})

    def media(self, kind, query, orientation=None, page=1):
        """Search media. orientation e.g. 'horizontal' (optional); page starts at 1."""
        if kind not in MEDIA_KINDS:
            raise CloudError(f"kind must be one of {MEDIA_KINDS}")
        body = {"kind": kind, "query": query, "page": int(page)}
        if orientation:
            body["orientation"] = orientation
        return self._post("/api/public/v1/media", body)

    def media_items(self, kind, query, orientation=None, page=1):
        """media() -> list of items: {id, kind, url, thumb, title, credit, creditUrl, source}."""
        return self.media(kind, query, orientation, page).get("items") or []

    def download(self, url, dest_no_ext, max_bytes=80_000_000):
        """Download a media URL; returns the saved path (extension chosen from Content-Type).

        Relative URLs (e.g. /api/public/media?u=...) are resolved against the API host and get the
        key. Absolute URLs on other hosts never receive the key.
        """
        import urllib.parse
        full = urllib.parse.urljoin(self.api_base + "/", url)
        headers = {"User-Agent": USER_AGENT}
        if urllib.parse.urlparse(full).netloc == urllib.parse.urlparse(self.api_base).netloc:
            headers["Authorization"] = f"Bearer {self.access_token()}"
        req = urllib.request.Request(full, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "video/mp4": ".mp4",
                       "video/webm": ".webm", "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
                       "audio/ogg": ".ogg"}.get(ctype) or os.path.splitext(urllib.parse.urlparse(full).path)[1] or ".bin"
                path, size = dest_no_ext + ext, 0
                with open(path, "wb") as f:
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_bytes:
                            f.close(); os.remove(path)
                            raise CloudError("Media file too large, skipped.")
                        f.write(chunk)
                return path
        except urllib.error.HTTPError as e:
            raise CloudError(f"Download failed ({e.code}).") from e
        except urllib.error.URLError as e:
            raise CloudError(f"Download failed: {e.reason}") from e
