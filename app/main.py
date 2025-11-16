import sqlite3
from pathlib import Path

import json

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from app.models import (
    VideoDownloadRequest,
    VideoMetadata,
    CourseCreateRequest,
    ChatRequest,
    ChatResponse,
)
from app.downloader import VideoDownloader
from app.storage import LocalStorage
from app.document_storage import DocumentStorage
from app.transcriber import ElevenLabsTranscriber
from app.pdf_slide_description_agent import PDFSlideDescriptionAgent
from app.database import CourseDatabase
from app.chroma_ingestion import ChromaIngestionService
from app.chat_agent import StudyBuddyChatAgent
from agno.run.agent import RunEvent

app = FastAPI(title="Panopto Video Downloader API")

# CORS middleware (allow browser extension to call API)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize storage, transcription, and downloader
storage = LocalStorage(storage_dir="storage/videos", data_dir="data")
document_storage = DocumentStorage(storage_dir="storage/documents", data_dir="data")
transcriber = ElevenLabsTranscriber()
chroma_ingestor = ChromaIngestionService(storage=storage, document_storage=document_storage)
downloader = VideoDownloader(storage, transcriber=transcriber, ingestion_service=chroma_ingestor)
pdf_slide_agent = PDFSlideDescriptionAgent()
course_db = CourseDatabase()
chat_agent = StudyBuddyChatAgent(config=chroma_ingestor.config)

@app.get("/")
async def root():
    return {"message": "Panopto Video Downloader API", "status": "running"}

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "storage_dir": str(storage.storage_dir),
        "storage_exists": storage.storage_dir.exists()
    }

@app.post("/api/videos/download")
async def download_video(request: VideoDownloadRequest):
    """
    Start downloading a video from Panopto stream URL
    """
    try:
        # Validate stream URL
        if not request.stream_url:
            raise HTTPException(status_code=400, detail="stream_url is required")

        if not request.course_id:
            raise HTTPException(status_code=400, detail="course_id is required")

        course = course_db.get_course(request.course_id)
        if not course:
            raise HTTPException(status_code=404, detail="Course not found")

        # Prefer canonical course name from DB if available
        course_name = request.course_name or course["name"]
        if course["name"] and course["name"] != course_name:
            course_name = course["name"]
        
        # Generate video_id if not provided
        video_id = request.video_id
        if not video_id:
            from datetime import datetime
            video_id = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        
        # Start download
        job_id = downloader.download_video(
            stream_url=request.stream_url,
            video_id=video_id,
            title=request.title,
            source_url=request.source_url,
            course_id=request.course_id,
            course_name=course_name,
        )
        
        return {
            "status": "accepted",
            "job_id": job_id,
            "video_id": video_id,
            "message": "Video download started",
            "course_id": request.course_id,
            "course_name": course_name,
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/videos")
async def list_videos():
    """List all stored videos"""
    videos = storage.list_videos()
    return {"videos": videos, "count": len(videos)}

@app.get("/api/videos/active")
async def list_active_downloads():
    """List all active downloads (in progress or recently completed)"""
    active_downloads = downloader.downloads
    return {"downloads": active_downloads, "count": len(active_downloads)}

@app.get("/api/videos/{video_id}/status")
async def get_video_status(video_id: str):
    """Get download status for a video"""
    status = downloader.get_status(video_id)
    
    if status.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Video not found")
    
    return status

@app.get("/api/videos/{video_id}")
async def get_video_info(video_id: str):
    """Get video metadata"""
    video = storage.get_video(video_id)
    
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    return video

@app.get("/api/videos/{video_id}/file")
async def download_video_file(video_id: str):
    """Download the video file"""
    file_path = storage.get_file_path(video_id)
    
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")
    
    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        filename=file_path.name
    )

