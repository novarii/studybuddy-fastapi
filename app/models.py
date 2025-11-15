from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class VideoDownloadRequest(BaseModel):
    stream_url: str
    video_id: Optional[str] = None
    title: Optional[str] = None
    source_url: Optional[str] = None
    metadata: Optional[dict] = None

class VideoMetadata(BaseModel):
    video_id: str
    title: Optional[str]
    source_url: Optional[str]
    file_path: str
    file_size: int
    uploaded_at: str
    status: str  # "downloading", "completed", "failed"
    error: Optional[str] = None
    audio_path: Optional[str] = None
    transcript: Optional[str] = None
    transcript_status: Optional[str] = None
    transcript_error: Optional[str] = None
