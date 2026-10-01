# 07: Windows and macOS desktop packaging

**What to build:** The user can install and run the completed desktop app on Windows x64 or macOS Apple Silicon with the Python worker and required media/OCR tools available locally.

**Blocked by:** 06: Queue progress and recovery.

**Status:** in-progress

- [ ] A Windows x64 package and a macOS Apple Silicon package can launch the Tauri app and Python worker.
- [ ] Each package includes or reliably provisions yt-dlp, FFmpeg with H.264 and libass subtitle support, and the configured OCR engine.
- [ ] Native file and folder dialogs work for background libraries and output folders on each target.
- [x] The app reports a clear dependency/capability error if a bundled tool cannot start or lacks a required encoder/filter.
- [ ] A smoke run on each target completes a local fixture render without YouTube credentials.
- [x] Signing/notarization is documented as a prerequisite for external distribution and is not required for local development builds.

**Implementation note:** Added target-native resource staging, pinned yt-dlp/Deno downloads with SHA-256 verification, a PyInstaller one-folder worker, macOS dylib bundling, local fixture smoke checks, and a Windows x64/macOS Apple Silicon GitHub Actions packaging workflow. The worker now passes the bundled Deno path explicitly to yt-dlp and returns actionable errors for an unavailable runtime or missing FFmpeg encoder/filter.

**Verification (2026-09-28):** On this Apple Silicon Mac, `worker/.venv/bin/python -m unittest discover -s worker/tests` passed (34 tests, one skipped because the system FFmpeg lacks libass); the targeted actionable missing-libass test passed. The packaged worker rebuilt successfully. `scripts/smoke_package.py` passed against both the staged tool directory and the final `.app` resource directory, including Deno/yt-dlp startup, worker health, local H.264/AAC + libass render, and OCR. Frontend build, `cargo check`, and the macOS `.app`/`.dmg` build passed; launching the final `.app` started the Tauri process. A direct missing-Deno check returned the expected dependency error.

**Still pending:** The Windows x64 workflow has not run from this local workspace; the native dialogs have not been manually exercised on either OS, and the workflow builds installer artifacts but does not install and launch them. Keep the ticket in progress until Windows packaging and dialog checks are verified.
