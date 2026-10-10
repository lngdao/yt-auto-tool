# YouTube Video Batch Tool — Product and Technical Spec

Status: in-progress
Date: 2026-09-28
Project: /Users/longdao/Projects/youtube-video-batch-tool
Domain glossary: ../../CONTEXT.md
Research: ../../docs/research/implementation-landscape.md

## Problem Statement

The user repeats the same production workflow across many YouTube channels and videos:

1. Fetch source media, thumbnail, and available subtitles.
2. In Premiere, place the selected background video under the YouTube source, remove the source picture, and keep the source audio.
3. Add and style captions.
4. Export the finished video, commonly at 720p for faster turnaround.
5. Edit or replace the thumbnail separately.

The work grows with the number of channels and videos. The difficult part is preserving the intended relationship between each URL, its channel, channel-specific background pool, subtitle language and appearance, output profile, and thumbnail style. A fixed number of channels or a global background rotation cannot express the user's workflow.

## Solution

Build a local desktop app for Windows and macOS. The user can manage any number of channel profiles, enter mixed batches, preview and edit each job's assignments, and process jobs in a queue. Tauri v2 provides the desktop shell and native file access; React/TypeScript provides the UI; a Python worker coordinates yt-dlp, FFmpeg, and thumbnail OCR.

The default video pipeline downloads YouTube audio only, selects a background video, loops or trims that background to the complete audio duration, burns the chosen captions, and exports an H.264 MP4 plus an SRT sidecar. Downloading the full YouTube video remains an explicit option. A separate Download only batch mode collects the full source video, preferred subtitle, and original thumbnail into a per-video folder without rendering or processing the thumbnail. Output profiles include 720p, Match background, and user-defined profiles.

Thumbnail handling is independent of video rendering. Auto mode downloads the actual YouTube thumbnail, recognizes its text with OCR, lets the user correct the text, and renders that text with a complete thumbnail preset. Manual mode saves the source thumbnail for external editing; Skip omits thumbnail work.

## User Stories

### Channel profiles and libraries

1. As a producer, I want to create any number of channel profiles so that the app supports growth beyond a fixed set of channels.
2. As a producer, I want to assign a background pool to one or more channels so that each job can only receive an appropriate background.
3. As a producer, I want to share background pools and thumbnail preset groups across selected channels so that I do not have to duplicate reusable assets.
4. As a producer, I want to set subtitle languages, subtitle appearance, thumbnail mode, thumbnail preset group, output profile, and output folder as channel defaults.
5. As a producer, I want to hide a channel without deleting its batch history or assets.
6. As a producer, I want to see missing background files and relink them before rendering.

### Batch intake and planning

7. As a producer, I want to paste many URLs under a selected channel so that every pasted URL receives that channel explicitly.
8. As a producer, I want to import a CSV or TSV containing channel and URL columns so that one batch can contain any number of channels.
9. As a producer, I want rows with unknown channels or invalid URLs flagged before processing so that a job never silently receives the wrong channel or background pool.
10. As a producer, I want duplicate URLs detected and reviewable so that accidental duplicate work can be removed.
11. As a producer, I want to see metadata and the exact background, subtitle, output profile, and thumbnail preset planned for each video before I start the batch.
12. As a producer, I want to change one or many assignments in the review table so that I can correct automatic choices efficiently.
13. As a producer, I want background and thumbnail preset pools to balance usage across batches within each channel so that their long-term use stays even.
14. As a producer, I want adjacent jobs to avoid the same pool item where possible so that the sequence varies naturally.
15. As a producer, I want retry to preserve the assignments already confirmed for a job so that a retry does not silently change the visual result.

### Source media and captions

