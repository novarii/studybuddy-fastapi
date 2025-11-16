# Project Architecture

## Product Goal & Runtime Snapshot
StudyBuddy FastAPI is a developer-facing service that downloads Panopto lectures, extracts and transcribes their audio, ingests both lectures and slide decks into Chroma, and exposes the resulting knowledge through a retrieval-augmented chat API. The system is intentionally filesystem-first: videos, audio, documents, transcripts, and chunk exports live under `storage/` or `data/`, while durable configuration sits inside `.env.local`. StudyBuddy also bundles an Agno AgentOS sandbox (`chat.py`) for experiments outside the primary FastAPI app.

```
browser extension / CLI → FastAPI routes (app/main.py)
                     ↙                 ↘
     VideoDownloader threads      BackgroundTasks for PDFs
          ↙             ↘              ↙             ↘
   storage/videos   storage/audio   storage/documents  data/document_descriptions
          ↓                ↓                  ↓                     ↓
   data/videos.json ↔ LocalStorage   data/documents.json ↔ DocumentStorage
          ↓                                   ↓
     ChromaIngestionService (TimestampAwareChunking / SlideChunking)
          ↓
   Chroma collections (course_lectures + course_slides)
          ↓
   StudyBuddyChatAgent (Agno + OpenAIChat)
```

## Tech Stack & Module Guide
- **Language + runtime**: Python 3.11+, FastAPI + Uvicorn, Pydantic v1 models, pytest for unit tests.
- **External services**: PanoptoDownloader CLI, ffmpeg, ElevenLabs Speech-to-Text, Google Gemini (through `agno.models.google`), OpenAI Chat models for retrieval, Chroma for embeddings, dotenv for env management.
- **Persistence**: Filesystem-backed metadata (JSON under `data/`), binary assets under `storage/`, SQLite (`data/app.db`) for courses, and Chroma for vector search (`tmp/chromadb` by default).

| Module | Responsibility |
| --- | --- |
| `app/main.py` | Declares all FastAPI routes, wires singleton services (storage, downloader, chroma ingestor, chat agent), and orchestrates background slide processing. |
| `app/downloader.py` | Wraps `PanoptoDownloader` downloads, tracks status in-memory, extracts audio (ffmpeg), runs ElevenLabs transcription, and triggers lecture ingestion. |
| `app/storage.py` | Owns `storage/videos`, `storage/audio`, transcript persistence (`data/transcripts/`, `data/transcript_segments/`), and the canonical `data/videos.json` metadata file. |
| `app/document_storage.py` | Streams uploaded PDFs into `storage/documents`, tracks metadata in `data/documents.json`, and stores slide descriptions under `data/document_descriptions/`. |
| `app/transcriber.py` | Configurable ElevenLabs client that normalizes word-level timestamps for downstream chunking. |
| `app/pdf_slide_description_agent.py` | Gemini-powered agent that emits structured `SlideContent` objects per page without rasterizing the PDF. |
| `app/chunkings/` | Houses `TimestampAwareChunking` and `SlideChunking` strategies used across ingestion pipelines and exported utilities. |
| `app/chroma_ingestion.py` | Converts stored transcripts/slides into Agno `Document` chunks, sanitizes metadata, and pushes them into Chroma collections. Also offers helper methods for lecture IDs per course. |
| `app/chat_agent.py` | Configures the Agno Agent that queries Chroma, merges lecture + slide hits, and exposes streaming/non-streaming replies. |
| `app/database.py` | Boots an on-disk SQLite store with `courses`, `course_lectures`, and `course_documents` tables. Currently only CRUD for `courses` is wired, but link helpers exist for future association endpoints. |
| `scripts/ingest_chroma.py`, `scripts/export_chunks.py`, `scripts/manual_transcribe.py` | Ad-hoc CLIs for ingestion backfills, debugging chunkers, and manually validating ElevenLabs transcription pipelines. |
| `tests/test_chunking.py` | Regression coverage for the transcript and slide chunkers. |
| `chat.py` | Standalone Agno AgentOS FastAPI app unrelated to the StudyBuddy API but available for experimentation. |

