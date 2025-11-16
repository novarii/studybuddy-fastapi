import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.models import VideoDownloadRequest, VideoMetadata, CourseCreateRequest
from app.downloader import VideoDownloader
from app.storage import LocalStorage
from app.document_storage import DocumentStorage
from app.transcriber import ElevenLabsTranscriber
from app.pdf_slide_description_agent import PDFSlideDescriptionAgent
from app.database import CourseDatabase
import os

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
downloader = VideoDownloader(storage, transcriber=transcriber)
pdf_slide_agent = PDFSlideDescriptionAgent()
course_db = CourseDatabase()

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
async def upload_document(file: UploadFile = File(...)):
    """Upload a PDF document (slides) and store it locally."""
    if not file.filename.lower().endswith(".pdf") or file.content_type not in {
        "application/pdf",
        "application/octet-stream",
    }:
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    metadata = document_storage.save_document(file)
    await file.close()
    return {"status": "stored", "document": metadata}


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

    return {
        "document_id": document_id,
        "pages_processed": len(description_payload),
        "descriptions_path": str(descriptions_path),
        "descriptions": description_payload,
    }


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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
