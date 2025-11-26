# Project Architecture

## Product Goal & Runtime Snapshot
StudyBuddy FastAPI is a backend service for capturing long-form course material (Panopto lectures + PDF slides), enriching it with transcriptions and Gemini-authored slide descriptions, and exposing the knowledge through a retrieval-augmented chat experience. The runtime is intentionally filesystem-first: video/audio/documents, transcripts, and chunk exports live under `storage/` or `data/`, while durable configuration stays inside `.env.local`. Besides the primary FastAPI app, the repo ships an Agno AgentOS sandbox (`chat.py` + `agent/dev_agui.py`) for experimenting with the chat agent outside of StudyBuddy’s REST surface.

```
client (browser extension / CLI) → FastAPI routes (app/main.py)
                        ↙                       ↘
          VideoDownloader threads         BackgroundTasks for PDFs
              ↙             ↘                  ↙             ↘
       storage/videos   storage/audio   storage/documents  data/document_descriptions
              ↓                ↓                  ↓                     ↓
   data/videos.json ↔ LocalStorage   data/documents.json ↔ DocumentStorage
              ↓                                   ↓
     ChromaIngestionService (TimestampAwareChunking / SlideChunking)
              ↓
   Chroma collections (course_lectures + course_slides)
              ↓
      StudyBuddyChatAgent (Agno + OpenAIChat) → FastAPI chat + SSE routes
              ↓
        CourseDatabase (SQLite) = course shells + units/topics + chat history
```

## Tech Stack & Module Guide
- **Runtime**: Python 3.11+, FastAPI + Uvicorn, Pydantic v1, pytest (tests WIP).
- **External services**: PanoptoDownloader CLI, ffmpeg, ElevenLabs Speech-to-Text, Google Gemini via `agno.models.google`, OpenAI Chat (Agno’s `OpenAIChat`), Chroma (via `agno.vectordb.chroma`), dotenv for env hydration.
- **Persistence strategy**: Immutable binaries on disk (`storage/`), JSON metadata (`data/`), SQLite (`data/app.db`) for structured associations + chat history, and Chroma collections for embeddings.

| Module | Responsibility |
| --- | --- |
| `app/main.py` | Hosts FastAPI routes, wires singletons (storage, downloader, chroma ingestor, PDF agent, course DB, chat agent), and registers background tasks for slide processing. |
| `app/downloader.py` | Thin wrapper around `PanoptoDownloader`. Defaults to audio-only jobs, manages temp files, ffmpeg audio extraction, ElevenLabs transcription, ingestion hand-off, and download progress tracked in-memory. |
| `app/storage.py` | Owns `storage/videos`, `storage/audio`, and transcript directories. Maintains `data/videos.json`, hydrates transcript text/segments on reads, and centralizes metadata mutation (including audio-first metadata like `audio_path`, `audio_size`, and inferred `asset_type`). |
| `app/document_storage.py` | Streams PDF uploads to `storage/documents`, persists metadata (`data/documents.json`), and tracks derived Gemini slide descriptions in `data/document_descriptions/`. |
| `app/transcriber.py` | Simple ElevenLabs client that loads env vars, posts MP3s to `/v1/speech-to-text`, and normalizes timestamp segments for ingestion. |
| `app/pdf_slide_description_agent.py` | Gemini-powered agent that processes PDFs page-by-page (PyPDF2 for page counts) and outputs structured `SlideContent`. |
| `app/chunkings/` | `TimestampAwareChunking` converts word-level timestamps into overlapping transcript windows; `SlideChunking` splits verbose slide descriptions into up to two chunks. |
| `app/chroma_ingestion.py` | Shared ingestion service that builds `Document` objects from storage metadata, strips volatile fields, and pushes them into Chroma collections while enforcing `OPENAI_API_KEY`. |
| `app/chat_agent.py` | Configures `StudyBuddyChatAgent` (Agno `Agent`) with lecture + slide knowledge sources, a friendly instruction prompt, and helper methods for sync/SSE replies. |
| `app/database.py` | Bootstraps SQLite tables for courses, course-to-asset links, course units/topics, chat sessions, and chat messages. Exposes CRUD helpers consumed by route handlers. |
| `agent/dev_agui.py` & `chat.py` | Optional Agno AgentOS entry points (AG-UI + demo agent) for local experimentation outside FastAPI. |
| `scripts/*.py` | Utilities for chunk export, bulk ingestion, and manual transcription debugging that reuse the same services as the API. |
| `tests/test_chunking.py` | Regression coverage for the chunking strategies (ensures overlap + splitting heuristics stay stable). |

