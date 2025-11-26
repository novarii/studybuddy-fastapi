# StudyBuddy FastAPI - Panopto Lecture Downloader API

A FastAPI-based REST API for downloading Panopto streams with an audio-first workflow.

## Features

- Download Panopto streams and persist MP3 audio as the canonical artifact
- Extract audio tracks (MP3 via ffmpeg) alongside each download
- Transcribe audio tracks to text through the ElevenLabs Speech-to-Text API
- Upload PDF slide decks for local storage (future processing)
- Track download progress and status
- List and manage downloaded videos
- RESTful API with CORS support

## Prerequisites

- Python 3.8 or higher
- pip or uv package manager
- ffmpeg (required for video processing)

### Installing ffmpeg

**Linux (Ubuntu/Debian/WSL):**
```bash
sudo apt update
sudo apt install -y ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Windows:**
Download from [ffmpeg.org](https://ffmpeg.org/download.html) or use:
```bash
choco install ffmpeg
```

Verify installation:
```bash
ffmpeg -version
```

## Installation

### Using pip

1. Install dependencies:
```bash
pip install -r requirements.txt
```

Note: Due to dependency conflicts, you may need to install some packages separately:
```bash
pip install "yarl>=1.9.0" "multidict>=4.0" "propcache>=0.2.1" --no-deps
pip install -r requirements.txt --no-deps
```

### Using uv

If you're using `uv` as your package manager:

```bash
# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv pip install -r requirements.txt
```

### Environment Variables

Create a `.env.local` (or `.env`) file at the project root and define the ElevenLabs API key:

```
ELEVENLABS_API_KEY=your_elevenlabs_key
```

Optional overrides include `ELEVENLABS_MODEL_ID`, `ELEVENLABS_LANGUAGE_CODE`, `ELEVENLABS_DIARIZE`, and `ELEVENLABS_TAG_AUDIO_EVENTS`. Restart the API server any time you change these values.

## Running the Server

### Using uvicorn directly

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The `--reload` flag enables auto-reload on code changes (useful for development).

### Using uv to run uvicorn

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Using Python directly

```bash
python -m app.main
```

Or:

```bash
python app/main.py
```

## Server Access

Once the server is running, you can access:

- **API Base URL**: `http://localhost:8000`
- **API Documentation (Swagger UI)**: `http://localhost:8000/docs`
- **Alternative API Docs (ReDoc)**: `http://localhost:8000/redoc`
- **Health Check**: `http://localhost:8000/api/health`

## API Endpoints

### Health Check
- `GET /api/health` - Check server health and storage status

### Video Management
- `POST /api/videos/download` - Start downloading a video
- `GET /api/videos` - List all stored videos
- `GET /api/videos/active` - List active downloads
- `GET /api/videos/{video_id}` - Get video metadata
- `GET /api/videos/{video_id}/status` - Get download status
- `GET /api/audio/{video_id}` - Download the MP3 artifact for a lecture (primary route)
- `GET /api/videos/{video_id}/file` - Legacy download route; returns audio when available and falls back to MP4 for archived entries
- `DELETE /api/videos/{video_id}` - Delete a video

`POST /api/videos/download` defaults to `{"audio_only": true}` to avoid persisting MP4s unless explicitly requested.

### Document Management
- `POST /api/documents/upload` - Upload PDF slides; file is saved under `storage/documents/` and metadata recorded in `data/documents.json`
- `GET /api/documents` - List metadata for every stored PDF (document ID, filename, paths, slide description details)
- `GET /api/documents/{document_id}` - Retrieve metadata for a single stored document
- `DELETE /api/documents/{document_id}` - Remove a PDF and any slide descriptions on disk

### Course Management
- `POST /api/courses` - Create a course record in SQLite (`course_id` returned)
- `GET /api/courses` - List available courses for UI dropdowns/extensions
- `POST /api/courses/{course_id}/units` - Create a unit for the specified course (title/description/position)
- `GET /api/courses/{course_id}/units` - List all units for a course
- `POST /api/units/{unit_id}/topics` - Create a topic inside a unit
- `GET /api/units/{unit_id}/topics` - List topics belonging to a unit

### Chat & Knowledge
- `POST /api/chat` - Send a message to the StudyBuddy agent (requires `course_id`; response includes `session_id` so clients can associate history)
- `POST /api/chat/stream` - Stream the same response over SSE; initial event contains the `session_id`
- `GET /api/courses/{course_id}/chat/history` - Persisted chat sessions/messages for a course (filterable via `?user_id=`)

## Example Usage

### Start a video download

```bash
curl -X POST "http://localhost:8000/api/videos/download" \
  -H "Content-Type: application/json" \
  -d '{
    "stream_url": "https://example.panopto.com/stream/...",
    "title": "My Video",
    "source_url": "https://example.panopto.com/...",
    "course_id": "course_20250101_120000_000000",
    "course_name": "CSC282 - Algorithms",
    "audio_only": true
  }'
```

### Check download status

