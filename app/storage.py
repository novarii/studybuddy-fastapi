import os
import json
import shutil
from pathlib import Path
from typing import Optional, List, Dict
from app.models import VideoMetadata

_NOT_SET = object()

class LocalStorage:
    def __init__(self, storage_dir: str = "storage/videos", data_dir: str = "data", audio_dir: str = "storage/audio"):
        self.storage_dir = Path(storage_dir)
        self.data_dir = Path(data_dir)
        self.audio_dir = Path(audio_dir)
        self.transcripts_dir = self.data_dir / "transcripts"
        self.transcript_segments_dir = self.data_dir / "transcript_segments"
        self.metadata_file = self.data_dir / "videos.json"
        
        # Create directories if they don't exist
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_segments_dir.mkdir(parents=True, exist_ok=True)
        
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
        metadata.video_path = str(destination)
        metadata.video_size = file_size
        metadata.asset_type = "video"
        self.save_metadata_entry(metadata)

        return str(destination)

    def save_metadata_entry(self, metadata: VideoMetadata) -> None:
        """Persist the provided metadata model to disk."""
        metadata_dict = self._load_metadata()
        metadata_dict[metadata.video_id] = metadata.model_dump()
        self._save_metadata(metadata_dict)

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

        audio_size = destination.stat().st_size
        metadata = self._load_metadata().get(video_id, {})
        asset_type = "audio"
        if metadata.get("video_path") or metadata.get("file_path"):
            asset_type = "hybrid"
        self.update_metadata(
            video_id,
            audio_path=str(destination),
            audio_size=audio_size,
            asset_type=asset_type,
        )

        return str(destination)

    def update_metadata(self, video_id: str, **updates) -> bool:
        """Update stored metadata fields for a given video."""
        metadata = self._load_metadata()
        if video_id not in metadata:
            return False
        transcript_value = updates.pop("transcript", _NOT_SET)
        if transcript_value is not _NOT_SET:
            updates["transcript_path"] = self._write_transcript_file(video_id, transcript_value)
        segments_value = updates.pop("transcript_segments", _NOT_SET)
        if segments_value is not _NOT_SET:
            updates["transcript_segments_path"] = self._write_transcript_segments_file(video_id, segments_value)
        current_entry = self._ensure_asset_metadata(metadata[video_id])
        current_entry.update(updates)
        metadata[video_id] = self._ensure_asset_metadata(current_entry)
        self._save_metadata(metadata)
        return True
    
    def get_video(self, video_id: str) -> Optional[Dict]:
        """Get video metadata by ID"""
        metadata = self._load_metadata()
        entry = metadata.get(video_id)
        if not entry:
            return None
        return self._hydrate_payload(entry.copy())
    
    def list_videos(self) -> List[Dict]:
        """List all stored videos"""
        metadata = self._load_metadata()
        return [self._normalize_entry(entry) for entry in metadata.values()]
    
    def delete_video(self, video_id: str) -> bool:
        """Delete video file and metadata"""
        metadata = self._load_metadata()
        
        if video_id not in metadata:
            return False
        
        # Delete files
        entry = self._ensure_asset_metadata(metadata[video_id])
        video_path = entry.get("video_path") or entry.get("file_path")
        if video_path:
            video_file = Path(video_path)
            if video_file.exists():
                video_file.unlink()
        audio_path = entry.get("audio_path")
        if audio_path:
            audio_file = Path(audio_path)
            if audio_file.exists():
                audio_file.unlink()
        transcript_path = metadata[video_id].get("transcript_path")
        if transcript_path:
            transcript_file = Path(transcript_path)
            if transcript_file.exists():
                transcript_file.unlink()
        transcript_segments_path = metadata[video_id].get("transcript_segments_path")
        if transcript_segments_path:
            segments_file = Path(transcript_segments_path)
            if segments_file.exists():
                segments_file.unlink()
        
        # Remove from metadata
        del metadata[video_id]
        self._save_metadata(metadata)
        
        return True
    
    def get_audio_path(self, video_id: str) -> Optional[Path]:
        """Get the audio path for a lecture if available."""
        metadata = self._load_metadata()
        entry = metadata.get(video_id)
        if not entry:
            return None
        entry = self._ensure_asset_metadata(entry)
        audio_path = entry.get("audio_path")
        if audio_path and os.path.exists(audio_path):
            return Path(audio_path)
        return None

    def get_video_path(self, video_id: str) -> Optional[Path]:
        """Get the video path for legacy lectures if available."""
        metadata = self._load_metadata()
        entry = metadata.get(video_id)
        if not entry:
            return None
        entry = self._ensure_asset_metadata(entry)
        video_path = entry.get("video_path")
        if video_path and os.path.exists(video_path):
            return Path(video_path)
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_transcript_file(self, video_id: str, transcript: Optional[str]) -> Optional[str]:
        path = self.transcripts_dir / f"{video_id}.txt"
        if transcript is None:
            if path.exists():
                path.unlink()
            return None
        with path.open("w", encoding="utf-8") as handle:
            handle.write(transcript)
        return str(path)

    def _write_transcript_segments_file(self, video_id: str, segments: Optional[List[Dict]]) -> Optional[str]:
        path = self.transcript_segments_dir / f"{video_id}.json"
        if segments is None:
            if path.exists():
                path.unlink()
            return None
        with path.open("w", encoding="utf-8") as handle:
            json.dump(segments, handle, indent=2)
        return str(path)

    def _hydrate_payload(self, entry: Dict) -> Dict:
        normalized = self._normalize_entry(entry, hydrate_transcript=True)
        return normalized

    def _normalize_entry(self, entry: Dict, hydrate_transcript: bool = False) -> Dict:
        normalized = self._ensure_asset_metadata(entry.copy())
        if hydrate_transcript:
            transcript_path = normalized.get("transcript_path")
            if transcript_path and Path(transcript_path).exists():
                normalized["transcript"] = Path(transcript_path).read_text(encoding="utf-8")
            segments_path = normalized.get("transcript_segments_path")
            if segments_path and Path(segments_path).exists():
                with Path(segments_path).open("r", encoding="utf-8") as handle:
                    normalized["transcript_segments"] = json.load(handle)
        return normalized

    def _ensure_asset_metadata(self, entry: Dict) -> Dict:
        if entry is None:
            return entry
        legacy_path = entry.pop("file_path", None)
        if legacy_path and not entry.get("video_path"):
            entry["video_path"] = legacy_path
        legacy_size = entry.pop("file_size", None)
        if legacy_size is not None and entry.get("video_size") is None:
            entry["video_size"] = legacy_size
        asset_type = entry.get("asset_type")
        audio_path = entry.get("audio_path")
        video_path = entry.get("video_path")
        if not asset_type:
            if audio_path and video_path:
                entry["asset_type"] = "hybrid"
            elif audio_path:
                entry["asset_type"] = "audio"
            elif video_path:
                entry["asset_type"] = "video"
            else:
                entry["asset_type"] = "audio"
        return entry