## API Surface (app/main.py)
- `GET /` / `GET /api/health` – service banners + filesystem sanity checks.
- `POST /api/videos/download` – validates `course_id`, spawns a download job, and returns `{job_id, video_id}` for polling.
- `GET /api/videos` / `GET /api/videos/active` – persisted vs. in-memory snapshots of downloads.
- `GET /api/videos/{video_id}` / `status` – fetch metadata or job state enriched with canonical `audio_url`/`video_url` links.
- `GET /api/audio/{video_id}` – stream the MP3 artifact stored under `storage/audio/`; returns structured 404s if the lecture predates audio extraction.
- `GET /api/videos/{video_id}/file` – legacy download route that now proxies to audio when available and falls back to the MP4 saved on disk.
- `DELETE /api/videos/{video_id}` – removes file + derived artifacts + metadata entry.
- `POST /api/documents/upload` – accepts PDF uploads, saves metadata, and enqueues `process_document_pipeline`.
- `GET /api/documents` / `GET /api/documents/{id}` / `GET /api/documents/{id}/file` – list metadata or stream the stored PDF.
- `POST /api/documents/{id}/slides/describe` – synchronous Gemini run (bypasses background queue) followed by slide ingestion.
- `DELETE /api/documents/{id}` – remove PDF + slide description artifacts.
- `POST /api/courses` / `GET /api/courses` – create/list course shells.
- `POST /api/courses/{course_id}/units` / `GET /api/courses/{course_id}/units` – CRUD for lecture units within a course.
- `POST /api/units/{unit_id}/topics` / `GET /api/units/{unit_id}/topics` – CRUD for granular topics nested within units.
- `POST /api/chat` – run the Agno agent synchronously; persists chat session/messages per course + user.
- `POST /api/chat/stream` – SSE endpoint streaming `RunOutputEvent`s; stores the concatenated reply in the DB once the stream completes.
- `GET /api/courses/{course_id}/chat/history` – fetches chat sessions (and nested messages) per course, optionally filtered by `user_id`.

## Domain Workflows

### Lecture ingestion
1. Client calls `POST /api/videos/download` with Panopto stream URL + `course_id`.
2. `CourseDatabase.get_course` guards the request; `VideoDownloader.download_video` seeds `self.downloads` for progress polling.
3. `_download_worker` runs in a thread: downloads via `PanoptoDownloader` (only when `audio_only=False`), extracts/streams MP3 via ffmpeg, and stores a `VideoMetadata` row through `LocalStorage` (audio-only entries persist immediately; hybrid runs call `store_video` followed by `store_audio`).
4. `_transcribe_audio` submits MP3 to ElevenLabs (if `ELEVENLABS_API_KEY` is set). Successful payloads store transcript text + timestamp segments via `LocalStorage.update_metadata` (writing files under `data/transcripts/` and `data/transcript_segments/`).
5. Completed transcripts trigger `_ingest_lecture`, which uses `ChromaIngestionService.ingest_lectures` and `TimestampAwareChunking` to push cleaned chunks into the lecture collection. Metadata intentionally omits `course_id` to prevent stale embeddings when lectures move between courses.
6. Clients poll `/api/videos/{video_id}/status` (in-memory first, disk fallback) until status shifts from `downloading` → `completed`/`failed` with transcript + ingestion markers; the payload now advertises `audio_url` so callers can hit `/api/audio/{video_id}` without inspecting metadata.

