# Changelog

All notable changes to this project will be documented in this file.

## v5 – Product‑CGI Reel Maker (2026‑04‑29)

### Added

- Implemented a full product‑CGI reel generation pipeline that runs entirely locally using Pillow and OpenCV.  The new pipeline removes the background from the uploaded product, generates five scene plates (using HuggingFace FLUX when available or a high‑quality gradient fallback), composites the product with realistic shadows, rim lighting and optional reflections, and assembles a polished MP4 with Ken‑Burns motion and rich transitions.
- Added duration selection to the Reel Maker UI.  Users can now choose an approximate length (4 s, 6 s or 8 s) and the backend distributes hold durations evenly across shots to achieve a shorter or longer reel.
- Added a Step 3 card to the Reel Maker page for picking the duration and wired up the form submission to include this value.
- Updated the reel pipeline to accept an optional `duration` parameter and compute per‑frame hold duration dynamically.
- Extended `save_reel_to_media` to forward a custom `hold_duration` to the video assembler.
- Added documentation on environment variables and usage instructions to the README.
- Added this `CHANGELOG.md` to track future changes.

### Removed

- Removed the deprecated classic slideshow reel concept.  The Reel Maker now exclusively generates product‑CGI reels with motion and transitions.

### Changed

- Renumbered the steps in the Reel Maker UI to accommodate the new duration selection.
- Updated the progress bar and pipeline status tracker to reflect the new stage ordering.