16. As a producer, I want audio-only download by default so that jobs avoid downloading unused source video data.
17. As a producer, I want an option to download the full YouTube video when I need it for a separate workflow.
18. As a producer, I want channel-level ordered subtitle language preferences and job-level overrides so that each job uses the right language.
19. As a producer, I want a creator-provided YouTube subtitle track preferred over an automatic track in the same preferred language.
20. As a producer, I want to provide an SRT or VTT when YouTube has no track matching my preferred languages, or explicitly skip captions.
21. As a producer, I want a job without a matching track to wait for my file-or-skip decision so that the app never invents captions or silently chooses an unrelated language.
22. As a producer, I want subtitle text burned into the MP4 and an SRT sidecar so that the captions appear consistently and remain separately editable.
23. As a producer, I want a static subtitle preview with demo text so that I can tune appearance without opening a video editor.
24. As a producer, I want to adjust subtitle font, size, color, background, outline, shadow, alignment, and position so that captions suit each channel.

### Video output

25. As a producer, I want the source audio preserved in full and paired with the chosen background so that the final video follows the existing Premiere workflow.
26. As a producer, I want short backgrounds looped and long backgrounds trimmed to the audio length so that video and audio end together.
27. As a producer, I want a 720p profile that uses the assigned background's frame rate so that I can export a smaller video quickly while keeping motion cadence.
28. As a producer, I want a Match background profile that uses the assigned background's native dimensions and frame rate.
29. As a producer, I want custom output profiles so that I can specify a different resolution or frame rate when needed.
30. As a producer, I want aspect-ratio mismatches detected before rendering and a choice of output frame and fit mode so that the app does not unexpectedly crop or letterbox my background.
31. As a producer, I want a job or bulk fit choice for crop-to-fill or contain/pad so that I can correct one mismatch or apply the same choice to similar jobs.

### Thumbnail handling

32. As a producer, I want auto mode to use the downloaded source thumbnail as the OCR input rather than the YouTube title so that generated text reflects the actual thumbnail.
33. As a producer, I want to review and correct OCR text before rendering so that recognition mistakes do not become final thumbnail text.
34. As a producer, I want OCR languages configured per channel so that recognition can match the text used by that channel.
35. As a producer, I want empty or low-confidence OCR results sent to manual review so that unreadable text is not exported automatically.
36. As a producer, I want each thumbnail preset to contain a complete background, font, colors, and layout so that shuffled combinations remain intentionally designed.
37. As a producer, I want complete thumbnail presets balanced across jobs and batches so that styles are distributed evenly.
38. As a producer, I want to choose shared, selected-channel, channel-specific, batch, or job-level preset groups so that thumbnails can vary globally or by channel.
39. As a producer, I want Manual mode to save the source thumbnail without changing it so that I can edit it in Canva or another app.
40. As a producer, I want Skip mode to omit thumbnail work so that I can finish the video independently.

### Queue and local workflow

41. As a producer, I want per-job and per-batch progress, logs, cancel, and retry so that I can manage large runs.
42. As a producer, I want one failed job not to stop unrelated jobs.
43. As a producer, I want job files and configuration stored locally so that private source media is not uploaded to a hosted service.
44. As a producer, I want to reopen the app and recover the batch plan and completed artifacts so that interruptions do not erase work.
45. As a producer, I want to open an output folder from a job so that I can quickly inspect or continue editing a result.
46. As a producer, I want a launch splash to verify the bundled media tools and automatically update yt-dlp and Deno before opening the workspace so that YouTube extraction starts with a current, usable toolchain.
47. As a producer, I want to select a local Netscape-format cookies.txt file once so that every yt-dlp request can use my YouTube session when required.
48. As a producer, I want to create a Download only batch so that many full YouTube videos, their preferred subtitle files, and original thumbnails are saved into separate folders for editing in Premiere later.

## Implementation Decisions

### Product boundary

