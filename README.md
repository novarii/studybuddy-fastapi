# StudyBuddy FastAPI - Panopto Video Downloader API

A FastAPI-based REST API for downloading videos from Panopto streaming URLs.

## Features

- Download videos from Panopto stream URLs
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
- `GET /api/videos/{video_id}/file` - Download video file
- `DELETE /api/videos/{video_id}` - Delete a video

### Document Management
- `POST /api/documents/upload` - Upload PDF slides; file is saved under `storage/documents/` and metadata recorded in `data/documents.json`

## Example Usage

### Start a video download

```bash
curl -X POST "http://localhost:8000/api/videos/download" \
  -H "Content-Type: application/json" \
  -d '{
    "stream_url": "https://example.panopto.com/stream/...",
    "title": "My Video",
    "source_url": "https://example.panopto.com/..."
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

## Development

The server runs with auto-reload enabled when using the `--reload` flag, so changes to the code will automatically restart the server.

## Notes

- Videos are stored in the `storage/videos/` directory
- Audio-only files are stored in `storage/audio/` and share the same `video_id` filename
- Uploaded PDFs are stored in `storage/documents/` with metadata in `data/documents.json`
- Metadata (including transcript text/status) is stored in `data/videos.json`
- CORS is enabled for all origins (configure appropriately for production)

## Timestamp-aware chunking with Agno

To feed transcripts into Agno’s knowledge base while keeping the precise ElevenLabs timecodes,
use the `TimestampAwareChunking` strategy defined in `app/chunkings/chunking.py`. It converts the stored
`transcript_segments` (word-level timestamps) into chunks that include `start_ms`/`end_ms`
metadata so the frontend and agents can jump directly to the right moment in a lecture.

```python
from agno.knowledge.document.base import Document
from app.chunkings.chunking import TimestampAwareChunking

doc = Document(
    id=video_id,
    name=metadata["title"],
    content=metadata["transcript"],
    meta_data={
        "segments": metadata["transcript_segments"],
        "lecture_id": video_id,
        "source": "transcript",
    },
)

chunker = TimestampAwareChunking(max_words=110, max_duration_ms=75_000, overlap_ms=12_000)
chunks = chunker.chunk(doc)
```

Each emitted chunk inherits the transcript context and includes the millisecond offsets required
for semantic search + timestamp previews in your UI.
