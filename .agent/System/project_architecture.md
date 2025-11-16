# Project Architecture

## Overview
StudyBuddy FastAPI powers an internal REST API that pulls down Panopto lectures, extracts MP3 audio, transcribes that audio with ElevenLabs, and now processes uploaded slide decks through a Gemini-powered agent for downstream chunking. Runtime artifacts live under `storage/`, metadata lands in JSON files under `data/`, and a light SQLite catalog (`data/app.db`) tracks courses plus their associated lectures/documents. A separate `chat.py` bootstraps an Agno Agent FastAPI app for experimentation.

## Tech Stack & Structure
- **Language**: Python 3.11+
- **Frameworks/Libraries**: FastAPI, Pydantic, Uvicorn, PanoptoDownloader, ffmpeg CLI, ElevenLabs Speech-to-Text, Google Gemini (via `agno`), Agno AgentOS, sqlite3.
- **Persistence**: Filesystem storage for media + PDFs, JSON metadata (`data/videos.json`, `data/documents.json`, `data/document_descriptions/`), and SQLite (`data/app.db`) for course relationships.
- **Key Modules**:
  - `app/main.py` – FastAPI routes, dependency wiring, and new course + slide-agent endpoints.
  - `app/downloader.py` – Background downloader that streams Panopto MP4s, extracts audio, and triggers transcription.
  - `app/storage.py` – Moves media files into `storage/` and keeps `data/videos.json` in sync.
  - `app/document_storage.py` – Handles PDF uploads plus slide description persistence.
  - `app/pdf_slide_description_agent.py` – Gemini agent that emits structured `SlideContent` objects per page.
  - `app/chunkings/` – Chunking strategies (`TimestampAwareChunking` for transcripts, `SlideChunking` for slide summaries).
  - `app/database.py` – SQLite helper creating `courses`, `course_lectures`, and `course_documents` tables.
  - `app/models.py` – Pydantic schemas (video download, metadata, course creation, etc.).
  - `app/transcriber.py` – ElevenLabs integration with env-based configuration.
  - `scripts/manual_transcribe.py` – CLI helper to smoke-test transcription + timestamps.
  - `tests/test_chunking.py` – Pytest coverage for transcript + slide chunkers.
  - `chat.py` – Optional Agno Agent FastAPI bootstrap.

### Directory Layout
```
app/
├── main.py
├── models.py
├── downloader.py
├── storage.py
├── document_storage.py
├── pdf_slide_description_agent.py
├── chunkings/
│   ├── chunking.py
│   └── slide_chunking.py
└── database.py
data/videos.json
data/documents.json
data/document_descriptions/
data/app.db
data/transcripts/
data/transcript_segments/
storage/videos/
storage/audio/
storage/documents/
```

## Core Workflows
1. **Course Catalog**
   - Clients create/select courses via `POST /api/courses` and `GET /api/courses` before uploading lectures.
   - `CourseDatabase` persists each course (`id`, `name`) and provides helper methods to link lectures/documents for future filtering (e.g., Chroma).
2. **Video Download & Storage**
   - `POST /api/videos/download` validates `stream_url` + `course_id`, hydrates canonical course names, generates `video_id` as needed, then calls `VideoDownloader.download_video`.
   - Downloader threads use `PanoptoDownloader` to fetch MP4s to a temp file, then `LocalStorage.store_video` moves them into `storage/videos` while updating `data/videos.json` with `course_id`/`course_name` and transcript placeholders.
3. **Audio Extraction & Transcription**
   - `_convert_to_audio` runs `ffmpeg` to produce MP3s under `storage/audio`.
   - When an `ElevenLabsTranscriber` is configured, `_transcribe_audio` uploads the MP3, captures word-level timestamps, and `LocalStorage.update_metadata` persists the transcript text under `data/transcripts/{video_id}.txt` plus timestamp segments under `data/transcript_segments/{video_id}.json`. Only the resulting file paths, status, and errors are written back to `data/videos.json`.
