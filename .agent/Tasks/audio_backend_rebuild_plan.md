# Task: Audio-Only Backend Rebuild (Postgres + pgvector)

## PRD
### Background
- The existing FastAPI service accumulated experimental surfaces (embedded AG-UI sandbox, dual databases, redundant storage) that are unnecessary for the production goal: gather lecture audio + slide PDFs, enrich them into retrieval-ready knowledge, and expose that context to the Agno Agent + CopilotKit clients.
- We are rebuilding the backend from a clean repo that focuses on two asset types: Panopto-derived transcripts (audio is temporary just for transcription) and PDF slide decks. AG-UI is no longer a standalone process; the backend must serve its bundle via an endpoint while the CopilotKit handler itself lives in the Next.js frontend server.
- All structured data moves to PostgreSQL with pgvector. JSON files, SQLite, and ChromaDB are removed. Binary storage can remain on disk or object storage for PDF assets, but metadata, transcripts, jobs, and embeddings must be persisted in Postgres.

### Goals
1. Deliver a lean FastAPI (or equivalent) backend dedicated to:
   - Downloading Panopto streams, extracting audio-only payloads long enough to transcribe them, and persisting transcript progress + metadata (audio artifacts are discarded once transcription completes).
   - Transcribing audio, chunking transcripts, and storing chunk embeddings directly in Postgres (pgvector) for Agno Agent retrieval.
   - Accepting PDF slide uploads, keeping the original files intact, generating slide descriptions/chunks, and embedding them via pgvector.
   - Serving the AG-UI client bundle under `/ag-ui` while exposing chat + retrieval endpoints that speak the existing AG-UI protocol.
2. Define a Postgres schema that captures everything we previously stored in JSON/SQLite/Chroma: assets, downloads, transcripts, jobs, embeddings, slide content, chat sessions/messages, and operational logs.
3. Publish a modern API surface that frontends can rely on (Next.js CopilotKit handler + AG-UI). Each endpoint must return deterministic metadata for transcripts and URLs for PDF files without requiring callers to know filesystem paths.
4. Ensure ingestion + retrieval pipelines run through background workers (synchronous kicks allowed) and emit consistent status transitions for monitoring.

### Non-Goals
- Rebuilding the CopilotKit handler (it moves to the Next.js repo).
- Supporting MP4 downloads, video streaming, or non-PDF document types.
- Shipping a new UI—this plan only addresses backend endpoints and AG-UI static serving.
- Reintroducing Chromadb or SQLite; pgvector replaces both the vector store and relational metadata.

## High-Level Architecture
- **Gateway**: FastAPI app exposing REST + SSE endpoints, static AG-UI serving, and authenticated upload/download routes.
- **Download Worker**: Thread/Task queue (Celery/RQ/Arq) responsible for Panopto jobs, ffmpeg audio extraction, transcript + ingestion callbacks.
- **Transcription Service**: ElevenLabs (or pluggable) client invoked by the worker; emits transcripts + word/segment JSON stored in Postgres JSONB.
- **Embedding Service**: Normalized interface to OpenAI/Vertex embedding APIs; writes embeddings straight into pgvector columns in Postgres.
- **Postgres**: Single source of truth for users/courses/assets/jobs/transcripts/embeddings/chat logs; pgvector plugin enabled for chunk tables.
- **Document Storage & Temp Audio Scratch**: PDFs persist under `storage/documents/` (or S3-compatible bucket) with canonical URLs + checksums; audio lives only in scratch space during transcription and is deleted afterward.
- **Agno Agent Layer**: Lives inside the backend, queries Postgres for lecture/slide chunks via SQL + pgvector search, and responds through AG-UI endpoints; CopilotKit traffic flows through the Next.js frontend but ultimately hits backend chat endpoints.

## Postgres Schema (initial draft)
### Core Reference Tables
- `courses(id UUID, name TEXT, description TEXT, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ)`
- `users(id UUID, email TEXT, display_name TEXT, created_at TIMESTAMPTZ)` – optional but keeps session attribution if needed.

### Asset + Job Tables
- `lectures(id UUID PK, course_id UUID FK, panopto_session_id TEXT, panopto_url TEXT, title TEXT, status TEXT, status_reason TEXT, audio_duration_seconds INT, language_code TEXT, transcript_status TEXT, embed_status TEXT, last_job_id UUID, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ)`
- `lecture_download_jobs(id UUID PK, lecture_id UUID FK, panopto_reference TEXT, job_state TEXT CHECK pending/downloading/transcribing/embedding/completed/failed, progress_percent INT, error_message TEXT, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, log JSONB)`
- `lecture_transcripts(id UUID PK, lecture_id UUID UNIQUE FK, transcript_text TEXT, word_segments JSONB, token_count INT, provider TEXT, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ)`
- `lecture_chunks(id UUID PK, lecture_id UUID FK, chunk_index INT, start_ms INT, end_ms INT, content TEXT, metadata JSONB, embedding vector(1536), created_at TIMESTAMPTZ)`