- The application is local-first and does not upload source audio, background videos, subtitles, or thumbnails to a cloud service.
- The startup splash validates the bundled FFmpeg/ffprobe capabilities, Tesseract OCR models, and worker. It automatically fetches current stable yt-dlp and Deno assets from their official GitHub releases when missing or out of date, verifies SHA-256 and executable versions, and stores updates in app data without modifying the app bundle.
- The normal workspace stays hidden until local dependency validation and yt-dlp/Deno update checks succeed. Network or verification errors remain on a retryable startup screen.
- YouTube cookies are optional and configured globally. The app stores only the selected local path and passes it to yt-dlp; it does not copy, upload, or log cookie contents.
- It is a repeatable batch production tool, not a general-purpose timeline editor.
- A user can still open source assets and outputs in Premiere for exceptions.
- Video rendering and thumbnail processing are independent job pipelines. A thumbnail review or error does not block video rendering.
- Batches have a workflow mode: Render (the existing default) or Download only. Download-only batches need a valid Channel for subtitle-language preferences but do not require a background pool, output profile, thumbnail preset, OCR, or render step.
- A Download-only batch can fetch full video plus audio or audio only. Full video can optionally be capped at 1080p, 720p, 480p, or 360p; the choice applies to all jobs added by a queue action.
- Download-only work also fetches the source thumbnail regardless of thumbnail Auto/Manual/Skip settings and the preferred creator or automatic subtitle track. Each package includes a UTF-8 `title.txt`, preserves the downloaded YouTube caption file, and writes a Premiere-friendly `captions.srt`; a supplied SRT/VTT is copied into the package and normalized to the same SRT sidecar. If no preferred-language track exists, the job waits for a supplied SRT/VTT or an explicit Skip captions choice.
- Each download-only job gets its own folder under `output root / channel display name / video N`, with N following import order per channel. If a numbered folder already contains files, the queue allocates the next available number; deleting finished video folders lets the sequence start over. Batch names and IDs are not added as extra directories.
- The output root can be set once as an application default in Settings or overridden per Batch. Each queue task snapshots the effective root when it is added.

### Core domain and configuration

- Use the terms Channel, Batch, Video job, Background pool, Balanced shuffle, Subtitle source, Subtitle language preference, Source thumbnail, Thumbnail text, Thumbnail preset, Thumbnail mode, Output profile, and Output video as defined in CONTEXT.md.
- A Channel is a reusable profile. It can own defaults and share asset or preset groups with other channels.
- A Batch contains jobs from any number of channels. Each Video job has an explicit channel before it is ready.
- Configuration precedence is job override, batch override, channel default, then application default.
- Output-root precedence is Batch override, then application default; when neither exists, ask once and save the choice to that Batch.
- When a batch is confirmed, each job stores a snapshot of its selected assets and profiles. Editing a channel later does not silently mutate a confirmed or completed job.

### Channel profiles

Each channel profile stores:

- Display name and filesystem-safe slug.
- Active or hidden state.
- Background pool and its assignment policy.
- Ordered subtitle language preferences.
- Subtitle appearance preset.
- Default output profile.
- Thumbnail mode, preset group, and OCR language list.
- Output root and naming preferences.

The app can create, edit, duplicate, hide, and delete profiles. Deleting a profile requires a review of its history and does not implicitly delete completed output or shared assets.

### Batch intake

- Support pasting multiple URLs under a selected channel.
- Support CSV/TSV import with at least channel and URL columns.
- Import review reports blank rows, malformed URLs, unknown channels, missing required configuration, and duplicate URLs.
- A job without a valid channel or usable background is not ready to run.
- The job table groups and filters by channel, status, subtitle, thumbnail mode, and error.
- Users can reorder jobs within a channel. The order used by Balanced shuffle is explicit and stored.

### Background library and assignment

- Background videos are local file references. Store their path, duration, dimensions, frame rate, codec when readable, channel/group associations, availability, and a representative preview frame.
- A pool may be channel-specific or shared among selected channels.
- A Video job gets one assigned background before rendering. The user sees and can override that assignment.
- Balanced shuffle operates per channel and pool, continues its usage history across batches, evens out assignments over time, and avoids adjacent repeats where possible.
- Persist the assignment ledger and random seed/tie-break order. A retry reuses the stored assignment and does not consume another pool turn.
- Users can explicitly rebalance or assign items manually. Rebalancing is a visible action and updates the preview; it never happens silently after a confirmed batch.
- Asset loss is detected before render and requires relinking or choosing a replacement.
- Audio length determines the output duration. A short background loops; a long background is trimmed.

### Subtitle source and selection