4. **Status + Retrieval APIs**
   - `GET /api/videos`, `/api/videos/{id}`, and `/api/videos/{id}/status` combine in-memory job state with persisted metadata (paths, transcript status, timing segments, course info).
   - `GET /api/videos/{id}/file` streams the stored MP4; `DELETE /api/videos/{id}` purges media + metadata.
5. **PDF Uploads & Slide Agent**
   - `POST /api/documents/upload` streams validated PDFs into `storage/documents` and records metadata in `data/documents.json`.
   - `POST /api/documents/{document_id}/slides/describe` runs `PDFSlideDescriptionAgent` (Gemini) page-by-page and saves the resulting structured descriptions to `data/document_descriptions/{document_id}_slides.json`. Metadata for that document is updated with the output path + page counts.
6. **Chunking for Knowledge Ingestion**
   - Transcript ingestion uses `TimestampAwareChunking`, which honors ElevenLabs word segments to produce chunks annotated with `start_ms`, `end_ms`, `chunk_index`, `chunking_strategy`, and the owning `lecture_id`. Course relationships live in SQLite, so we avoid duplicating `course_id` inside Chroma metadata.
   - Slide ingestion uses `SlideChunking`, which emits one chunk per slide by default and splits oversized slides into deterministic parts while preserving `document_id`, `page_number`, and chunk counters (again without embedding the course identifier).
   - `ChromaIngestionService` (see below) consumes these chunks automatically after transcripts or slide descriptions are generated, so manual scripts are only needed for backfills.
7. **Agno AgentOS (Optional)**
   - `chat.py` wires an Agno Agent (Claude + SqliteDb) into AgentOS for experimentation but is separate from the primary FastAPI app.

## Data & Persistence
### JSON Metadata
- **`data/videos.json`** – keyed by `video_id`, storing:
  - `title`, `source_url` (optional)
  - `course_id` (required) and friendly `course_name`
  - `file_path`, `file_size`, `uploaded_at`, `status`, `error`
  - `audio_path`
  - `transcript_status`, `transcript_error`
  - `transcript_path`, `transcript_segments_path` (pointing to per-lecture payloads under `data/transcripts/` and `data/transcript_segments/`)
- **`data/documents.json`** – keyed by `document_id`, storing:
  - `original_filename`, `content_type`, `file_path`, `file_size`, `uploaded_at`
  - `slide_descriptions_path`, `slide_descriptions_updated_at`, `slide_page_count` when the agent runs

- **`data/transcripts/{video_id}.txt`** – raw transcript text per lecture.
- **`data/transcript_segments/{video_id}.json`** – ElevenLabs word-level timestamps for each lecture.
- **`data/document_descriptions/*.json`** – arrays of slide description dicts (`SlideContent.model_dump()`), ready for chunking + vector storage.

### SQLite (`data/app.db`)
Managed by `CourseDatabase`:
| Table | Columns | Purpose |
| --- | --- | --- |
| `courses` | `id TEXT PRIMARY KEY`, `name TEXT NOT NULL` | Canonical course list surfaced to clients.
| `course_lectures` | `course_id TEXT`, `lecture_id TEXT`, PK `(course_id, lecture_id)` | Maps lectures (video IDs) to courses for downstream filtering.
| `course_documents` | `course_id TEXT`, `document_id TEXT`, PK `(course_id, document_id)` | Maps uploaded slide decks to their courses.

Helper methods `link_lecture`, `link_document`, `list_lectures_for_course`, and `list_documents_for_course` let ingestion jobs maintain or query these relationships without mutating chunk metadata (important because Chroma collections are immutable once written).