### Slide ingestion
1. `POST /api/documents/upload` stores the PDF via `DocumentStorage.save_document` and immediately schedules `process_document_pipeline` (FastAPI `BackgroundTasks`).
2. The pipeline loads metadata, validates the PDF path, and calls `PDFSlideDescriptionAgent.process_pdf`. Gemini is instructed per page and streams structured `SlideContent` objects.
3. `DocumentStorage.save_slide_descriptions` writes `data/document_descriptions/{document_id}_slides.json` and annotates the metadata entry with `slide_descriptions_path`, `slide_descriptions_updated_at`, and `slide_page_count`.
4. `ChromaIngestionService.ingest_slides([document_id])` reads that JSON, runs `chunk_slide_descriptions`, and ships each chunk into the slide collection while tagging metadata (`document_id`, `page_number`, `slide_type`, optional `user_id`).
5. `/api/documents/{document_id}/slides/describe` offers the same pipeline synchronously when an immediate Gemini/GPT pass is needed.

### Course scaffolding & chat persistence
1. Courses are stored in SQLite (`data/app.db`). `CourseDatabase` exposes coarse helpers (`create_course`, `list_courses`, `get_course`).
2. `CourseDatabase.create_unit` / `create_topic` allow route handlers to scaffold course outlines (units + granular topics). Listings are ordered by `position` then `title`.
3. Every chat call verifies the course, then `CourseDatabase.get_or_create_chat_session` finds or creates a `session_{timestamp}` per course/user pair. Messages are appended to `chat_messages` and include the source requested (lectures/slides/combined).
4. `/api/chat/stream` yields SSE payloads (JSON per `RunOutputEvent`). Once streaming finishes, StudyBuddy concatenates all chunks and persists them as the agent response.
5. `/api/courses/{course_id}/chat/history` exposes sessions with nested message arrays so client dashboards can replay chat history without re-querying Chroma.

### Retrieval & chat
1. `StudyBuddyChatAgent` instantiates two `Knowledge` handles (lectures + slides) pointing at Chroma and registers a custom `knowledge_retriever` that merges/sorts results, tagging each doc with `knowledge_source`.
2. `.respond()` invokes `Agent.run` with optional knowledge filters (`user_id` partitions). Responses are normalized into `ChatAgentResult` (markdown reply + metadata references).
3. `.stream_response()` returns an iterator of `RunOutputEvent` objects. FastAPI wraps this in an SSE response that surfaces `session` metadata, incremental `content`, and any tool invocations.

## Persistence & Runtime State

### Filesystem + JSON artifacts
- `storage/videos/{video_id}.mp4` – optional MP4 for legacy downloads or when clients request `audio_only=false`.
- `storage/audio/{video_id}.mp3` – canonical artifact used for playback and transcription, streamed via `/api/audio/{video_id}`.
- `storage/documents/{document_id}.pdf` – uploaded slide decks (downloadable via API).
- `data/videos.json` – top-level video metadata keyed by `video_id`. Fields include `title`, `source_url`, `course_id`, `course_name`, `video_path`, `video_size`, `audio_path`, `audio_size`, `asset_type` (`audio`, `video`, `hybrid`), `uploaded_at`, `status`, `error`, `transcript_status`, `transcript_error`, `transcript_path`, and `transcript_segments_path`. `LocalStorage.get_video` hydrates `transcript` + `transcript_segments` payloads by reading their sidecar files.
- `data/transcripts/` & `data/transcript_segments/` – raw transcript text (`.txt`) and ElevenLabs word segments (`.json`). Treated as read-through caches loaded only when metadata is requested.
- `data/documents.json` – dictionary keyed by `document_id` storing PDF metadata plus derived slide info (`slide_descriptions_path`, `slide_descriptions_updated_at`, `slide_page_count`).
- `data/document_descriptions/` – Gemini output per document (`{document_id}_slides.json`). Consumers (ingestor, debugging scripts) read these files without re-running Gemini.
- `data/chunks/` – optional exports created by `scripts/export_chunks.py` for inspection/testing.