- Inspect available YouTube subtitle tracks without downloading the full source video.
- Use job overrides first, then the Channel's ordered subtitle preferences; if neither is set, use the video's language reported by yt-dlp.
- For each preferred language, prefer a creator-provided track; use an automatic YouTube track only if no creator track is available for that language.
- Continue to the next preferred language when neither track type is available for the current language.
- Do not silently choose a YouTube subtitle outside the configured preferences or the detected video-language fallback.
- If no matching YouTube track exists, the job enters a needs-subtitle decision state. The user may attach an SRT/VTT file or choose Skip captions.
- A supplied file is a fallback when YouTube has no matching preferred-language track. If a matching YouTube track exists, the app uses that YouTube track.
- Do not generate subtitles with Whisper in the MVP.
- Normalize selected timed captions for the render pipeline and create an SRT sidecar. Preserve the original downloaded or supplied subtitle artifact as a source artifact when configured.
- For YouTube VTT tracks with inline word timestamps, remove karaoke markup and roll-up duplicates while preserving the ordered word sequence. Group timed words into readable SRT cues; a character-limit split is allowed only after the current cue has at least 1.2 seconds, so words sharing a timestamp cannot create overlapping flash cues. Non-karaoke timed SRT/VTT cues keep their source timing.
- Store selected language, origin (creator, automatic, or supplied file), and caption decision in the job snapshot.
- Subtitle timing remains aligned because the complete source audio is kept. Any later trim or offset feature must transform subtitle timing as well.

### Subtitle appearance and preview

- A Subtitle preset controls installed font family, bold, size, text color, background enable/color/opacity, outline/box width, shadow offset, nine-point anchor alignment, and horizontal/vertical position.
- A shared Subtitle preset is a reusable library item; it is not automatically active. Each job uses its explicit preset override, then its Channel's default preset, then the built-in default. A shared preset can be selected as a Channel default or as a per-job override.
- The font dropdown lists installed font families. A saved font that is unavailable on the current machine remains visible with a warning because the renderer may substitute a fallback.
- Reset restores the built-in style values in the editor; the user must save to persist them.
- Provide an editable demo string in a static frame preview. The preview does not require a video or timeline.
- The preview supports multi-line text, selectable aspect ratios, and a 720-based reference frame. Position percentages locate the ASS anchor; center-middle uses the center of the entire caption block, so wrapping a long caption must not move that anchor. For a different render resolution, pixel-sized font and outline settings may have a different relative size.
- Use the same subtitle rendering rules as the final render where practical. FFmpeg burns captions through its subtitles/libass path; the runtime must check that the packaged FFmpeg includes required subtitle support.
- Use ASS automatic smart wrapping (WrapStyle 0) with 6% horizontal margins. Background-enabled styles use an opaque box whose width control is padding; background-disabled styles use that width as a glyph outline. Convert FFprobe JSON stdout as UTF-8 so Unicode media paths on Windows remain readable.
- Support Unicode and Vietnamese text. Warn about missing fonts and show the fallback font used.
- Store style in a reusable preset and convert it to an FFmpeg-compatible subtitle style for final rendering.

### Output profiles and frame handling

- Output profiles are reusable sets of video dimensions, frame rate, video/audio encoding choices, and quality/speed preference.
- Include these profiles:
  - 720p: 1280×720 output frame; use the assigned background video's frame rate.
  - Match background: use the assigned background video's native width, height, and frame rate.
  - Custom: user-set dimensions and frame rate.
- H.264 MP4 with AAC audio is the default container/codec combination. Preserve the complete source audio content and end the video at its duration.
- The source YouTube picture is never used in the output video by default; the selected Background pool asset supplies all output pictures.
- Before rendering, probe the assigned background and compare its aspect ratio with the selected output frame.
- When a mismatch is found, show the background frame and profile frame in batch review. Let the user choose whether the output canvas follows the selected profile or the background's aspect ratio.
- If the output canvas and background still have different aspect ratios, let the user choose crop-to-fill or contain/pad. Crop-to-fill fills the full canvas and may cut edges; contain/pad keeps the full image and may leave empty bars.
- Allow the mismatch choice per job and bulk application to selected jobs. Preview the resulting fit before confirming the batch.
- Record the selected canvas and fit mode in the job snapshot so retry is deterministic.
- Use automatic encoder detection where the packaged FFmpeg supports it, with an explicit software fallback. Do not claim a universal speed winner between hardware and software encoding.
- Provide a balanced quality/speed default and make output profile settings visible. Exact speed and file size depend on the user's hardware, source frame rate, filters, and selected quality.

