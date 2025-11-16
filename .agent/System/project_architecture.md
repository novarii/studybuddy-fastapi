# Project Architecture

## Overview
StudyBuddy FastAPI exposes a REST API that downloads Panopto videos, extracts MP3 audio, and transcribes that audio with the ElevenLabs Speech-to-Text API. Downloads are tracked in local JSON metadata and mirrored on disk under `storage/videos` and `storage/audio`. A separate `chat.py` entry bootstraps an Agno Agent-based FastAPI app for experimentation.

## Tech Stack & Structure
- **Languages**: Python 3.11+
- **Frameworks/Libraries**: FastAPI, Pydantic, Uvicorn, PanoptoDownloader, ffmpeg CLI, Requests, python-dotenv, ElevenLabs Speech-to-Text REST API, Agno AgentOS (in `chat.py`).
- **Persistence**: Local filesystem (`storage/videos`, `storage/audio`, `storage/documents`) plus JSON metadata (`data/videos.json`, `data/documents.json`). No relational DB.
- **Key Modules**:
  - `app/main.py` – FastAPI app, routes, and dependency wiring.
  - `app/downloader.py` – `VideoDownloader` orchestrating downloads, ffmpeg conversion, and transcription.
  - `app/storage.py` – `LocalStorage` managing video/audio file moves, metadata JSON, and housekeeping.
  - `app/document_storage.py` – PDF upload handling and metadata management.
  - `app/models.py` – Pydantic schemas for requests and stored metadata.
  - `app/transcriber.py` – ElevenLabs client wrapper that loads `.env.local` / `.env`.
  - `app/chunking.py` – Timestamp-aware Agno chunking strategy built on ElevenLabs word metadata.
  - `scripts/manual_transcribe.py` – Local helper script to call ElevenLabs on arbitrary audio/video clips and inspect timestamp segments.
  - `tests/test_chunking.py` – Pytest coverage that exercises the chunker’s timestamp + fallback paths.
  - `chat.py` – Optional Agno Agent FastAPI bootstrap.

Directory layout:
```
app/
├── main.py
├── models.py
├── downloader.py
├── storage.py
├── transcriber.py
└── document_storage.py
data/videos.json
data/documents.json
storage/videos/
storage/audio/
storage/documents/
```

## Core Workflows
1. **Video Download API**
   - `POST /api/videos/download` receives `VideoDownloadRequest` (URL, optional IDs, metadata).
   - `VideoDownloader.download_video` spawns a background thread, tracks job state in-memory, and uses `PanoptoDownloader.download` to stream to a temp MP4.
2. **Audio Extraction**
   - `_convert_to_audio` runs `ffmpeg -i <video> -vn -acodec mp3` on the temp file.
   - Resulting MP3 is moved to `storage/audio/<video_id>.mp3`.
3. **Speech-to-Text**
   - `ElevenLabsTranscriber.transcribe` posts the MP3 to `POST https://api.elevenlabs.io/v1/speech-to-text`.
   - Responses (status, text, error) are persisted in `data/videos.json`.
4. **Metadata & Retrieval**
   - `LocalStorage.store_video` updates JSON metadata with file paths, sizes, transcript status, etc.
   - `GET /api/videos`, `/api/videos/{id}`, and `/api/videos/{id}/status` read from `VideoDownloader.downloads` plus persisted metadata.
5. **Cleanup**
   - `DELETE /api/videos/{id}` removes MP4/MP3 files and metadata entries.
6. **PDF Uploads**
   - `POST /api/documents/upload` accepts a PDF `UploadFile`, validates MIME type/extension, and streams it to disk.
   - `DocumentStorage.save_document` persists metadata into `data/documents.json` for later retrieval.

## External Integrations & Config
- **PanoptoDownloader**: installed via `requirements.txt` (git dependency) and expects `yarl`, `multidict`, and `propcache` pre-installed (see requirements comments).
- **ffmpeg**: must be installed on the host and resolvable on `$PATH`.
- **ElevenLabs**: configure via `.env.local` or `.env`:
  - `ELEVENLABS_API_KEY` (required for transcription).
  - Optional: `ELEVENLABS_MODEL_ID` (`scribe_v1` default), `ELEVENLABS_LANGUAGE_CODE`, `ELEVENLABS_DIARIZE`, `ELEVENLABS_TAG_AUDIO_EVENTS`.
