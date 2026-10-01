# 02: Batch import and balanced background planning

**What to build:** The user can create a Batch for any number of Channels, import URLs with explicit channel mapping, inspect the jobs, and review balanced Background pool assignments before starting work.

**Blocked by:** 01: Desktop channel and background library.

**Status:** complete

- [x] The user can paste many URLs under a selected Channel.
- [x] The user can import CSV/TSV rows with Channel and URL columns and correct unknown or invalid values.
- [x] yt-dlp metadata lookup provides the video ID, title, duration, and source thumbnail reference without downloading the full source video.
- [x] The app flags duplicate URLs and jobs with missing Channel or required configuration.
- [x] Balanced shuffle assigns Background pool items per Channel, continues usage counts across Batches, avoids adjacent repeats where possible, and exposes the planned assignments.
- [x] The user can override assignments per job or for selected jobs and explicitly rebalance before confirming the Batch.
- [x] Confirmed assignments are snapshotted; retry or reopening the Batch does not silently reshuffle them.
- [x] Behavioral tests cover import, validation, assignment balance across multiple Batches, manual override, and stable retry through the public worker interface.
