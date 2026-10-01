# YouTube Video Batch Tool

This context describes how source videos, channel configurations, batches, and visual assets relate in the local production workflow.

## Work organization

**Channel**:
A reusable production profile for one YouTube channel. It owns the channel's defaults for background videos, subtitle appearance, thumbnail styles, and output settings.
_Avoid_: Account, workspace

**Batch**:
One work session containing video jobs for any number of channels.
_Avoid_: Channel batch, fixed-size group

**Video job**:
One source YouTube URL assigned to one channel, with its own selected background video, subtitle choice, thumbnail handling choice, and output.
_Avoid_: Task, item (when referring to a video being processed)

## Media and visual assets

**Background pool**:
The set of reusable background videos available to a channel or group of channels.
_Avoid_: Playlist (when referring to local background video files)

**Balanced shuffle**:
A way to assign items from a pool across batches so their use is as even as possible over time and adjacent jobs avoid the same item when possible.
_Avoid_: Pure random, strict rotation

**Subtitle source**:
A time-coded subtitle track matching the channel or job's preferred language, obtained from YouTube first or supplied by the user when YouTube has no matching track. A job may also proceed without captions when the user chooses to skip them.
_Avoid_: Transcript (when referring to a timed subtitle track)

**Subtitle language preference**:
The ordered list of subtitle languages preferred by a channel, used to select an available subtitle unless a video job overrides it.
_Avoid_: Global subtitle language (when channels may differ)

**Source thumbnail**:
The original thumbnail image fetched for a source YouTube video. It remains available whether the job creates a redesigned thumbnail, leaves it for manual editing, or skips thumbnail work.
_Avoid_: Generated thumbnail

**Thumbnail text**:
The words shown in the source thumbnail, which the user may correct or rewrite before applying a thumbnail style. It does not default to the video's title.
_Avoid_: Video title (when referring to the words intended for the thumbnail)

**Thumbnail preset**:
A reusable visual style containing a background, typography, and text layout. Presets can be used by one video, one channel, a selected set of channels, or a shared group.
_Avoid_: Channel thumbnail (when referring to a reusable style)

**Thumbnail mode**:
The per-job choice to create a redesigned thumbnail, keep the source thumbnail for manual editing, or skip thumbnail handling.
_Avoid_: Thumbnail status (when referring to the user's chosen handling mode)

**Output video**:
The rendered video made from a source video's audio, an assigned background video, the job's chosen subtitle track and appearance, and an output profile.
_Avoid_: YouTube source video (when referring to the rendered result)

**Output profile**:
A reusable set of export choices, such as resolution, frame rate, codec, and quality, selected for a channel, batch, or video job.
_Avoid_: Export preset (when the term could be confused with a thumbnail or subtitle preset)
