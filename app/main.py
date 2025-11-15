from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.models import VideoDownloadRequest, VideoMetadata
from app.downloader import VideoDownloader
from app.storage import LocalStorage
from app.transcriber import ElevenLabsTranscriber
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
transcriber = ElevenLabsTranscriber()
downloader = VideoDownloader(storage, transcriber=transcriber)

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
            source_url=request.source_url
        )
        
        return {
            "status": "accepted",
            "job_id": job_id,
            "video_id": video_id,
            "message": "Video download started"
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
