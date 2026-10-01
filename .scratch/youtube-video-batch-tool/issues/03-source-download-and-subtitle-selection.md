# 03: Source downloads and subtitle selection

**What to build:** The user can fetch the media artifacts needed by a Video job and resolve its subtitle source using the Channel's language preferences.

**Blocked by:** 02: Batch import and balanced background planning.

**Status:** complete

- [x] Audio-only is the default YouTube download; the user can explicitly request the full source video.
- [x] The source thumbnail image is saved for Auto or Manual thumbnail handling.
- [x] Available YouTube subtitle languages and track types are inspected before selection.
- [x] For each preferred language, creator-provided subtitles take priority over automatic captions; the next preferred language is tried when neither is available.
- [x] A job-level language override can replace the Channel preference for that job.
- [x] If no YouTube track matches the preferred languages, the user can attach SRT/VTT or choose Skip captions; the job waits for this decision when neither is selected.
- [x] A supplied subtitle file is used only when YouTube has no matching preferred-language track.
- [x] No Whisper or other automatic transcription is run.
- [x] The job records downloaded artifacts, selected subtitle language/source, and waiting/error state.
- [x] Tests use local fixtures or fake download responses and verify the public job behavior without making network requests.
