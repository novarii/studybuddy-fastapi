# Feature Briefs & Plans

## Panopto Video Download & Storage
- **PRD Summary**: Users submit a Panopto stream URL and optional metadata; the system downloads the MP4, persists it locally, and exposes metadata plus the original file via REST.
- **Implementation Snapshot**:
  - `VideoDownloader.download_video` validates input, tracks job progress, and invokes `PanoptoDownloader`.
  - `LocalStorage.store_video` moves temp files into `storage/videos` and updates `data/videos.json`.
  - API routes in `app/main.py` surface job status (`/api/videos/active`) and persisted records (`/api/videos`).
- **Future Enhancements**:
  - Replace ad-hoc threading with a task queue (Celery / RQ) for better concurrency.
  - Add pytest coverage to prevent regressions in downloader and storage layers.

## Audio Extraction & ElevenLabs Transcription
- **PRD Summary**: For every completed video download, automatically extract an MP3 track, store it, and submit audio to ElevenLabs Speech-to-Text. Persist transcript text and status for retrieval.
- **Implementation Snapshot**:
  - `_convert_to_audio` in `app/downloader.py` runs ffmpeg to create MP3 files stored under `storage/audio`.
  - `ElevenLabsTranscriber` (`app/transcriber.py`) loads `ELEVENLABS_*` env vars, calls `POST /v1/speech-to-text`, and returns transcript data.
  - Metadata now includes `audio_path`, `transcript`, `transcript_status`, and `transcript_error`, exposed via `/api/videos/{video_id}` and `/api/videos/{video_id}/status`.
- **Next Steps**:
  - Streamline error handling by retrying ElevenLabs failures or allowing manual re-transcription.
  - Consider queueing transcription so ffmpeg completion doesn’t block the download thread.

## Related Docs
- `.agent/System/project_architecture.md`
- `.agent/SOP/adding_api_endpoint.md`
- `.agent/README.md`