@app.delete("/api/videos/{video_id}")
async def delete_video(video_id: str):
    """Delete a video"""
    success = storage.delete_video(video_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Video not found")
    
    return {"status": "deleted", "video_id": video_id}

@app.post("/api/documents/upload")
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Upload a PDF document (slides) and store it locally."""
    if not file.filename.lower().endswith(".pdf") or file.content_type not in {
        "application/pdf",
        "application/octet-stream",
    }:
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    metadata = document_storage.save_document(file)
    await file.close()
    background_tasks.add_task(process_document_pipeline, metadata["document_id"])
    return {"status": "stored", "document": metadata, "processing": "queued"}


@app.post("/api/documents/{document_id}/slides/describe")
async def describe_document_slides(document_id: str):
    """Generate structured slide descriptions for an uploaded PDF."""
    document = document_storage.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    pdf_path = Path(document.get("file_path", ""))
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    try:
        descriptions = pdf_slide_agent.process_pdf(pdf_path=pdf_path)
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    description_payload = [desc.model_dump() for desc in descriptions]
    descriptions_path = document_storage.save_slide_descriptions(
        document_id=document_id,
        descriptions=description_payload,
    )
    ingested_chunks = 0
    try:
        ingested_chunks = chroma_ingestor.ingest_slides([document_id])
    except Exception as exc:
        print(f"[warn] Failed to ingest slide descriptions for {document_id}: {exc}")

    return {
        "document_id": document_id,
        "pages_processed": len(description_payload),
        "descriptions_path": str(descriptions_path),
        "descriptions": description_payload,
        "ingested_chunks": ingested_chunks,
    }


@app.delete("/api/documents/{document_id}")
async def delete_document(document_id: str):
    """Delete a stored PDF and any derived slide descriptions."""
    deleted = document_storage.delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"status": "deleted", "document_id": document_id}


@app.post("/api/courses")
async def create_course(request: CourseCreateRequest):
    """Create a new course entry before uploading lectures."""
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Course name cannot be empty")

    from datetime import datetime

    course_id = f"course_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

    try:
        course_db.create_course(course_id=course_id, name=name)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="Course ID already exists") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"course": {"id": course_id, "name": name}}


@app.get("/api/courses")
async def list_courses():
    """List all available courses."""
    rows = course_db.list_courses()
    return {"courses": [dict(row) for row in rows], "count": len(rows)}


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """Chat with the Agno agent backed by Chroma knowledge."""
    try:
        result = chat_agent.respond(
            message=request.message,
            source=request.source,
            user_id=request.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(
        reply=result.reply,
        source=result.source,
        references=result.references,
    )


@app.post("/api/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    """Stream chat responses chunk-by-chunk using server-sent events."""

    def event_generator():
        try:
            stream = chat_agent.stream_response(
                message=request.message,
                source=request.source,
                user_id=request.user_id,
            )
            for chunk in stream:
                payload = {"event": chunk.event}
                if getattr(chunk, "content", None) is not None:
                    payload["content"] = str(chunk.content)
                if getattr(chunk, "tools", None):
                    payload["tools"] = [tool.__dict__ for tool in chunk.tools]
                yield f"data: {json.dumps(payload)}\n\n"
        except Exception as exc:
            error_payload = {"event": "error", "message": str(exc)}
            yield f"data: {json.dumps(error_payload)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def process_document_pipeline(document_id: str) -> None:
    """Background pipeline to describe slides and ingest them into Chroma."""
    document = document_storage.get_document(document_id)
    if not document:
        print(f"[warn] Document {document_id} vanished before processing.")
        return
    pdf_path = Path(document.get("file_path", ""))
    if not pdf_path.exists():
        print(f"[warn] PDF path missing for {document_id}: {pdf_path}")
        return
    try:
        descriptions = pdf_slide_agent.process_pdf(pdf_path=pdf_path)
    except HTTPException as exc:
        print(f"[warn] Slide agent rejected document {document_id}: {exc.detail}")
        return
    except Exception as exc:
        print(f"[warn] Failed to process slides for {document_id}: {exc}")
        return

    description_payload = [desc.model_dump() for desc in descriptions]
    try:
        document_storage.save_slide_descriptions(document_id=document_id, descriptions=description_payload)
    except Exception as exc:
        print(f"[warn] Failed to persist slide descriptions for {document_id}: {exc}")
        return

    try:
        ingested = chroma_ingestor.ingest_slides([document_id])
        print(f"[info] Ingested {ingested} slide chunks for document {document_id}.")
    except Exception as exc:
        print(f"[warn] Failed to ingest slide descriptions for {document_id}: {exc}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