### Document Tables
- `documents(id UUID PK, course_id UUID FK, filename TEXT, storage_url TEXT, mime_type TEXT, size_bytes BIGINT, page_count INT, status TEXT CHECK uploaded/described/embedding/completed/failed, description_job_id UUID, created_at TIMESTAMPTZ, updated_at TIMESTAMPTZ)`
- `slide_descriptions(id UUID PK, document_id UUID FK, page_number INT, raw_description TEXT, normalized_description TEXT, metadata JSONB, created_at TIMESTAMPTZ)`
- `slide_chunks(id UUID PK, document_id UUID FK, chunk_index INT, content TEXT, metadata JSONB (e.g., page, section, tags), embedding vector(1536), created_at TIMESTAMPTZ)`

### Chat & AG-UI
- `chat_sessions(id UUID PK, course_id UUID FK, user_id UUID FK NULL, session_label TEXT, created_at TIMESTAMPTZ)`
- `chat_messages(id UUID PK, session_id UUID FK, role TEXT CHECK ('user','assistant','system'), content TEXT, metadata JSONB (knowledge hits, request ids), created_at TIMESTAMPTZ)`
- `agui_assets(id SERIAL PK, bundle_version TEXT, checksum TEXT, served_at TIMESTAMPTZ)` – tracks which bundle is being served to `/ag-ui`.

### Operational Metadata
- `processing_events(id BIGSERIAL PK, asset_type TEXT, asset_id UUID, event_type TEXT, payload JSONB, created_at TIMESTAMPTZ)` – optional audit trail.
- `api_keys(id UUID PK, name TEXT, hashed_key TEXT, scopes TEXT[], created_at TIMESTAMPTZ)` – if we gate endpoints by API key.

### Indexing/Constraints
- Vector columns (`lecture_chunks.embedding`, `slide_chunks.embedding`) need `ivfflat` indexes tuned to embedding dimensionality.
- Unique constraints on `(lecture_id, chunk_index)` and `(document_id, chunk_index)` enforce deterministic chunk ordering.
- Partial indexes on `lectures.status`, `documents.status`, and `chat_sessions.course_id` accelerate dashboard queries.

## Document Storage & Temporary Audio Handling
- Audio extracted from Panopto is written to a temp scratch path solely for transcription and deleted immediately after transcription jobs finish; only derived transcript text/metadata persist in Postgres.
- PDFs remain under `{env.DATA_ROOT}/documents/{document_id}.pdf` (or a bucket). The backend never mutates PDFs; only derived slide descriptions live in Postgres.
- Checksums (SHA256) saved in Postgres cover persistent files (PDFs) so we can perform integrity checks and deduplication without retaining audio binaries.

## API Surface
### Health & Static
- `GET /api/health` – DB + storage sanity.
- `GET /ag-ui` + `GET /ag-ui/{asset}` – serve bundled AG-UI assets (HTML/JS/CSS) so there is no second process. Use caching headers and optional checksum query param.

### Course + Catalog
- `POST /api/courses` / `GET /api/courses` / `GET /api/courses/{id}`.
- `GET /api/courses/{id}/assets` – aggregated view of lectures + documents + their statuses.

### Lectures / Transcripts
- `POST /api/lectures/download` – body: `{course_id, panopto_url, title?, priority?, transcription=true|false}`; returns `{lecture_id, job_id}`. Immediately enqueues worker job.
- `GET /api/lectures` – list with filters (`status`, `course_id`, `updated_before/after`).
- `GET /api/lectures/{id}` – returns metadata, job state, transcript + embedding flags, transcript excerpts, and AG-UI-friendly metadata (duration, asset_type='audio').
- `GET /api/lectures/{id}/status` – lightweight job progress (pulls from `lecture_download_jobs`).
- `GET /api/lectures/{id}/transcript` – returns `transcript_text`, optional segments; 404 until transcription completes.
- `DELETE /api/lectures/{id}` – removes DB rows + transcript/chunk derivatives (soft delete optional via `deleted_at`).

### Documents / Slides
- `POST /api/documents/upload` – multipart PDF upload; persists row + disk file; schedules slide description + embedding job.
- `GET /api/documents` / `GET /api/documents/{id}` – metadata, statuses, derived stats (page_count, chunk_counts).
- `GET /api/documents/{id}/file` – stream PDF.
- `POST /api/documents/{id}/describe` – optional synchronous slide description run (returns structured summary).
- `GET /api/documents/{id}/chunks` – slide chunks preview for debugging.
- `DELETE /api/documents/{id}` – remove metadata + storage file.

### Retrieval + Chat
- `POST /api/retrieval/query` – optional internal endpoint for Next.js CopilotKit handler; body includes `course_id`, `query`, `top_k`, `sources=['lectures','slides']`. Executes pgvector search and returns `[{chunk_id, content, source, score, metadata}]`.
- `POST /api/chat` – synchronous Agno Agent response (wraps retrieval, tool execution, DB logging).
- `POST /api/chat/stream` – SSE or chunked responses compatible with AG-UI protocol; includes `session_id`, `message_id`, and `run_metadata`.
- `GET /api/chat/sessions?course_id=` – list sessions + last message summary.
- `GET /api/chat/sessions/{id}` – returns ordered messages, knowledge references.

