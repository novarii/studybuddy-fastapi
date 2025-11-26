# Task: Audio-First Lecture Endpoints

## PRD
### Background
The FastAPI surface under `app/main.py` was built around MP4 delivery: `/api/videos/*` routes expose metadata plus `/file` streams an `video/mp4` payload sourced from `LocalStorage.get_file_path()`. The pipeline in `VideoDownloader` (`app/downloader.py`) always downloads the Panopto MP4, even when callers only need transcripts, and the metadata contract in `app/models.py` marks `file_path` as required. We recently added an `audio_only` mode and `LocalStorage.store_audio`, but clients still need to inspect flags before they can play anything because the API only exposes MP4 files. Nova wants to flip the service to audio-first delivery so every endpoint consistently surfaces MP3 artifacts without bespoke client logic.

### Goals
- Treat MP3 audio as the canonical artifact for `/api/videos` listings, status responses, and `/file` downloads.
- Ensure newly downloaded lectures never persist MP4 files unless explicitly requested, trimming storage pressure and simplifying ingestion/transcription.
- Provide a clean API contract so frontends can download/stream audio without branching on `audio_only` or private metadata fields.

### Non-Goals
- Rebuilding the Panopto downloader itself or removing transcript/Chroma ingestion.
- Shipping a new frontend; this task only updates backend contracts + docs.
- Handling long-term migrations of historical MP4 blobs (they can stay untouched but should still be considered readable).

## Current Pain Points
- `GET /api/videos/{video_id}/file` (`app/main.py:141-159`) refuses to serve anything if there is no MP4 on disk, even when `storage/audio/<id>.mp3` exists.
- `VideoMetadata` in `app/models.py` requires `file_path`/`file_size` and only treats `audio_path` as optional, so audio-only jobs must hack around the schema by stuffing the remote Panopto URL into `file_path` (`app/downloader.py:129-137`).
- `LocalStorage` lacks a `get_audio_path()` helper and only hydrates transcripts when returning metadata, so callers must inspect `audio_path` manually.
- `VideoDownloader.download_video` still downloads MP4s by default, leaving `storage/videos` bloated even if we only expose MP3s.

## Proposed Solution
1. **Schema rename**: Introduce `LectureAssetMetadata` (or keep the class but rename fields) that promotes `audio_path`, `audio_filesize`, and `duration` to first-class fields. Mark `video_path` optional so existing MP4 inventory is still trackable. Update JSON persistence under `data/videos.json` via a lightweight migration script.
2. **Storage API**: Extend `LocalStorage` with:
   - `get_audio_path(video_id)` returning a `Path` if the MP3 exists.
   - `store_audio` returning metadata (`file_size`, `duration` if we can probe via ffprobe) and automatically persisting it.
   - deletion helpers that skip missing MP4s quietly but still remove orphaned MP3/transcript files.
3. **Downloader pipeline**:
   - Default to audio extraction by calling `_download_audio_stream` whenever `audio_only` is true (which should now be the default). Only fetch the MP4 when `video_only=True` or similar.
   - Update status bookkeeping so `self.downloads[job_id]['file_path']` becomes `audio_path` (with `video_path` optional).
   - Ensure transcription always points to the MP3 artifact and ingestion uses the canonical metadata fields.
4. **API surface**:
   - Update `/api/videos` listing + `/status` payloads to return `audio_download_url` (the new `/api/audio/{video_id}` route) and hide MP4-only metadata unless present.
   - Replace `/api/videos/{video_id}/file` with `/api/audio/{video_id}` (keep the old route for backward compatibility but switch it to call the audio handler). Media type should be `audio/mpeg`.
   - Include an `asset_type` flag in responses so future extensions (e.g., transcripts only) stay forward-compatible.
5. **Docs + SOP**: Refresh `.agent/System/project_architecture.md`, `.agent/SOP/adding_api_endpoint.md`, and README sections covering download semantics to explain the audio-first behavior.

## Implementation Plan
1. **Model + metadata update**
   - Edit `app/models.py` to rename `VideoMetadata.file_path` ➜ `video_path: Optional[str] = None` and add `audio_path: str` plus `audio_filesize: int`. Update `VideoDownloadRequest` default to `audio_only=True`.
   - Write a one-off migration script (under `scripts/`) that backfills `audio_path` for existing entries by inspecting `storage/audio/*.mp3` and moving any orphaned `file_path` values into `video_path`.
2. **LocalStorage refactor**
   - Introduce `get_audio_path` + `get_video_path` helpers and update `delete_video`, `list_videos`, and `_hydrate_payload` to load audio-first metadata.
   - When storing audio, measure file size via `Path.stat()` and persist it to metadata.
3. **Downloader pipeline**
   - Make `audio_only` default to `True` inside `VideoDownloader.download_video`, only writing MP4s when a new `download_video(video=True)` flag arrives.
   - Remove assumptions that `metadata.file_path` points to a local MP4; update status dicts, ingestion, and transcript code to reference the new fields.
4. **API contract**
   - Replace `download_video_file` handler with `download_audio_file` under `/api/audio/{video_id}`, returning the MP3 path via `FileResponse`; keep `/api/videos/{video_id}/file` as a thin wrapper.
   - Update `/api/videos` and `/api/videos/{video_id}` responses to surface `audio_url`, `audio_size`, `audio_only`, and optional `video_url`.
   - Adjust tests (under `tests/`), frontend API clients, and dev scripts so they call the new route.
5. **Documentation + release notes**
   - Update `.agent/System` docs + README to describe the new endpoint and metadata contract.
   - Document migration + rollback in `.agent/SOP/adding_api_endpoint.md` or a dedicated SOP entry.

## Testing & Validation
- Unit tests for `LocalStorage` covering store/list/delete when only MP3 exists.
- Integration test for `/api/videos/download` (audio-only) asserting `/audio` returns `audio/mpeg` and that `/file` continues to work for legacy MP4 entries.
- Regression test verifying downloader still kicks off transcription + ingestion using the MP3 artifact.

## Open Questions
- None — audio downloads stay on plain `FileResponse` unless infra changes down the line.

## Frontend Considerations
- Update API client wrappers to hit `GET /api/audio/{video_id}` for playback/download and expect `audio/mpeg` responses.
- Adjust UI labels/buttons from “Download Video” to “Download Audio” and surface an audio badge using the new `asset_type` field.
- Simplify conditional logic: assume audio exists for new entries and only fall back to `video_url` when `asset_type` reports a legacy video.
- Refresh caching/polling layers so they pick up `audio_url` from `/api/videos` responses without extra metadata parsing.