### Thumbnail flow

- Thumbnail mode is independent from video rendering and can be set at channel, batch, or job level.
- New channels default to Auto. Users can choose Manual or Skip at channel, batch, and job level.
- Auto:
  1. Download the source thumbnail image with yt-dlp.
  2. Run OCR on that image using the channel's configured OCR languages.
  3. Show recognized text and confidence for the user to edit and confirm.
  4. Assign a complete Thumbnail preset from the applicable pool.
  5. Preview and export a new PNG, keeping the source thumbnail unchanged.
- Thumbnail text comes from OCR of the source thumbnail; it does not default from the YouTube video title.
- Treat average OCR word confidence below 0.55 as uncertain and mark the thumbnail as needing manual review. Keep the threshold conservative until calibrated against representative thumbnails; the video job remains free to render.
- A Thumbnail preset includes a complete solid or linear-gradient background, font, text color/weight, outline or shadow, alignment, line breaks, position, and fit rules.
- Preset pools can be shared globally, assigned to selected channels, owned by one channel, or overridden on a batch/job.
- Balanced shuffle distributes complete presets (not independent background/font combinations) across jobs and across batches per channel.
- Render a 1280×720 PNG from the complete preset with Pillow. Keep the downloaded source thumbnail as a separate, unchanged artifact; no Canva API or SVG conversion service is required.
- Manual saves the original thumbnail into the job folder for editing elsewhere and marks it as manual work. Skip performs no thumbnail download, OCR, or generation.
- Thumbnail work can run in its own queue pipeline without downloading the YouTube audio or waiting for video rendering. Auto mode stops after OCR so the user can review/edit the text; confirming it resumes PNG generation. Manual mode queues the original image download only.
- Do not inpaint or preserve the source artwork in Auto mode; Auto rebuilds the simple solid/gradient background from the selected preset. The source image remains available as a reference.
- The OCR confidence threshold should start conservatively and be tuned against representative thumbnails. Failed/ambiguous OCR always has a manual path.

### Queue, job states, and recovery

Video and thumbnail progress are tracked independently.

Video job states:

- draft
- needs_channel
- needs_config
- needs_subtitle_decision
- ready
- downloading
- preparing_subtitles
- rendering
- completed
- failed
- cancelled
- interrupted

Thumbnail states:

- not_requested
- source_saved
- needs_manual_review
- queued
- generating
- completed
- failed

- Display progress per job and batch. Use yt-dlp progress hooks for downloads and FFmpeg progress output for rendering.
- Store a per-job log and show a short actionable error with expandable technical details.
- Allow retry of a failed step when its inputs are still valid, cancellation of active work, and running selected jobs.
- Queue concurrency defaults to one active job and can be changed from 1 to 4. The scheduler updates its limit while running; a single Video job cannot run both its video and thumbnail pipelines at the same time.
- A job failure does not prevent unrelated jobs from running.
- On app restart, mark active subprocess work interrupted. Keep confirmed assignments and artifacts; let the user resume or retry from the last valid stage.
- Deleting a Batch requires confirmation, is blocked while any job is actively running, removes its local history, and never deletes downloaded output files.
- Re-running an already completed step must not redownload or rerender valid artifacts unless the user explicitly requests it.

### Output artifacts and local data

Suggested folder layout:

- output / batch-name / channel-name / video-title_video-id / final.mp4
- output / batch-name / channel-name / video-title_video-id / captions.srt
- output / batch-name / channel-name / video-title_video-id / source-audio
- output / batch-name / channel-name / video-title_video-id / source-thumbnail
- output / batch-name / channel-name / video-title_video-id / generated-thumbnail.png
- output / batch-name / channel-name / video-title_video-id / job manifest