## API Surface (app/main.py)
- `GET /` – service banner + health indicator.
- `GET /api/health` – storage path existence plus API status.
- `POST /api/videos/download` – requires `stream_url` + `course_id`; creates/validates course, spawns a download thread, and returns `{job_id, video_id}` for polling.
- `GET /api/videos` – dumps metadata from `data/videos.json`.
- `GET /api/videos/active` – in-memory view of `VideoDownloader.downloads` (download progress + transcription state).
- `GET /api/videos/{video_id}/status` – merged status (`downloader.downloads` fallback to persisted metadata).
- `GET /api/videos/{video_id}` – hydrated metadata including transcript text/segments (loaded from disk on demand).
- `GET /api/videos/{video_id}/file` – streams stored MP4.
- `DELETE /api/videos/{video_id}` – removes media, audio, transcript artifacts, and metadata entry.
- `POST /api/documents/upload` – PDF-only upload; enqueues `process_document_pipeline` background job.
- `POST /api/documents/{document_id}/slides/describe` – force-runs the Gemini agent synchronously, writes JSON descriptions, and ingests resulting slide chunks.
- `DELETE /api/documents/{document_id}` – removes PDF + derived files.
- `POST /api/courses` / `GET /api/courses` – create and list course shells before ingestion.
- `POST /api/chat` – runs `StudyBuddyChatAgent.respond` and returns markdown + references.
- `POST /api/chat/stream` – wraps `StudyBuddyChatAgent.stream_response` in Server-Sent Events (`event`, optional `content`/`tools`).

## End-to-End Workflows

### Lecture ingestion pipeline
1. Client calls `POST /api/videos/download` with a Panopto `stream_url`, `course_id`, optional `video_id`/title/source.
2. `CourseDatabase` ensures the course exists; `VideoDownloader.download_video` records an entry in `self.downloads` and dispatches `_download_worker` on its own thread.
3. `_download_worker` pulls to a temp file via `PanoptoDownloader`, invokes `_convert_to_audio` (ffmpeg) for MP3 output, and persists a `VideoMetadata` object to `data/videos.json` using `LocalStorage.store_video`.
4. If audio extraction succeeded and ElevenLabs credentials are set, `_transcribe_audio` posts the MP3 to `ElevenLabsTranscriber`. Transcript text and timestamp segments are written to `data/transcripts/{video_id}.txt` and `data/transcript_segments/{video_id}.json` via `LocalStorage.update_metadata`.
5. When transcription finishes successfully, `_ingest_lecture` calls `ChromaIngestionService.ingest_lectures([video_id])`. `TimestampAwareChunking` consumes the transcript + segments to create overlapping windows annotated with `chunk_index`, `start_ms`, `end_ms`, and `lecture_id`. Metadata deliberately excludes mutable fields such as `course_id`.
6. Clients poll `/api/videos/{video_id}/status` to monitor download → transcription → ingestion progress.

### Slide ingestion pipeline
1. Client uploads a PDF through `POST /api/documents/upload`. `DocumentStorage.save_document` streams to `storage/documents/{document_id}.pdf` and records metadata in `data/documents.json`. FastAPI schedules `process_document_pipeline(document_id)` via `BackgroundTasks`.
2. The pipeline fetches metadata, validates the on-disk PDF, and calls `PDFSlideDescriptionAgent.process_pdf`. The agent iterates through pages using Gemini (default `gemini-2.0-flash-exp`) and emits `SlideContent` models containing summaries plus fine-grained descriptions.
3. `DocumentStorage.save_slide_descriptions` writes JSON output to `data/document_descriptions/{document_id}_slides.json` and annotates metadata with `slide_descriptions_path`, last-updated timestamp, and `slide_page_count`.
4. `ChromaIngestionService.ingest_slides([document_id])` loads those descriptions and converts each slide to `Document` instances. `SlideChunking` emits one or two chunks per slide (`chunk`/`total_chunks` metadata) and keeps `document_id`, `page_number`, `slide_type`, summary, and optional `user_id` metadata. The CLI `scripts/export_chunks.py` uses the same helpers for debugging.

### Retrieval & chat
1. `StudyBuddyChatAgent` instantiates two `Knowledge` handles backed by Chroma collections (`course_lectures`, `course_slides`). Both connect to `tmp/chromadb` unless overridden via env.
2. The agent runs OpenAI Chat (`gpt-4o-mini` by default; overridable via `CHAT_MODEL_ID`) with custom `knowledge_retriever`. Depending on the `source` requested (`lectures`, `slides`, `combined`), it queries the appropriate collections, tags each hit with `knowledge_source`, and merges + sorts by similarity score.
3. `/api/chat` exposes synchronous responses (markdown text + references). `/api/chat/stream` replays the `RunOutputEvent` stream as SSE, preserving `event`, `content`, and `tools` payloads for the caller.
4. The agent enforces `OPENAI_API_KEY` at initialization. Slides/lectures may also include `user_id` filters, allowing per-user knowledge partitions when the ingestion CLI is invoked with `--user-id`.

