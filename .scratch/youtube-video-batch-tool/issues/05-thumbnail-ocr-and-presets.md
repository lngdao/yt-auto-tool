# 05: Thumbnail OCR and preset workflow

**What to build:** The user can choose Auto, Manual, or Skip per Channel/Batch/job; Auto recognizes text from the downloaded source thumbnail and renders it with a complete, balanced Thumbnail preset pool.

**Blocked by:** 03: Source downloads and subtitle selection.

**Status:** complete

- [x] Auto and Manual modes download and retain the source thumbnail; Skip performs no thumbnail work.
- [x] OCR languages are configurable per Channel, and recognized text plus confidence is shown for editing and confirmation.
- [x] Thumbnail text starts from OCR of the source image and never defaults to the YouTube title.
- [x] Empty or low-confidence OCR marks the thumbnail as needing manual review without blocking video rendering.
- [x] The user can create complete presets containing solid/gradient background, font, color, text layout, and fit rules.
- [x] Preset groups can be shared globally, across selected Channels, per Channel, Batch, or job.
- [x] Balanced shuffle assigns complete presets per Channel across jobs/Batches, with visible assignments and per-job override.
- [x] Auto exports a 1280×720 PNG and never overwrites the source thumbnail.
- [x] Manual saves the original image for external editing and marks it as manual work.
- [x] Tests use fixed thumbnail images and controlled OCR responses to verify edit, review, assignment, and export behavior.

**Implementation:** Pillow rasterizes complete solid/gradient presets to PNG. Tesseract OCR is injectable through `TESSERACT_BINARY`; image export is covered by a fixed JPEG and deterministic OCR fixture.

**Verification:** `npm run build`, `cargo check`, and `worker/.venv/bin/python -m unittest discover -s worker/tests -v`. Thumbnail-focused worker tests cover OCR from the source image, editable text, untouched source image, preset balancing across batches, Skip/Manual behavior, and video rendering while OCR is marked for review.