```bash
curl "http://localhost:8000/api/videos/{video_id}/status"
```

### List all videos

```bash
curl "http://localhost:8000/api/videos"
```

### Export transcript or slide chunks to JSON

```bash
# Transcript chunks for a lecture (first 3 chunks only)
PYTHONPATH=$PWD scripts/export_chunks.py --video-id video_20250101_120000_000000 --limit 3

# Slide chunks from a processed document
PYTHONPATH=$PWD scripts/export_chunks.py --document-id doc_20250102_130000_000000 --limit 3
```
Outputs land in `data/chunks/` for quick inspection before sending to Chroma.

### Ingest a course into Chroma

```bash
PYTHONPATH=$PWD scripts/ingest_chroma.py \
  --course-id course_20250101_120000_000000 \
  --user-id alice@example.com \
  --lectures video_20250105_101010_000001 \
  --documents doc_20250106_123000_000000 \
  --lecture-collection course_lectures \
  --slide-collection course_slides \
  --chroma-path data/chroma_db
```

`--lectures` defaults to all lectures stored for that course; `--documents` is optional and expects slide decks that already have `slides/describe` output. Lecture and slide chunks are inserted into separate Chroma collections (specified via `--lecture-collection` and `--slide-collection`) so your agent can query them independently.

## Project Structure

```
studybuddy-fastapi/
├── app/
│   ├── main.py          # FastAPI application and routes
│   ├── models.py        # Pydantic models
│   ├── downloader.py    # Video download logic
│   ├── document_storage.py # PDF storage utilities
│   ├── chunkings/
│   │   └── chunking.py  # Timestamp-aware chunking strategy
│   ├── storage.py       # Local storage management
│   └── transcriber.py   # ElevenLabs speech-to-text integration
├── storage/
│   ├── videos/          # Downloaded video files
│   └── audio/           # Extracted audio files (mp3)
├── data/                # Metadata and data files
├── requirements.txt     # Python dependencies
└── README.md           # This file
```

## Dev-only CopilotKit Bridge

To proxy CopilotKit traffic from the Vite UI into StudyBuddy’s existing agent:

1. **Expose AG-UI**
   ```bash
   python -m agent.dev_agui  # serves http://localhost:8001/agui (override via AGUI_PORT)
   ```
   The script wraps `StudyBuddyChatAgent` with the Agno v2 `AGUI` interface, so you interact with the same retrieval pipeline as `/api/chat`.

2. **Start the CopilotKit bridge** (Node 18+)
   ```bash
   cd dev/copilotkit-server
   npm install @ag-ui/agno @copilotkit/runtime cors dotenv express \
              && npm install -D @types/express @types/node ts-node typescript
   npx ts-node --project tsconfig.json server.ts  # hosts http://localhost:3000/api/copilotkit
   ```
   Optional env vars: `AGNO_AGENT_URL` (defaults to `http://localhost:8001/agui`) and `COPILOTKIT_PORT` (defaults to `3000`).

3. **Point Vite’s CopilotChat runtime** at `http://localhost:3000/api/copilotkit`. Messages now flow: Vite → CopilotKit bridge → AG-UI → StudyBuddy agent.

## Development

The server runs with auto-reload enabled when using the `--reload` flag, so changes to the code will automatically restart the server.

## Notes

- Videos are stored in the `storage/videos/` directory
- Audio-only files are stored in `storage/audio/` and share the same `video_id` filename
- Uploaded PDFs are stored in `storage/documents/` with metadata in `data/documents.json`
- Metadata (status, file paths, etc.) lives in `data/videos.json`, while transcript text and segments are stored per-lecture under `data/transcripts/` and `data/transcript_segments/`
- CORS is enabled for all origins (configure appropriately for production)

## Timestamp-aware chunking with Agno

To feed transcripts into Agno’s knowledge base while keeping the precise ElevenLabs timecodes,
use the `TimestampAwareChunking` strategy defined in `app/chunkings/chunking.py`. It converts the stored
`transcript_segments` (word-level timestamps) into chunks that include `start_ms`/`end_ms`
metadata so the frontend and agents can jump directly to the right moment in a lecture.

```python
import json
from pathlib import Path
from agno.knowledge.document.base import Document
from app.chunkings.chunking import TimestampAwareChunking

transcript_text = Path(metadata["transcript_path"]).read_text(encoding="utf-8")
segments = json.loads(Path(metadata["transcript_segments_path"]).read_text(encoding="utf-8"))

doc = Document(
    id=video_id,
    name=metadata["title"],
    content=transcript_text,
    meta_data={
        "segments": segments,
        "lecture_id": video_id,
        "source": "transcript",
        "course_id": metadata.get("course_id"),
    },
)

chunker = TimestampAwareChunking(max_words=110, max_duration_ms=75_000, overlap_ms=12_000)
chunks = chunker.chunk(doc)
```

Each emitted chunk inherits the transcript context and includes the millisecond offsets required
for semantic search + timestamp previews in your UI.