### SQLite (`data/app.db`)
```
courses(id TEXT PRIMARY KEY, name TEXT NOT NULL)
course_lectures(course_id TEXT, lecture_id TEXT, PRIMARY KEY(course_id, lecture_id))
course_documents(course_id TEXT, document_id TEXT, PRIMARY KEY(course_id, document_id))
course_units(id TEXT PRIMARY KEY, course_id TEXT, title TEXT NOT NULL, description TEXT, position INTEGER DEFAULT 0)
course_topics(id TEXT PRIMARY KEY, unit_id TEXT, title TEXT NOT NULL, description TEXT, position INTEGER DEFAULT 0)
chat_sessions(id TEXT PRIMARY KEY, course_id TEXT, user_id TEXT, created_at TEXT NOT NULL)
chat_messages(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, message TEXT, source TEXT, created_at TEXT NOT NULL)
```
- Route handlers currently exercise courses/units/topics + chat tables, while `link_lecture` / `link_document` helpers are available for future association endpoints.
- `get_chat_history` performs a join across sessions/messages to return nested payloads ordered chronologically.

### Vector store (Chroma)
- Default path `tmp/chromadb`. Configurable via `ChromaIngestionConfig` or env overrides (used by CLI + AG-UI entry points).
- Collections: `course_lectures` (timestamp-aware chunks) and `course_slides` (slide chunks). Metadata avoids mutable fields such as `course_id`, but carries `lecture_id` / `document_id`, chunk indices, chunking strategy, `start_ms`/`end_ms`, `page_number`, optional `user_id`, and derived `chunk_id`s for traceability.

## External Dependencies & Env Vars
- **PanoptoDownloader** – third-party CLI module; credentials must already be configured in the runtime environment.
- **ffmpeg** – required on PATH for `_convert_to_audio` inside `VideoDownloader`.
- **ElevenLabs Speech-to-Text** – `ELEVENLABS_API_KEY` (plus `ELEVENLABS_MODEL_ID`, `ELEVENLABS_LANGUAGE_CODE`, `ELEVENLABS_DIARIZE`, `ELEVENLABS_TAG_AUDIO_EVENTS`) gate automatic transcription. Missing keys mark transcripts as `skipped` but keep download metadata intact.
- **Gemini** – `PDFSlideDescriptionAgent` calls `Gemini(id="gemini-2.0-flash-exp")` and expects Google API credentials to be present for backend-only PDF analysis.
- **OpenAI** – `ChromaIngestionService` and `StudyBuddyChatAgent` enforce `OPENAI_API_KEY` during init; `CHAT_MODEL_ID` overrides the default `gpt-4o-mini` chat model. Scripts reuse the same env loading logic for parity.
- **dotenv files** – `.env.local` is loaded by storage/transcriber/ingestion/chat services so local development and scripts share identical credentials + Chroma paths.

## Tooling & Developer Surfaces
- `scripts/manual_transcribe.py` – send any MP3/MP4 through ElevenLabs without touching FastAPI (handy for debugging diarization or timestamps).
- `scripts/ingest_chroma.py` – bulk-ingest lectures and slide docs (supports `--course-id`, `--user-id`, inclusion filters). Useful for backfills or CLI-driven pipelines.
- `scripts/export_chunks.py` – reads stored transcripts or slide descriptions and writes chunked JSON files under `data/chunks/` for inspection/regression checks.
- `agent/dev_agui.py` – spins up Agno’s AG-UI around `StudyBuddyChatAgent` for interactive debugging over the same Chroma collections.
- `tests/test_chunking.py` – regression suite for chunking strategies; run via `pytest`.

## Related Docs
- `.agent/SOP/adding_api_endpoint.md`
- `.agent/Tasks/current_features.md`
- `.agent/README.md`
