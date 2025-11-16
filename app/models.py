from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime

class VideoDownloadRequest(BaseModel):
    stream_url: str
    video_id: Optional[str] = None
    title: Optional[str] = None
    source_url: Optional[str] = None
    metadata: Optional[dict] = None
    course_id: Optional[str] = None
    course_name: Optional[str] = None

class VideoMetadata(BaseModel):
    video_id: str
    title: Optional[str]
    source_url: Optional[str]
    course_id: Optional[str] = None
    course_name: Optional[str] = None
    file_path: str
    file_size: int
    uploaded_at: str
    status: str  # "downloading", "completed", "failed"
    error: Optional[str] = None
    audio_path: Optional[str] = None
    transcript: Optional[str] = None
    transcript_path: Optional[str] = None
    transcript_status: Optional[str] = None
    transcript_error: Optional[str] = None
    transcript_segments: Optional[List[Dict[str, Any]]] = None
    transcript_segments_path: Optional[str] = None


class CourseCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    source: Literal["lectures", "slides", "combined"] = "combined"
    user_id: Optional[str] = None
    course_id: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    reply: str
    source: Literal["lectures", "slides", "combined"]
    references: Optional[List[Dict[str, Any]]] = None
    session_id: Optional[str] = None


class CourseUnitCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    position: Optional[int] = None


class CourseTopicCreateRequest(BaseModel):
    title: str = Field(..., min_length=1)
    description: Optional[str] = None
    position: Optional[int] = None