The actual artifacts present depend on the job's selected modes. File names are sanitized and include video ID to avoid collisions. The user can set the output root and naming template, open job/batch folders from the UI, and choose whether to keep or remove temporary files after success. Temporary cleanup never removes original library assets.

- Store Channel, Batch, Video job, MediaAsset, SubtitlePreset, ThumbnailPreset, PresetGroup, OutputProfile, JobArtifact, assignment history, and logs locally in SQLite and the filesystem.
- The database records asset availability and reports missing paths without deleting batch history.
- Keep logs and job manifests free of cookies and credentials.

### Desktop architecture and target platforms

- Use Tauri v2 as the desktop shell from the start. Do not make a browser-only local web release the primary product.
- Use React and TypeScript for the interface.
- Use a Python worker sidecar for batch orchestration, job state, yt-dlp, FFmpeg, and OCR coordination.
- Bundle and invoke native media/OCR tools through narrowly scoped process interfaces using argument arrays, not shell interpolation.
- Bundle yt-dlp with a compatible Deno JavaScript runtime and pass Deno explicitly to yt-dlp so YouTube extraction does not depend on another user-installed runtime.
- Include FFmpeg with `libx264`, AAC, and the `subtitles`/libass filter; probe those capabilities and report the missing encoder/filter when unavailable.
- Bundle Tesseract with the English and Vietnamese fast LSTM models (`eng`, `vie`). If a channel selects a language model not present in the package, explain the missing model and send thumbnail text to manual review.
- Use a local SQLite database. Tauri native dialogs support selecting background assets and output folders.
- Build the first platform targets as Windows x64 and macOS Apple Silicon (arm64). Mac Intel support is deferred.
- The worker and tool binaries are packaged for each target. The installer can be developed before code signing/notarization credentials are available; signing requirements must be addressed before external distribution.
- Pin packaging tool versions and verify downloaded yt-dlp/Deno artifacts by SHA-256. Emit a per-target manifest with versions and hashes; run a local FFmpeg/subtitle/OCR fixture smoke check in native CI for both supported targets.
- Keep Tauri-to-worker requests/events stable and explicit: create/import a batch, preview assignments, confirm a batch, start/cancel/retry jobs, and receive state/progress/artifact updates.

### Error handling

| Condition | User-visible behavior |
|---|---|
| Invalid or inaccessible URL | Keep the input row and report validation/download details; allow edit or removal |
| Missing channel or configuration | Mark the job as needing attention and prevent start |
| No audio track | Fail the video pipeline with a source-specific message |
| No YouTube caption in a preferred language | Ask for SRT/VTT or offer Skip captions |
| Invalid supplied subtitle | Keep the job waiting for a corrected file or Skip decision |
| Missing/moved background asset | Block render and offer relink or replacement |
| Background/profile aspect mismatch | Show source dimensions, selected frame, and fit choices before confirmation |
| FFmpeg lacks H.264 or subtitle/libass support | Report the missing capability and prevent a silent incompatible output |
| Hardware encoder missing | Use the configured software fallback and record the encoder used |
| Render fails | Preserve valid inputs and logs; allow retry from render |
| OCR empty or low confidence | Mark needs_manual_review and leave video processing independent |
| Thumbnail generation fails | Mark only thumbnail failed; retain completed video output |
| Low disk space | Warn before queue start when detectable and preserve completed jobs |
| User cancels | Stop the current subprocess, record cancellation, and retain safe completed artifacts |

### Non-functional requirements

- Keep source media, job data, and output local; no upload to a hosted processing service.
- Keep the UI responsive while workers download or render.
- Never interpolate user-controlled strings into shell commands.
- Scope sidecar capabilities to only the tools and file locations required.
- Support Unicode in channel names, titles, subtitles, thumbnail text, and output names.
- Sanitize filesystem names and retain stable IDs in job manifests.
- Provide cancel, retry, logging, and recoverable job state.
- Do not write cookies or credentials into logs or manifests.
- Show dependency readiness for yt-dlp, FFmpeg/libass, and OCR.
- Provide UI in Vietnamese initially; keep strings structured for later localization.