## API Surface
- `GET /` – simple status message.
- `GET /api/health` – confirms storage paths.
- `POST /api/courses` / `GET /api/courses` – manage/select courses before uploads.
- `POST /api/videos/download` – kick off Panopto downloads; requires `course_id`.
- `GET /api/videos` / `/api/videos/active` – inspect stored metadata or in-flight jobs.
- `GET /api/videos/{video_id}` / `/api/videos/{video_id}/status` – retrieve metadata/progress.
- `GET /api/videos/{video_id}/file` – download stored MP4.
- `DELETE /api/videos/{video_id}` – remove media + metadata.
- `POST /api/documents/upload` – ingest slide PDFs; immediately schedules the slide-description agent + Chroma ingestion in a FastAPI background task.
- `POST /api/documents/{document_id}/slides/describe` – run the Gemini slide agent and persist results.
- `POST /api/chat` – client-facing endpoint that relays prompts to the Agno chat agent backed by Chroma knowledge. `source` accepts `"lectures"`, `"slides"`, or `"combined"` (default) so one question can pull from both datasets.

## External Integrations & Config
- **PanoptoDownloader** – pulled via `requirements.txt`; ensure `yarl`, `multidict`, and `propcache` install cleanly on Python 3.11.
- **ffmpeg** – must be available on `$PATH` for audio extraction.
- **ElevenLabs** – configure `.env.local` or `.env` with `ELEVENLABS_API_KEY`, optional `ELEVENLABS_MODEL_ID`, `ELEVENLABS_LANGUAGE_CODE`, `ELEVENLABS_DIARIZE`, `ELEVENLABS_TAG_AUDIO_EVENTS`.
- **Gemini** – `PDFSlideDescriptionAgent` uses `agno.models.google.Gemini`; provide credentials via Agno’s expected environment variables or configuration.
- **Agno AgentOS** – `chat.py` depends on `agno` packages and optional `agno.db.sqlite`. It is isolated from the primary FastAPI server.

## Chunking Strategies & Testing
1. **TimestampAwareChunking** (`app/chunkings/chunking.py`)
   - Requires `Document.meta_data["segments"] = transcript_segments`.
   - Emits chunks with `chunk_index`, `chunking_strategy="timestamp_aware"`, `start_ms`, `end_ms`, and copies through `lecture_id` plus timing metadata (course identifiers stay in SQLite).
   - Falls back to `chunking_strategy="timestamp_aware_fallback"` when no segments exist.
2. **SlideChunking** (`app/chunkings/slide_chunking.py`)
   - Operates on structured slide descriptions, emitting one chunk per slide or splitting into two when content exceeds `max_chars`.
   - Adds `chunk`, `total_chunks`, and sets `chunking_strategy="slide_chunking"` so downstream filters remain consistent.
3. **Tests** – `tests/test_chunking.py` covers timestamp preservation, fallback behavior, and slide chunk splitting. Run `PYTHONPATH=$PWD python -m pytest tests/test_chunking.py` after modifying chunkers.

These strategies ensure every chunk stored in Chroma (or another vector DB) stays immutable yet queryable by `lecture_id`/`document_id`, enabling course-level filtering via SQLite lookups instead of duplicating mutable metadata inside the embeddings.

### Chroma Ingestion
- `app/chroma_ingestion.py` exposes `ChromaIngestionService`, which loads `.env.local`, converts `Document` chunks into Agno `Knowledge.add_contents` payloads, and sanitizes metadata (no `course_id` is written to Chroma—only `lecture_id` or `document_id`, chunk counters, and optional `user_id` remain).
- The service is instantiated inside `app/main.py`, so completed ElevenLabs transcripts and uploaded PDFs automatically flow into Chroma without manual calls.
- `app/chat_agent.py` wires a `StudyBuddyChatAgent` (Agno `Agent` + `OpenAIChat`) that uses a custom `knowledge_retriever` to merge lecture and slide searches in a single tool call. The FastAPI route exposes a thin wrapper returning markdown replies plus optional references (with `knowledge_source` metadata).
- `scripts/ingest_chroma.py` is now a thin CLI wrapper around the shared service. Provide `--course-id`, `--user-id`, optional `--lectures` and `--documents`, plus the desired `--chroma-path`, `--lecture-collection`, and `--slide-collection`. The script prints how many chunks land in each collection for manual backfills or smoke tests.

## Related Docs
- `.agent/SOP/adding_api_endpoint.md`
- `.agent/Tasks/current_features.md`
- `.agent/README.md`
