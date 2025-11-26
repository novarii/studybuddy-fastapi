# Task: Audio-Only Download Follow-Ups

## Context
Audio-only downloads are now supported through the `audio_only` flag on `POST /api/videos/download`. When the flag is true, the downloader skips storing the MP4, pulls the AAC track via ffmpeg, saves the MP3 artifact, and records the remote CloudFront/Panopto URL inside the metadata. Clients still ingest transcripts and can poll `/api/videos/*` endpoints, but we need to round off the experience for playback and lifecycle management.

## Open Workstreams
1. **Playback routing**
   - Decide what `/api/videos/{video_id}/file` should do for audio-only entries. Options include redirecting (302) to `remote_video_url`, returning an `audio/mp3` stream instead, or providing a structured error so clients can link users to Panopto.
   - Update the frontend/extension to read `audio_only` + `remote_video_url` and render the appropriate CTA (download audio, open Panopto, etc.).
2. **Metadata ergonomics**
   - Surface `audio_only` and `remote_video_url` inside `storage.list_videos()` responses so admin dashboards can filter and locate remote-only assets quickly.
   - Extend delete logic to skip missing MP4 files without logging warnings (currently benign but noisy once most entries are audio-only).
3. **Operational hardening**
   - Add integration tests (or a CLI smoke script) that exercises both video+audio and audio-only paths to ensure regressions are caught when touching downloader/storage modules.
   - Document the new flag + remote URL semantics in `.agent/System/project_architecture.md` and the public README so contributors know why MP4s might be missing on disk.

## Related Docs
- `.agent/System/project_architecture.md`
- `.agent/SOP/adding_api_endpoint.md`
- `.agent/README.md`
