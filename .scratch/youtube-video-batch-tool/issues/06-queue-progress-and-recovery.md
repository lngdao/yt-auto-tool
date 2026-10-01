# 06: Queue progress and recovery

**What to build:** The user can run video and thumbnail work independently in a durable queue, monitor it, cancel or retry it, and resume safely after restarting the app.

**Blocked by:** 04: Subtitle preview and video rendering; 05: Thumbnail OCR and preset workflow.

**Status:** complete

- [x] Video and thumbnail pipeline states are tracked independently per job.
- [x] The user can start selected jobs, see per-job and per-Batch progress, inspect logs, and open outputs.
- [x] A failed job does not stop unrelated jobs.
- [x] The user can cancel active subprocess work and retry a failed step from valid local artifacts.
- [x] Retry reuses confirmed assignments and does not repeat completed download/render/OCR work without an explicit request.
- [x] Jobs active during app shutdown are marked interrupted; reopening offers a safe resume/retry path.
- [x] The default render concurrency is one job and is configurable from 1 to 4.
- [x] Tests exercise progress, failure isolation, cancel, retry, and restart recovery through the public worker interface.

**Implementation note:** SQLite stores separate video/thumbnail queue tasks and logs. yt-dlp and FFmpeg progress are persisted; thumbnail jobs can fetch/OCR a source image without fetching audio and pause for text review before the queued PNG export. Worker heartbeat recovery exposes interrupted jobs for retry. Verification: 34 worker tests pass with one FFmpeg/libass test skipped; frontend production build and Rust `cargo check` pass.
