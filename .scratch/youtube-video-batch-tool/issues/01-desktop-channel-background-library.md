# 01: Desktop channel and background library

**What to build:** The user can launch the Tauri desktop app, create channel profiles, add local background videos to shared or channel-specific pools, and reopen the app without losing configuration.

**Blocked by:** None (can start immediately).

**Status:** complete

- [x] The Tauri v2 app starts and can communicate with the Python worker through a narrow public request/event interface.
- [x] The user can create, edit, duplicate, hide, and reactivate a Channel.
- [x] The user can select one or more background video files with a native file dialog and assign them to a pool usable by one or more Channels.
- [x] The app probes and displays each background's duration, dimensions, frame rate, and availability when metadata is readable.
- [x] Channel profiles and asset references persist locally and remain available after restarting the app.
- [x] Missing background paths are visible and can be relinked without deleting Batch history.
- [x] Behavioral tests exercise the Tauri-to-worker public boundary and local persistence; they do not target private implementation details.