- **Agno AgentOS**: `chat.py` depends on `agno` packages (not listed in `requirements.txt` yet) for running conversational agents; it exposes its own FastAPI app if needed.

## Metadata Schemas

### `data/videos.json`
Each `video_id` key stores:

| Field | Description |
| --- | --- |
| `video_id` | Unique identifier (auto timestamp if not provided). |
| `title` / `source_url` | Optional descriptors surfaced via API. |
| `file_path` | Absolute path to the stored MP4 in `storage/videos`. |
| `file_size` | Byte size of the MP4. |
| `uploaded_at` | ISO timestamp recording completion. |
| `status` | `downloading`, `completed`, or `failed`. |
| `error` | Failure message when status is `failed`. |
| `audio_path` | Absolute path to MP3 in `storage/audio`. |
| `transcript` | Text returned by ElevenLabs (may be `null`). |
| `transcript_status` | `completed`, `failed`, `skipped`, or `pending`. |
| `transcript_error` | Human-readable transcription error (if any). |
| `transcript_segments` | List of `{text, start_ms, end_ms, confidence, speaker?}` tokens produced by ElevenLabs for downstream semantic search. |

### `data/documents.json`
| Field | Description |
| --- | --- |
| `document_id` | Auto-generated identifier (`doc_<timestamp>`). |
| `original_filename` | Name provided during upload. |
| `content_type` | MIME type (PDF enforced). |
| `file_path` | Absolute path under `storage/documents`. |
| `file_size` | Size in bytes. |
| `uploaded_at` | ISO timestamp. |

## API Surface
- `GET /api/health` – storage sanity check.
- `POST /api/videos/download` – start job; returns `job_id` + `video_id`.
- `GET /api/videos` – list persisted metadata records.
- `GET /api/videos/active` – inspect in-memory download states.
- `GET /api/videos/{video_id}` – fetch metadata (including transcript info).
- `GET /api/videos/{video_id}/status` – blend of live progress + persisted data.
- `GET /api/videos/{video_id}/file` – download MP4.
- `DELETE /api/videos/{video_id}` – remove files + metadata.
- `POST /api/documents/upload` – upload PDF slide decks and persist metadata for later processing.

## Operational Notes
- Background threads run per download; no central queue exists, so long-running ffmpeg/ElevenLabs calls may block additional throughput depending on system resources.
- `LocalStorage.update_metadata` rewrites the JSON file per change; keep file sizes manageable or migrate to a DB if scaling up.
- Ensure `.gitignore` keeps `storage/` and `data/videos.json` out of version control to avoid leaking media.
- If ElevenLabs transcription fails, downloads still succeed with `transcript_status="failed"` and error details saved for debugging.
- `scripts/manual_transcribe.py` reuses `VideoDownloader` + `ElevenLabsTranscriber` to validate credentials and timestamp payloads without triggering Panopto downloads.
- Run `pytest` (after installing `pytest` + `agno`) to execute `tests/test_chunking.py` and guard against regressions in timestamp-aware chunking.

## Transcription Metadata & Agno Chunking

ElevenLabs returns word-level timestamps; `app/transcriber.py` now normalizes those into `transcript_segments` so the system can:

1. **Inspect timestamps quickly** – `python scripts/manual_transcribe.py <path/to/clip>` prints transcript text plus sample `[start_ms -> end_ms]` entries, making it easy to confirm metadata before ingestion.
2. **Chunk for semantic search** – `TimestampAwareChunking` (in `app/chunking.py`) consumes `Document` objects whose `meta_data["segments"]` references `transcript_segments`. It:
   - Cuts chunks when `max_words` or `max_duration_ms` is exceeded.
   - Preserves an `overlap_ms` tail for continuity.
   - Annotates each chunk’s metadata with `start_ms`, `end_ms`, and `chunk_index`.
   - Falls back to simple word-count splitting when timestamp metadata is absent (legacy transcripts).
3. **Test coverage** – `tests/test_chunking.py` verifies both timestamped and fallback chunk output; run `pytest` after modifying chunking parameters or metadata shape.

This metadata enables Agno Knowledge (or any vector store) to return relevant transcript snippets plus the exact millisecond offsets required for frontend deep links.

## Related Docs
- `.agent/SOP/adding_api_endpoint.md`
- `.agent/Tasks/current_features.md`
- `.agent/README.md`
