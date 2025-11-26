import os
import subprocess
import tempfile
import threading
from datetime import datetime
from typing import Optional, TYPE_CHECKING

import PanoptoDownloader
from PanoptoDownloader.exceptions import *

from app.transcriber import ElevenLabsTranscriber

if TYPE_CHECKING:
    from app.chroma_ingestion import ChromaIngestionService

class VideoDownloader:
    def __init__(
        self,
        storage,
        transcriber: Optional[ElevenLabsTranscriber] = None,
        ingestion_service: Optional["ChromaIngestionService"] = None,
    ):
        self.storage = storage
        self.transcriber = transcriber
        self.ingestion_service = ingestion_service
        self.downloads = {}  # Track active downloads
    
    def download_video(
        self,
        stream_url: str,
        video_id: str,
        title: Optional[str] = None,
        source_url: Optional[str] = None,
        course_id: Optional[str] = None,
        course_name: Optional[str] = None,
        audio_only: bool = True,
    ) -> str:
        """
        Download video from stream URL to local storage
        Returns job_id for tracking
        """
        # Generate job_id if video_id not provided
        job_id = video_id or f"video_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        
        # Check if video already exists
        existing_video = self.storage.get_video(job_id)
        if existing_video and existing_video.get("status") == "completed":
            # Video already exists, return existing status
            self.downloads[job_id] = self._status_payload_from_video(existing_video)
            return job_id

        temp_file_path: Optional[str] = None
        if not audio_only:
            # Create unique temp file with video_id in name to avoid conflicts
            temp_dir = tempfile.gettempdir()
            temp_file_path = os.path.join(temp_dir, f"panopto_{job_id}_{datetime.now().strftime('%f')}.mp4")
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

        # Mark as downloading
        self.downloads[job_id] = {
            "status": "downloading",
            "progress": 0,
            "audio_path": None,
            "video_path": None,
            "asset_type": "audio" if audio_only else "hybrid",
            "transcript_status": "pending" if self.transcriber else None,
            "transcript": None,
            "transcript_segments": None,
            "course_id": course_id,
            "course_name": course_name,
            "audio_only": audio_only,
            "remote_video_url": source_url or stream_url,
        }
        
        # Start download in background thread
        thread = threading.Thread(
            target=self._download_worker,
            args=(stream_url, temp_file_path, job_id, title, source_url, course_id, course_name, audio_only)
        )
        thread.daemon = True
        thread.start()
        
        return job_id
    
    def _download_worker(
        self,
        stream_url: str,
        temp_file: Optional[str],
        video_id: str,
        title: Optional[str],
        source_url: Optional[str],
        course_id: Optional[str],
        course_name: Optional[str],
        audio_only: bool,
    ):
        """Background worker to download and store video/audio"""
        audio_temp_file = None
        try:
            def progress_callback(progress: int):
                if video_id in self.downloads:
                    self.downloads[video_id]["progress"] = progress

            from app.models import VideoMetadata
            metadata = VideoMetadata(
                video_id=video_id,
                title=title,
                source_url=source_url or stream_url,
                course_id=course_id,
                course_name=course_name,
                uploaded_at=datetime.now().isoformat(),
                status="completed",
                transcript_status="pending" if self.transcriber else None,
                audio_only=audio_only,
                asset_type="audio" if audio_only else "hybrid",
                remote_video_url=source_url or stream_url,
            )

            video_path = None
            audio_path = None

            if audio_only:
                audio_temp_file = self._download_audio_stream(stream_url, video_id)
                self.storage.save_metadata_entry(metadata)
            else:
                PanoptoDownloader.download(stream_url, temp_file, progress_callback)
                audio_temp_file = self._convert_to_audio(temp_file, video_id)
                video_path = self.storage.store_video(temp_file, video_id, metadata)

            if audio_temp_file:
                audio_path = self.storage.store_audio(audio_temp_file, video_id)
            else:
                self.storage.update_metadata(video_id, asset_type="video" if video_path else "audio")

            transcript_info = None
            if self.transcriber and audio_path:
                transcript_info = self._transcribe_audio(video_id, audio_path)
            elif not self.transcriber:
                self.storage.update_metadata(video_id, transcript_status="skipped")

            if (
                self.ingestion_service
                and transcript_info
                and transcript_info.get("status") == "completed"
            ):
                self._ingest_lecture(video_id)

            # Update status
            self.downloads[video_id] = {
                "status": "completed",
                "progress": 100,
                "audio_path": audio_path,
                "video_path": video_path,
                "asset_type": "audio"
                if (audio_only and not video_path)
                else ("hybrid" if audio_path and video_path else "video"),
                "transcript_status": (transcript_info or {}).get("status")
                if transcript_info
                else ("skipped" if not self.transcriber else "pending"),
                "transcript": (transcript_info or {}).get("text"),
                "transcript_segments": (transcript_info or {}).get("segments"),
                "course_id": course_id,
                "course_name": course_name,
                "audio_only": audio_only,
                "remote_video_url": metadata.remote_video_url,
            }

        except RegexNotMatch:
            self._handle_error(video_id, "Invalid stream URL")
        except FileExistsError as exc:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except OSError:
                    pass
            self._handle_error(video_id, f"File already exists: {exc}")
        except Exception as e:
            error_msg = str(e)
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except OSError:
                    pass
            self._handle_error(video_id, error_msg)
        finally:
            if audio_temp_file and os.path.exists(audio_temp_file):
                try:
                    os.unlink(audio_temp_file)
                except OSError:
                    pass
    
    def _handle_error(self, video_id: str, error_msg: str):
        """Handle download errors"""
        self.downloads[video_id] = {
            "status": "failed",
            "progress": 0,
            "error": error_msg,
            "audio_path": None,
            "video_path": None,
            "asset_type": None,
            "transcript_status": None,
            "transcript": None,
            "transcript_segments": None,
        }
        
        # Also update metadata if it exists
        video = self.storage.get_video(video_id)
        if video:
            self.storage.update_metadata(video_id, status="failed", error=error_msg)
    
    def get_status(self, video_id: str) -> dict:
        """Get download status"""
        # Check active downloads
        if video_id in self.downloads:
            return self.downloads[video_id]
        
        # Check stored videos
        video = self.storage.get_video(video_id)
        if video:
            return self._status_payload_from_video(video)
        
        return {"status": "not_found"}

    def _status_payload_from_video(self, video: dict) -> dict:
        """Normalize stored metadata into the status schema used by the API."""
        return {
            "status": video.get("status"),
            "progress": 100 if video.get("status") == "completed" else 0,
            "audio_path": video.get("audio_path"),
            "video_path": video.get("video_path"),
            "asset_type": video.get("asset_type"),
            "transcript": video.get("transcript"),
            "transcript_status": video.get("transcript_status"),
            "transcript_segments": video.get("transcript_segments"),
            "course_id": video.get("course_id"),
            "course_name": video.get("course_name"),
            "audio_only": video.get("audio_only"),
            "remote_video_url": video.get("remote_video_url"),
        }

    def _convert_to_audio(self, video_path: str, video_id: str) -> Optional[str]:
        """Use ffmpeg to extract audio from the downloaded video"""
        temp_dir = tempfile.gettempdir()
        audio_temp_file = os.path.join(
            temp_dir, f"panopto_{video_id}_{datetime.now().strftime('%f')}.mp3"
        )
        cmd = [
            "ffmpeg",
            "-y",  # overwrite if exists
            "-i", video_path,
            "-vn",
            "-acodec", "mp3",
            audio_temp_file,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg audio extraction failed for {video_id}: {result.stderr.decode('utf-8', 'ignore')}"
            )
        return audio_temp_file

    def _download_audio_stream(self, stream_url: str, video_id: str) -> str:
        """Download only the audio track from the remote stream using ffmpeg."""
        temp_dir = tempfile.gettempdir()
        audio_temp_file = os.path.join(
            temp_dir, f"panopto_audio_{video_id}_{datetime.now().strftime('%f')}.m4a"
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            stream_url,
            "-vn",
            "-acodec",
            "copy",
            audio_temp_file,
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg audio-only download failed for {video_id}: {result.stderr.decode('utf-8', 'ignore')}"
            )
        return audio_temp_file

    def _transcribe_audio(self, video_id: str, audio_path: str) -> Optional[dict]:
        """Run audio through ElevenLabs transcription and persist metadata."""
        if not self.transcriber:
            return None
        try:
            result = self.transcriber.transcribe(audio_path)
        except Exception as exc:
            result = {
                "status": "failed",
                "text": None,
                "error": str(exc),
            }
        self.storage.update_metadata(
            video_id,
            transcript=result.get("text"),
            transcript_status=result.get("status"),
            transcript_error=result.get("error"),
            transcript_segments=result.get("segments"),
        )
        return result

    def _ingest_lecture(self, video_id: str) -> None:
        """Send the completed lecture transcript into Chroma."""
        if not self.ingestion_service:
            return
        try:
            inserted = self.ingestion_service.ingest_lectures([video_id])
            if inserted:
                print(f"[info] Ingested {inserted} chunks for lecture {video_id} into Chroma.")
            else:
                print(f"[warn] No chunks produced for lecture {video_id}; ingestion skipped.")
        except Exception as exc:
            print(f"[warn] Failed to ingest lecture {video_id} into Chroma: {exc}")
