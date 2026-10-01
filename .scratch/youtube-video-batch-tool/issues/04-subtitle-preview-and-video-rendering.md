# 04: Subtitle preview and video rendering

**What to build:** The user can preview caption appearance, choose an output profile and frame-fit behavior, then render the assigned Background with the complete YouTube audio and selected captions.

**Blocked by:** 03: Source downloads and subtitle selection.

**Status:** complete

- [x] The user can create, edit, duplicate, and apply Subtitle presets with font, size, text color, background, outline/shadow, alignment, and position controls.
- [x] A static preview uses editable demo text and selectable output frame shapes; the style controls update it live.
- [x] The 720p profile outputs 1280×720 at the assigned Background's frame rate.
- [x] Match background uses the assigned Background's native dimensions and frame rate; custom profiles allow user-set dimensions and frame rate.
- [x] Before rendering, the app detects aspect-ratio mismatches and lets the user choose the profile frame or the Background frame, then crop-to-fill or contain/pad as applicable.
- [x] Mismatch decisions can be applied per job or in bulk and are stored for retry.
- [x] FFmpeg maps picture from the assigned Background and the complete audio from the YouTube source, loops/trims the Background to audio duration, and outputs H.264 MP4 with AAC audio.
- [x] Selected captions are burned into the video and an SRT sidecar is saved. SRT/VTT input is normalized, and ASS rendering data is generated from the selected style and position.
- [x] Render progress, actionable errors, output artifacts, and the encoder used are reported through the public worker interface.
- [x] The style workspace checks font availability and shows the renderer's matched fallback family where fontconfig is available.
- [x] A tiny real FFmpeg fixture verifies output dimensions, duration/audio presence, burned captions, and SRT sidecar; behavioral tests cover a missing-libass failure and a successful retry after choosing skip captions.

**Verification:** `npm run build`, `cargo check`, and `python3 -m unittest discover -s worker/tests -v`. Caption burn-in was run against a temporary FFmpeg 9.0.2 build with libass in `/tmp`; this avoided changing the Homebrew installation. The failure/retry path was run against the installed FFmpeg build, which has no libass filter.
