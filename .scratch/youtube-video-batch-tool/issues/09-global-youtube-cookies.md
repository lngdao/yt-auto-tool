# 09: Global YouTube cookies configuration

**What to build:** Add an app-wide setting for selecting and clearing a local Netscape-format cookies.txt file. Apply the configured file to every yt-dlp operation and report a clear error if it is missing or malformed.

**Blocked by:** 03: Source download and subtitle selection; 08: Startup toolchain bootstrap and yt-dlp auto-update.

**Status:** in-progress

- [x] A Settings workspace can choose, show, validate, and clear a local cookies.txt path using the native file picker.
- [x] The setting persists locally and applies to metadata, audio/video, subtitles, and thumbnail yt-dlp requests.
- [x] Cookie contents are never copied, uploaded, or written to logs; only the local path is stored.
- [x] A deleted/invalid configured cookie file gives an actionable error before yt-dlp starts.
- [ ] Tests cover persistence, command propagation to every yt-dlp path, and missing/malformed file handling.

**Implementation note:** The Settings screen explains that `cookies.txt` is sensitive and how to export the Netscape-format file. The macOS Apple Silicon `.app` and `.dmg` bundle successfully; Windows packaging and automated tests remain pending.

**Sources:** [yt-dlp cookie FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp) and [yt-dlp release files](https://github.com/yt-dlp/yt-dlp#release-files).