## Processing Pipelines
### Lecture Pipeline
1. **Request**: `POST /api/lectures/download`.
2. **Job init**: create rows in `lectures` (status=`pending`) + `lecture_download_jobs`.
3. **Panopto download**: worker pulls job, invokes PanoptoDownloader, downloads to temp MP4 if needed.
4. **Audio extraction**: ffmpeg converts to MP3 inside worker scratch space; capture checksum/duration metadata, pass the temp file to transcription, then delete it as soon as transcription uploads finish.
5. **Transcription** (optional flag): send MP3 to ElevenLabs (or alt provider); store transcript + segments in `lecture_transcripts`; set `transcript_status`.
6. **Chunking + embeddings**: run timestamp-aware chunker; persist rows in `lecture_chunks` with embeddings in pgvector; mark `embed_status=completed`.
7. **Completion**: update `lectures.status='completed'`, `lecture_download_jobs.job_state='completed'`.
8. **Failure handling**: capture stack/error message into `job_state='failed'`, `status_reason`, and `processing_events`.

### Document Pipeline
1. Upload PDF → persist metadata + file.
2. Background job calls Gemini (or other LLM) to produce page descriptions; rows land in `slide_descriptions`.
3. Slide chunker runs (max tokens per chunk) → create `slide_chunks` with embeddings.
4. Document status transitions through `uploaded → described → embedding → completed`.

### Retrieval/Chat Flow
1. Chat endpoint receives prompt + course_id (+ user/session ids).
2. Agent composes retrieval query (optionally use heuristics for lectures vs slides). 
3. pgvector search executed on `lecture_chunks` and/or `slide_chunks` with filters (course_id) + metadata (e.g., `user_id` for personalized assets).
4. Agent uses returned context to craft responses; results logged to `chat_messages` with references to chunk ids.
5. SSE stream ensures AG-UI receives content chunks; once complete, final message stored with aggregated metadata.

## AG-UI Integration Plan
- Build AG-UI bundle (from the Next.js repo) as static assets committed/packaged under `assets/agui/`.
- Backend exposes `GET /ag-ui` to serve the HTML shell and `GET /ag-ui/static/{path}` for JS/CSS chunks. Use `aiofiles`/Starlette `StaticFiles`.
- Provide config endpoint `GET /api/agui/config` returning environment toggles (API base URL, CopilotKit endpoints).
- CopilotKit handler inside Next.js will call backend `/api/chat`/`/stream` using the AG-UI protocol; we simply ensure payload schema matches expectations (`session_id`, `messages`, `contextDocs` etc.).

## Metadata & Telemetry
- Every lecture/document stores lifecycle timestamps (`ingestion_started_at`, `transcribed_at`, `embedded_at`) inside JSONB metadata for debugging.
- `processing_events` gives chronological breadcrumbs for jobs; useful for UI timelines.
- Log ingestion/responses via structured logging (JSON) for shipping to centralized logging (Datadog/Grafana).
- Metrics to expose: active jobs, failed jobs, ingestion duration per stage, transcript latency, embedding latency, chat response latency, retrieval hit counts.

## Implementation Roadmap
1. **Bootstrap repo**: create FastAPI skeleton, configure alembic migrations for Postgres + pgvector extension.
2. **Define models/migrations**: implement tables outlined above; build SQLAlchemy models and repository layer.
3. **Document storage module**: wrap local/S3 PDF storage with deterministic paths + checksum utilities while keeping audio scratch paths ephemeral.
4. **Lecture ingestion service**: Panopto download wrapper, ffmpeg audio extraction (temp only), job orchestration, status updates.
5. **Transcription + embedding services**: integrate ElevenLabs (or alternative) and embedding API; implement chunkers mirroring current heuristics.
6. **Document upload pipeline**: PDF storage, Gemini slide description worker, chunking + embeddings.
7. **API routes**: implement endpoints grouped by domain (courses, lectures, documents, retrieval, chat, AG-UI static serving).
8. **Agno Agent integration**: configure agent to read from Postgres via repository/pgvector search; expose `/api/chat` + `/api/chat/stream`.
9. **Testing & hardening**: unit tests for services, integration tests for ingestion + retrieval, load tests on pgvector queries.
10. **Docs & SOP refresh**: document API contracts, migrations, operational playbooks, AG-UI deployment steps.

## Open Questions / Follow-Ups
- Decide on scratch storage strategy for temporary audio artifacts (local disk vs. short-lived object storage) to keep transcription throughput high without persisting binaries.
- Confirm transcription provider (stay with ElevenLabs or migrate to Whisper/GCP STT).
- Determine auth strategy (API keys vs. JWT from Next.js) for upload/download endpoints.
- Clarify retention policy for PDF binaries and embeddings (auto-expire vs. manual cleanup) since audio is already transient.
- Validate AG-UI bundle delivery flow with the Next.js team to ensure `/ag-ui` integration matches their expectations.