### User interface areas

- Batches: create/import, validate, review, confirm assignments, queue, progress, logs, retry, and output links.
- Channels: manage defaults, preferred subtitle languages, OCR languages, pools, preset groups, and output profile.
- Backgrounds: select/import files, preview frames, inspect dimensions/FPS, and manage channel/group membership.
- Subtitle presets: font/style controls and a static demo preview in the selected output frame.
- Thumbnail presets: solid/gradient background, font/layout controls, sample text preview, and pool membership.
- Settings: output/temp folder, bundled-tool readiness, concurrency, and output profile defaults.

Batch review uses a dense table grouped by channel, with search/filter and multi-select. Each job row shows title/ID, duration, channel, assigned background, subtitle language/source/status, subtitle preset, output profile, thumbnail mode/preset/status, and video status. Mismatch alerts and OCR/manual-review states appear on their job rows. Bulk actions show how many jobs will change.

### Data model

- Channel: identity, active state, background pool, subtitle preferences/preset, thumbnail mode/preset group/OCR languages, output profile, output root.
- MediaAsset: path, media kind, metadata, availability, and channel/group memberships.
- Batch: name, created date, state, import source, job ordering, shared overrides, confirmed settings snapshot.
- Video job: batch/channel IDs, URL/video ID, metadata, order, assigned assets and profiles, subtitle selection, thumbnail mode, output canvas/fit, state, artifacts, error/log references.
- SubtitlePreset: font, size, colors, background, outline, shadow, alignment, position, margins, and wrapping.
- ThumbnailPreset: background type/colors, font, text style, complete layout, and fit rules.
- PresetGroup: item ordering, scope, assignment mode, and shuffle state.
- OutputProfile: dimensions or Match background behavior, frame rate policy, codec, audio settings, and quality preference.
- JobArtifact: type, path, size, checksum when available, and validity state.

### Acceptance criteria

#### Channels and batches

- The user can create more than six channel profiles and can hide/reactivate profiles without losing history.
- A batch can mix any number of channels through per-channel paste or CSV/TSV.
- A row with an unknown channel cannot run until explicitly mapped.
- Each job displays its planned background, subtitle, output profile, and thumbnail mode/preset before batch confirmation.
- Shared pools and per-channel pools both work; a job-level override remains visible.

#### Balanced assignment

- Background pools and complete thumbnail preset pools balance by channel across batches.
- Adjacent jobs avoid repeating the same item when the pool allows it.
- Batch confirmation persists the assignment ledger and per-job snapshot.
- Retry produces the same assignment.
- Explicit rebalance changes are shown before confirmation and do not mutate completed jobs.

#### Video and subtitle

- Audio-only is the default download mode; full source video is an explicit option.
- A rendered job uses the full YouTube audio and its assigned background, looped or trimmed to the audio duration.
- 720p uses a 1280×720 frame and background FPS; Match background uses the background's native dimensions and FPS.
- Custom output profiles can be created and selected.
- Profile/background aspect mismatch is detected before render and exposes canvas and crop/contain choices per job and in bulk.
- If captions are selected, they are burned in and an SRT sidecar is produced.
- The language selection honors the channel/job preference order, selecting creator subtitles before automatic captions in each language.
- No matching track requires supplied SRT/VTT or an explicit Skip captions decision; no Whisper transcription is run.
- Static subtitle preview updates for font, size, color, background, position, and demo text.
- Failures in caption loading or rendering are visible and actionable.

#### Thumbnail

- Auto, Manual, and Skip modes can be selected at channel, batch, and job level.
- Auto fetches the source thumbnail, OCRs that image, allows correction, applies a complete preset, and exports a PNG without overwriting the source.
- Auto never uses the source video title as the thumbnail text default.
- OCR language is configurable per channel; empty/low-confidence results require manual review.
- Balanced shuffle works on complete thumbnail presets and can be scoped across selected channels.
- Manual saves the source thumbnail and does not block video completion.
- Skip performs no thumbnail work.

