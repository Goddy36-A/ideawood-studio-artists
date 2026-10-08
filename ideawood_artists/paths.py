"""Locate bundled tools (ffmpeg, whisper), assets and fonts - from source or inside the PyInstaller exe."""
import os
import shutil
import subprocess
import sys


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _candidates(name):
    exe = name + (".exe" if os.name == "nt" else "")
    base = getattr(sys, "_MEIPASS", None)
    if base:
        yield os.path.join(base, "bin", exe)
    yield os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "bin", exe)
    yield os.path.join(_root(), "bin", exe)


def find_tool(name):
    for c in _candidates(name):
        if os.path.isfile(c):
            return c
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"{name} not found. Put it in the 'bin' folder or on PATH.")


def no_window_flags():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def asset_path(name):
    base = getattr(sys, "_MEIPASS", None)
    return os.path.join(base if base else _root(), "assets", name)


def bundled_fonts_dir() -> str:
    """Fonts that ship with the app (SIL OFL licensed, see assets/fonts/OFL-LICENSES.txt)."""
    return asset_path("fonts")


def user_data_dir() -> str:
    d = os.environ.get("IDEAWOOD_ARTISTS_DATA")
    if not d:
        if os.name == "nt":
            d = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "IdeawoodStudio", "Artists")
        else:
            d = os.path.join(os.path.expanduser("~"), ".local", "share", "IdeawoodStudio", "Artists")
    os.makedirs(d, exist_ok=True)
    return d


def user_fonts_dir() -> str:
    """Fonts the artist adds themselves (any .ttf/.otf dropped here is available in the app and the render)."""
    d = os.path.join(user_data_dir(), "fonts")
    os.makedirs(d, exist_ok=True)
    return d
