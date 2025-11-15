import os
import subprocess
import tempfile
import threading
from datetime import datetime
from typing import Optional
import PanoptoDownloader
from PanoptoDownloader.exceptions import *
from app.transcriber import ElevenLabsTranscriber

class VideoDownloader:
    def __init__(self, storage, transcriber: Optional[ElevenLabsTranscriber] = None):
        self.storage = storage
        self.transcriber = transcriber
        self.downloads = {}  # Track active downloads
    
    def download_video(self, stream_url: str, video_id: str, title: Optional[str] = None, 
                      source_url: Optional[str] = None) -> str:
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
            self.downloads[job_id] = {
                "status": "completed",
                "progress": 100,
                "file_path": existing_video.get("file_path"),
                "audio_path": existing_video.get("audio_path"),
                "transcript": existing_video.get("transcript"),
                "transcript_status": existing_video.get("transcript_status"),
            }
            return job_id
        
        # Create unique temp file with video_id in name to avoid conflicts
        temp_dir = tempfile.gettempdir()
        temp_file_path = os.path.join(temp_dir, f"panopto_{job_id}_{datetime.now().strftime('%f')}.mp4")
        
        # Ensure temp file doesn't exist
        if os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
        
        # Mark as downloading
        self.downloads[job_id] = {
            "status": "downloading",
            "progress": 0,
            "audio_path": None,
            "transcript_status": "pending" if self.transcriber else None,
            "transcript": None,
        }
        
        # Start download in background thread
        thread = threading.Thread(
            target=self._download_worker,
            args=(stream_url, temp_file_path, job_id, title, source_url)
        )
        thread.daemon = True
        thread.start()
        
        return job_id
    
    def _download_worker(self, stream_url: str, temp_file: str, video_id: str, 
                        title: Optional[str], source_url: Optional[str]):
        """Background worker to download and store video"""
        audio_temp_file = None
        try:
            # Progress callback
            def progress_callback(progress: int):
                if video_id in self.downloads:
                    self.downloads[video_id]["progress"] = progress
            
            # Download to temp file
            PanoptoDownloader.download(stream_url, temp_file, progress_callback)
            audio_temp_file = self._convert_to_audio(temp_file, video_id)
            
            # Store video
            from app.models import VideoMetadata
            metadata = VideoMetadata(
                video_id=video_id,
                title=title,
                source_url=source_url,
                file_path="",  # Will be set by storage
                file_size=0,   # Will be set by storage
                uploaded_at=datetime.now().isoformat(),
                status="completed",
                transcript_status="pending" if self.transcriber else None
            )
            
            file_path = self.storage.store_video(temp_file, video_id, metadata)
            audio_path = None
            if audio_temp_file:
                audio_path = self.storage.store_audio(audio_temp_file, video_id)
            
            transcript_info = None
            if self.transcriber and audio_path:
                transcript_info = self._transcribe_audio(video_id, audio_path)
            elif not self.transcriber:
                self.storage.update_metadata(video_id, transcript_status="skipped")
            
            # Update status
            self.downloads[video_id] = {
                "status": "completed",
                "progress": 100,
                "file_path": file_path,
                "audio_path": audio_path,
                "transcript_status": (transcript_info or {}).get("status") if transcript_info else (
                    "skipped" if not self.transcriber else "pending"
                ),
                "transcript": (transcript_info or {}).get("text"),
            }
            
        except RegexNotMatch:
            error_msg = "Invalid stream URL"
            self._handle_error(video_id, error_msg)
        except FileExistsError as e:
            # Handle file already exists error
            error_msg = f"File already exists: {str(e)}. Trying to remove and retry..."
            # Try to remove the existing file and retry
            if os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                    # Retry download
                    PanoptoDownloader.download(stream_url, temp_file, progress_callback)
                    # Continue with storage if retry succeeds
                    from app.models import VideoMetadata
                    metadata = VideoMetadata(
                        video_id=video_id,
                        title=title,
                        source_url=source_url,
                        file_path="",
                        file_size=0,
                        uploaded_at=datetime.now().isoformat(),
                        status="completed"
                    )
                    file_path = self.storage.store_video(temp_file, video_id, metadata)
                    self.downloads[video_id] = {
                        "status": "completed",
                        "progress": 100,
                        "file_path": file_path
                    }
                except Exception as retry_error:
                    self._handle_error(video_id, f"Retry failed: {str(retry_error)}")
            else:
                self._handle_error(video_id, error_msg)
        except Exception as e:
            error_msg = str(e)
            # Check if it's a "file already exists" error in the message
            if "already exists" in error_msg.lower() or "File already exists" in error_msg:
                # Try to handle it by removing the file
                if os.path.exists(temp_file):
                    try:
                        os.unlink(temp_file)
                        error_msg = f"File conflict resolved. Please retry the download."
                    except:
                        pass
            self._handle_error(video_id, error_msg)
            # Clean up temp file on error
            if os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except:
                    pass
        finally:
            if audio_temp_file and os.path.exists(audio_temp_file):
                try:
                    os.unlink(audio_temp_file)
                except:
                    pass
    
    def _handle_error(self, video_id: str, error_msg: str):
        """Handle download errors"""
        self.downloads[video_id] = {
            "status": "failed",
            "progress": 0,
            "error": error_msg,
            "audio_path": None,
            "transcript_status": None,
            "transcript": None,
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
            return {
                "status": video["status"],
                "progress": 100 if video["status"] == "completed" else 0,
                "file_path": video["file_path"],
                "audio_path": video.get("audio_path"),
                "transcript": video.get("transcript"),
                "transcript_status": video.get("transcript_status"),
            }
        
        return {"status": "not_found"}

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
        )
        return result