#### Queue and persistence

- Users can monitor per-job and batch progress, inspect logs, cancel, and retry.
- Failure of one job does not stop independent jobs.
- Restarting the app recovers job states, confirmed assignments, and valid artifacts.
- Output artifacts are separated by batch, channel, and video ID, with a manifest sufficient to reproduce the selected configuration.

#### Startup and YouTube access

- A startup splash blocks the workspace while it checks FFmpeg/ffprobe capabilities, Tesseract, and OCR models.
- Missing pinned OCR models are downloaded from the packaged manifest revision and hash.
- The splash checks the official stable yt-dlp and Deno releases on every launch, downloads missing or older binaries, verifies SHA-256 and executable version, and installs them into app data before opening the workspace.
- If GitHub is unreachable or an asset cannot be verified, the app remains on a retryable error splash.
- Settings can save/clear one global cookies.txt path; all yt-dlp metadata, media, subtitle, and thumbnail requests use it when configured.
- A missing cookie file or a file without the Netscape cookie header is reported before yt-dlp starts. Cookie contents stay in the user-selected local file and never enter app logs or manifests.

## Testing Decisions

### Agreed seams

The primary behavioral seam is the public interface between the Tauri application and the Python worker. Tests should exercise visible requests and returned events/state rather than private classes or database internals.

- Batch seam: import rows, preview assignments, confirm a batch, and verify explicit channel/background/preset assignments and stable history.
- Job seam: start, cancel, retry, and inspect progress/artifacts/errors through the worker interface.
- Render seam: run a tiny local fixture through FFmpeg and verify the output frame, complete audio duration, burned caption, and SRT sidecar.
- Failure seam: use controlled fake tool responses for download, OCR, and render failures and verify the job state and recovery path.
- Thumbnail seam: use fixed thumbnail images and deterministic OCR responses to verify edit/review state and generated PNG artifact behavior.
- UI smoke: validate the critical Tauri flow of selecting an output/background folder, importing a batch, reviewing it, and starting a job.

Worker tests use the public Tauri-to-worker JSON interface and local fixtures or fake external-tool adapters where deterministic behavior is needed; ordinary tests do not contact YouTube. A small real FFmpeg integration fixture is retained because only actual rendering can prove codec/filter integration. Startup release checks should use injected release metadata/download responses so they never contact GitHub in ordinary tests.

## Out of Scope

- Replacing Premiere with a timeline editor.
- Automatically publishing videos or thumbnails to YouTube.
- Cloud processing, account sync, or multi-user collaboration.
- Whisper transcription or any other automatic subtitle generation in the MVP.
- Automatically rewriting, translating, or generating thumbnail text with AI.
- Using the YouTube video title as a substitute for thumbnail OCR text.
- Preserving complex source-thumbnail artwork while removing or inpainting its text in Auto mode.
- General-purpose graphic design layers and freeform image editing.
- Automatic browser cookie extraction or account login. The user may select an already exported local cookies.txt file.
- Premiere project interchange, transition/motion-graphics editing, and automated social posting.
- Mac Intel build in the first platform target.

## Further Notes

- The detailed implementation research is in docs/research/implementation-landscape.md. It covers yt-dlp, FFmpeg, Tesseract OCR, Pillow thumbnail rendering, Tauri sidecars, and the limits of general FFmpeg vs Media Encoder speed claims.
- The product decision is to use creator YouTube subtitles before automatic tracks within the configured language preference list; Whisper is excluded from the MVP. User-supplied SRT/VTT is a fallback only when no matching YouTube track exists.
- Research does not establish that FFmpeg is always faster than Media Encoder. Hardware and software encoders are detected and measured on the target machine; output profiles make speed/quality choices explicit.
- OCR confidence thresholds require calibration using thumbnails representative of the user's actual channels. Until calibrated, uncertain results go to manual review.
- The working feature name is YouTube Video Batch Tool.
