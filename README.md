# Ideawood Studio for Artists

Turn a finished song into a professional **lyric video** on your own PC: add the audio, paste the lyrics, get them timed,
pick a look, let **AI find the background pictures and video clips**, and export for YouTube, Reels, TikTok or Instagram.

Built from the engines of [voxcut / Ideawood Studio](https://github.com/Goddy36-A/voxcut) (offline Whisper, FFmpeg, the AI
cloud client, the theme), re-focused on one job.

## The five steps

| Step | What happens |
|---|---|
| **1 Song & lyrics** | Choose the audio, paste lyrics (`[Chorus]`-style headers and blank-line verses understood), then **Auto-sync** (offline Whisper + alignment), **Tap to sync** (press Space as each line starts - best for Luganda, Runyankole and other languages Whisper doesn't know) or **Spread evenly**. |
| **2 Timing** | Table editor: change any time or text, move everything, split / merge / add / delete lines, play from a line, export `.lrc` (with word timing) and `.srt`. |
| **3 Look & fonts** | 8 presets (Karaoke Bold, Neon Night, Cinematic Gold, Street Poster, Soul & Script, Retro Tape, Clean Minimal, Reggae Sunrise), **15 bundled professional fonts** + add your own `.ttf/.otf`, karaoke fill (sweep or word), glow, box, outline, entrance animation, next-line preview, countdown dots in long gaps, title card, colour grade, grain, vignette, transitions, optional audio visualiser. |
| **4 Visuals (AI)** | AI reads the lyrics, plans a search phrase per part of the song and downloads matching **video clips or pictures** (needs your API key). Repeated choruses reuse the same background. Pick alternatives with thumbnails, or use your own files. No key? Designed animated gradients - it always renders. Add your logo. |
| **5 Export** | 16:9, 9:16, 1:1 or 4:5; 480p to 4K; optional loudness normalisation; 22 s preview clip; `.credits.txt` for stock media. Projects save as `.iwlyric`. |

A **live preview** frame (right side) follows every change.

## How it renders

Everything is one FFmpeg pass: scenes (image Ken-Burns / looped video / gradient) -> crossfades -> darken, blur, grade,
vignette, grain -> optional visualiser + logo -> lyrics drawn by libass from a generated ASS script -> H.264 + AAC MP4.
ASS gives true karaoke sweep, glow and outlines without drawing frames in Python, so exports are fast.

## Run from source

```
pip install -r requirements.txt
# put ffmpeg(.exe), ffprobe(.exe) in bin/ (or on PATH); whisper-cli + a model are only needed for Auto-sync
python main.py
```
Tests: `pip install -r requirements-dev.txt && python -m pytest -q tests`

## Windows EXE

Push to GitHub: the **Build Windows EXE** workflow runs the tests, bundles FFmpeg, whisper.cpp and the English base model,
and produces `IdeawoodStudioArtists.exe`. Tag `v1.0.0` to publish a release.

## What was kept from voxcut and what was left behind

Kept: offline speech engine (`asr.py`), cloud client (`cloud.py`), theme, FFmpeg job runner, model management.
Left behind: lecture recorder, whiteboard, screen capture, background removal (RVM / onnxruntime - saves ~100 MB), workspaces,
generic video tools. They don't help a lyric video and would only slow the app down.

## Notes

* Lyric accuracy: Whisper is trained mostly on speech; over loud music it can miss words. Your pasted text is always what
  is shown - only the *timing* comes from the audio - and the match rate is reported so you know when to check step 2 or use Tap to sync.
* Stock media comes from your AI service; keep the generated `.credits.txt` with the video where licences ask for credit.
* Fonts: SIL Open Font License (see `assets/fonts/OFL-LICENSES.txt`). FFmpeg is GPL; whisper.cpp is MIT.
