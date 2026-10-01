# 08: Startup toolchain bootstrap and yt-dlp auto-update

**What to build:** Gate the main workspace behind a launch splash that validates the packaged media/OCR tools, checks the official stable yt-dlp and Deno releases, downloads missing/outdated binaries into app data, verifies their SHA-256 digests and reported versions, and only then opens the workspace.

**Blocked by:** 07: Windows and macOS desktop packaging.

**Status:** in-progress

- [x] The splash automatically reports startup checks and download/update progress and does not render the workspace until all checks pass; it needs no update button.
- [x] Packaged FFmpeg/ffprobe H.264, AAC, and subtitle capabilities plus Tesseract and OCR models are checked locally. Missing pinned OCR models are restored automatically.
- [x] Missing/outdated yt-dlp and Deno binaries are downloaded for the current OS/architecture from official stable release assets, SHA-256 checked, version checked, and atomically installed in app data.
- [x] All later yt-dlp operations and queue workers use the app-data binaries when present; the read-only app bundle remains unchanged.
- [x] Offline/API/download failures keep the user on a retryable splash with an actionable error and the last installed versions.
- [ ] Tests exercise release selection, digest/version rejection, atomic update, and startup gating through worker/UI seams.

**Implementation note:** FFmpeg, ffprobe, and Tesseract executables are target-native resources included in the signed app bundle and are checked at launch; yt-dlp, Deno, and pinned OCR models are the dependencies that can be repaired/downloaded at runtime. If a bundled executable is absent or corrupt, the splash reports that the app installation needs repair. The macOS Apple Silicon `.app` and `.dmg` bundle successfully; Windows packaging and automated tests remain pending.

**Startup regression fix:** The released UI was calling the new startup method against an older packaged worker, which returned `Unknown worker method`. Rebuilt the PyInstaller worker and DMG. The startup checker also now uses FFmpeg's and ffprobe's single-dash `-version` flag. Verified the exact worker embedded in the rebuilt `.app` accepts `system.toolchain.check` and reports FFmpeg, ffprobe, and Tesseract ready.

**Sources:** [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases), [yt-dlp JavaScript runtime setup](https://github.com/yt-dlp/yt-dlp/wiki/ejs), and [Deno releases](https://github.com/denoland/deno/releases).
