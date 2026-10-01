# 10: Download-only source packages

**What to build:** Allow the producer to import many YouTube URLs into a Download only batch and queue full source-video, preferred subtitle, and original thumbnail downloads into a separate folder per job without running OCR, thumbnail generation, or video rendering.

**Blocked by:** 02: Batch import and balanced background planning; 03: Source downloads and subtitle selection; 06: Queue progress and recovery.

**Status:** complete

- [x] New batches can choose Render (default) or Download only; Download only does not require a background pool or render profile.
- [x] Paste or CSV/TSV batch input resolves each job to a Channel so channel subtitle-language preferences remain active.
- [x] One batch action queues the full source video, original source thumbnail, and preferred creator/automatic subtitle for every ready job.
- [x] No OCR, thumbnail preset export, or FFmpeg render runs in Download only mode.
- [x] Save a usable SRT sidecar when YouTube or a supplied subtitle is available. If no preferred track exists, wait for SRT/VTT upload or an explicit Skip captions choice.
- [x] Keep per-job folders under the selected output root and expose queue progress, cancellation, retry, logs, and a way to open each completed package.
- [x] Existing Render batches keep their current behavior.

**Implementation note:** Download only should reuse batch intake, metadata lookup, channel language preferences, cookies, and the durable queue while skipping background assignment and rendering.

**Verification (2026-10-01):** `python3 -m py_compile worker/worker.py`, `npm run build`, `cargo check`, PyInstaller worker build, and the Apple Silicon `.app`/`.dmg` bundle passed. No tests were added or run.
