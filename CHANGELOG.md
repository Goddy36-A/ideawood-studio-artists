# Changelog

## 1.1.0 - unreleased
- **Cartoons for scenes**: in step 4 (Visuals), "Draw a cartoon for this scene..." opens a frame-by-frame drawing editor
  with a Paint-3D-style board: 8 brushes (pen, marker, pencil, crayon, spray, watercolor, calligraphy, pixel), eraser,
  fill bucket with tolerance, 10 shapes (outline / fill / both), text with any font, rectangle select (move, resize,
  flip, rotate, copy / cut / paste, insert picture), colour picker, zoom and pan, primary / secondary colours (left /
  right mouse button), opacity, stroke smoothing, pen-tablet pressure, undo / redo, onion skin, duplicate / delete
  frames, background colour, 4-30 fps.
- The song is the clock: Play starts the audio at the scene's start; the lyric being sung is shown as a guide (never saved).
  Clips shorter than the scene loop; "Fill scene length" adds blank frames to cover it.
- Saved cartoons become the scene's background clip (`source = "toon"`), so the single-pass FFmpeg render is unchanged;
  AI visuals never overwrite them and repeated choruses share them.
- **Lip-sync**: the editor's Lip-sync tool listens to the song with the bundled Rhubarb (offline, no credits) and shows
  the right mouth shape at the right moment. Built-in cartoon mouths, or your own A-H / X pictures. Click to place the
  mouth on a frame (frames without a spot inherit the previous one); drawn frames loop while the mouth follows the song.
- **AI storyboard**: "AI storyboard ideas for all scenes..." in step 4 asks the toon board service once (small credit
  cost, asks first) and adds an idea to every scene; shown on hover and inside the cartoon editor.

## 1.0.0 - 2026-10-08
First release: lyric video maker split out of Ideawood Studio (voxcut).
- Audio + pasted lyrics; Whisper auto-sync with fuzzy alignment, tap-to-sync, even spread, LRC import/export
- Timing table editor, SRT/LRC export
- 8 style presets, 15 bundled OFL fonts + user fonts, karaoke sweep/word highlight, glow, box, animations,
  next-line preview, countdown dots, title card
- AI visuals: per-scene search phrases from the lyrics, video/picture download, thumbnail picker, own files, gradient fallback
- Single-pass FFmpeg render: Ken Burns, transitions, grade, grain, vignette, visualiser, logo; 4 shapes, up to 4K
- Live preview frame, 22 s preview clip, `.iwlyric` projects
