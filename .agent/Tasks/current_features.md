# Feature Briefs & Plans

## Panopto Lecture Pipeline
- **PRD Summary**: Students submit a Panopto stream alongside `course_id`; the backend downloads the MP4, extracts audio, runs transcription, and ships transcript chunks to Chroma so downstream chat can cite lecture segments.
- **Implementation Snapshot**:
  - `VideoDownloader.download_video` validates the course, tracks in-memory progress, and spawns `_download_worker` threads per job.
  - `_download_worker` streams to a temp file via `PanoptoDownloader`, extracts MP3 audio with ffmpeg, and persists canonical metadata through `LocalStorage.store_video`.
  - `ElevenLabsTranscriber` handles transcription; results flow back through `LocalStorage.update_metadata` to write transcript text + timestamp segments that `ChromaIngestionService.ingest_lectures` later chunk with `TimestampAwareChunking`.
  - `/api/videos/*` routes expose active download progress, persisted metadata, raw files, and delete orchestration.
- **Next Steps**:
  - Swap ad-hoc threads for a real task runner (Celery/RQ) so large batches do not compete for Python threads.
  - Add retries/manual overrides for failed ElevenLabs jobs; allow ingestion replays without forcing a re-download.

## Slide Upload, Description & Chroma Ingestion
- **PRD Summary**: Upload PDF slide decks, auto-describe each page with Gemini, convert descriptions into Chroma slide chunks, and keep metadata + files manageable through REST endpoints.
- **Implementation Snapshot**:
  - `DocumentStorage.save_document` streams PDFs to `storage/documents` and records metadata; `/api/documents/upload` queues `process_document_pipeline` for async Gemini processing.
  - `PDFSlideDescriptionAgent` (Gemini) emits structured `SlideContent` per page; `DocumentStorage.save_slide_descriptions` writes JSON under `data/document_descriptions/` and annotates metadata with updated timestamps + page counts.
  - `ChromaIngestionService.ingest_slides` reads the stored JSON, uses `chunk_slide_descriptions` (`SlideChunking`), and stores slide chunks with `document_id`, `page_number`, `slide_type`, and optional `user_id` metadata.
  - REST surface now includes document listing, metadata fetch, raw file streaming, synchronous `/slides/describe`, and deletion endpoints.
- **Next Steps**:
  - Associate documents with courses via `CourseDatabase.link_document` so ingestion filters can scope to a course without extra metadata.
  - Add observability around Gemini failures + ingestion metrics (per-page latency, chunk counts) for UI surfacing.

## Course Structure & Chat History
- **PRD Summary**: Persist course context (units, topics) and chat history per course/user so StudyBuddy can provide structured outlines and replay previous Q&A sessions.
- **Implementation Snapshot**:
  - `CourseDatabase` now bootstraps `course_units`, `course_topics`, `chat_sessions`, and `chat_messages` tables inside `data/app.db`.
  - `/api/courses/{course_id}/units` and `/api/units/{unit_id}/topics` endpoints create + list outline data using timestamp-derived IDs with optional `position` ordering.
  - `/api/chat` + `/api/chat/stream` verify courses, maintain per-user chat sessions, and append every user/agent exchange to SQLite (streaming concatenates reply chunks before insert).
  - `/api/courses/{course_id}/chat/history` exposes sessions + nested messages for dashboards or auditing. Future `link_lecture`/`link_document` helpers already exist for tighter associations.
- **Next Steps**:
  - Surface unit/topic data inside chat prompts to provide additional retrieval hints (requires linking ingestion IDs to course structures).
  - Add pagination + search to chat history endpoint once sessions get large; consider retention rules per user/course.

## Related Docs
- `.agent/System/project_architecture.md`
- `.agent/SOP/adding_api_endpoint.md`
- `.agent/README.md`
