# StudyBuddy FastAPI - Panopto Video Downloader API

A FastAPI-based REST API for downloading videos from Panopto streaming URLs.

## Features

- Download videos from Panopto stream URLs
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
│   └── storage.py       # Local storage management
├── storage/
│   └── videos/          # Downloaded video files
├── data/                # Metadata and data files
├── requirements.txt     # Python dependencies
└── README.md           # This file
```

## Development

The server runs with auto-reload enabled when using the `--reload` flag, so changes to the code will automatically restart the server.

## Notes

- Videos are stored in the `storage/videos/` directory
- Metadata is stored in the `data/` directory
- CORS is enabled for all origins (configure appropriately for production)

