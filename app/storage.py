import os
import json
import shutil
from pathlib import Path
from typing import Optional, List, Dict
from app.models import VideoMetadata

class LocalStorage:
    def __init__(self, storage_dir: str = "storage/videos", data_dir: str = "data", audio_dir: str = "storage/audio"):
        self.storage_dir = Path(storage_dir)
        self.data_dir = Path(data_dir)
        self.audio_dir = Path(audio_dir)
        self.metadata_file = self.data_dir / "videos.json"
        
        # Create directories if they don't exist
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize metadata file if it doesn't exist
        if not self.metadata_file.exists():
            self._save_metadata({})
    
    def _load_metadata(self) -> Dict:
        """Load metadata from JSON file"""
        try:
            with open(self.metadata_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def _save_metadata(self, metadata: Dict):
        """Save metadata to JSON file"""
        with open(self.metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
    
    def store_video(self, temp_file_path: str, video_id: str, metadata: VideoMetadata) -> str:
        """
        Move video from temp file to storage directory
        Returns the stored file path
        """
        # Generate filename
        filename = f"{video_id}.mp4"
        destination = self.storage_dir / filename
        
        # Check if destination already exists
        if destination.exists():
            # Remove existing file to avoid conflicts
            destination.unlink()
        
        # Move file (or copy if on different filesystem)
        if os.path.exists(temp_file_path):
            shutil.move(temp_file_path, destination)
        else:
            raise FileNotFoundError(f"Temp file not found: {temp_file_path}")
        
        # Get file size
        file_size = destination.stat().st_size
        
        # Update metadata
        metadata_dict = self._load_metadata()
        metadata_dict[video_id] = {
            "video_id": video_id,
            "title": metadata.title,
            "source_url": metadata.source_url,
            "file_path": str(destination),
            "file_size": file_size,
            "uploaded_at": metadata.uploaded_at,
            "status": metadata.status,
            "error": metadata.error,
            "audio_path": metadata.audio_path,
            "transcript": metadata.transcript,
            "transcript_status": metadata.transcript_status,
            "transcript_error": metadata.transcript_error,
            "transcript_segments": metadata.transcript_segments,
        }
        self._save_metadata(metadata_dict)
        
        return str(destination)

    def store_audio(self, temp_file_path: str, video_id: str) -> str:
        """Move extracted audio to storage/audio and update metadata"""
        filename = f"{video_id}.mp3"
        destination = self.audio_dir / filename

        if destination.exists():
            destination.unlink()

        if os.path.exists(temp_file_path):
            shutil.move(temp_file_path, destination)
        else:
            raise FileNotFoundError(f"Temp audio file not found: {temp_file_path}")

        self.update_metadata(video_id, audio_path=str(destination))

        return str(destination)

    def update_metadata(self, video_id: str, **updates) -> bool:
        """Update stored metadata fields for a given video."""
        metadata = self._load_metadata()
        if video_id not in metadata:
            return False
        metadata[video_id].update(updates)
        self._save_metadata(metadata)
        return True
    
    def get_video(self, video_id: str) -> Optional[Dict]:
        """Get video metadata by ID"""
        metadata = self._load_metadata()
        return metadata.get(video_id)
    
    def list_videos(self) -> List[Dict]:
        """List all stored videos"""
        metadata = self._load_metadata()
        return list(metadata.values())
    
    def delete_video(self, video_id: str) -> bool:
        """Delete video file and metadata"""
        metadata = self._load_metadata()
        
        if video_id not in metadata:
            return False
        
        # Delete files
        file_path = Path(metadata[video_id].get("file_path", ""))
        if file_path.exists():
            file_path.unlink()
        audio_path = metadata[video_id].get("audio_path")
        if audio_path:
            audio_file = Path(audio_path)
            if audio_file.exists():
                audio_file.unlink()
        
        # Remove from metadata
        del metadata[video_id]
        self._save_metadata(metadata)
        
        return True
    
    def get_file_path(self, video_id: str) -> Optional[Path]:
        """Get the file path for a video"""
        video = self.get_video(video_id)
        if video and os.path.exists(video["file_path"]):
            return Path(video["file_path"])
        return None