## Persistence Map

### Filesystem + JSON
- `storage/videos/{video_id}.mp4` – canonical MP4 asset referenced by `file_path` in metadata.
- `storage/audio/{video_id}.mp3` – derived MP3 for ElevenLabs submissions.
- `storage/documents/{document_id}.pdf` – uploaded slide decks.
- `data/videos.json` – dictionary keyed by `video_id` including: `title`, `source_url`, `course_id`, `course_name`, `file_path`, `file_size`, `uploaded_at`, `status`, `error`, `audio_path`, `transcript_status`, `transcript_error`, `transcript_path`, `transcript_segments_path`, and ingestion status fields appended over time.
- `data/transcripts/{video_id}.txt` & `data/transcript_segments/{video_id}.json` – lazily populated text + timestamp payloads read back inside `LocalStorage.get_video` when API callers need them.
- `data/documents.json` – dictionary keyed by `document_id` that stores `original_filename`, `content_type`, `file_path`, `file_size`, `uploaded_at`, plus slide description metadata (`slide_descriptions_path`, `_updated_at`, `slide_page_count`).
- `data/document_descriptions/{document_id}_slides.json` – structured `SlideContent` output; used by ingestion and inspection tools.
- `data/chunks/` – optional exports generated by `scripts/export_chunks.py`.

### SQLite (`data/app.db`)
```
courses(id TEXT PRIMARY KEY, name TEXT NOT NULL)
course_lectures(course_id TEXT, lecture_id TEXT, PRIMARY KEY(course_id, lecture_id))
course_documents(course_id TEXT, document_id TEXT, PRIMARY KEY(course_id, document_id))
```
Only `/api/courses` endpoints currently hit this DB, but helper methods (`link_lecture`, `link_document`, `list_*_for_course`) are ready for future association work or ingestion filters.

### Vector store (Chroma)
- Default path: `tmp/chromadb`. Collections: `course_lectures` and `course_slides` (configurable via `ChromaIngestionConfig`).
- Stored metadata intentionally omits `course_id` to avoid stale embeddings; lookups rely on `lecture_id` / `document_id`, `chunk_index`, `chunking_strategy`, `start_ms`/`end_ms` (lectures), `page_number` (slides), and optional `user_id`. `chunk_id` is derived from document IDs for traceability.

## External Dependencies & Env Vars
- **PanoptoDownloader** – imported from `PanoptoDownloader`; requires credentials/config in the runtime environment.
- **ffmpeg** – must be installed on PATH for `_convert_to_audio`.
- **ElevenLabs** – `ElevenLabsTranscriber` reads `ELEVENLABS_API_KEY`, `ELEVENLABS_MODEL_ID` (default `scribe_v1`), `ELEVENLABS_LANGUAGE_CODE`, `ELEVENLABS_DIARIZE`, and `ELEVENLABS_TAG_AUDIO_EVENTS`. Missing API keys cause transcripts to be marked `skipped`.
- **Gemini** – `PDFSlideDescriptionAgent` uses `Gemini(id="gemini-2.0-flash-exp")`; `agno` expects standard Google API credentials in the environment.
- **OpenAI** – `ChromaIngestionService` and `StudyBuddyChatAgent` both enforce `OPENAI_API_KEY`; chat model ID defaults to `gpt-4o-mini` but honors `CHAT_MODEL_ID`.
- `.env.local` – loaded wherever credentials are needed so scripts + FastAPI share the same configuration.

## Tooling & Quality Gates
- `scripts/manual_transcribe.py` – transcribes arbitrary media files using ElevenLabs to debug diarization or timestamp extraction without hitting FastAPI routes.
- `scripts/ingest_chroma.py` – CLI for bulk ingestion/backfills. Requires `--course-id` and `--user-id`, and optionally limits lecture/document IDs.
- `scripts/export_chunks.py` – dumps transcript or slide chunks to `data/chunks/` for inspection.
- `tests/test_chunking.py` – ensures chunking logic preserves overlaps, fallback behavior, and slide splitting heuristics. Run via `pytest` once dependencies are installed.

## Related Docs
- `.agent/SOP/adding_api_endpoint.md`
- `.agent/Tasks/current_features.md`
- `.agent/README.md`
