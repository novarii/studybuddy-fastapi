import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import UploadFile


class DocumentStorage:
    """Manage uploaded PDF documents and their metadata."""

    def __init__(self, storage_dir: str = "storage/documents", data_dir: str = "data"):
        self.storage_dir = Path(storage_dir)
        self.data_dir = Path(data_dir)
        self.metadata_file = self.data_dir / "documents.json"

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.metadata_file.exists():
            self._save_metadata({})

    def save_document(
        self, upload_file: UploadFile, document_id: Optional[str] = None
    ) -> Dict:
        """Persist the uploaded PDF to disk and record metadata."""
        doc_id = document_id or f"doc_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        destination = self.storage_dir / f"{doc_id}.pdf"

        # Write the file in chunks to avoid loading into memory.
        upload_file.file.seek(0)
        with destination.open("wb") as dest:
            while True:
                chunk = upload_file.file.read(1024 * 1024)
                if not chunk:
                    break
                dest.write(chunk)

        metadata_entry = {
            "document_id": doc_id,
            "original_filename": upload_file.filename,
            "content_type": upload_file.content_type,
            "file_path": str(destination),
            "file_size": destination.stat().st_size,
            "uploaded_at": datetime.now().isoformat(),
        }

        metadata = self._load_metadata()
        metadata[doc_id] = metadata_entry
        self._save_metadata(metadata)

        return metadata_entry

    def list_documents(self) -> Dict[str, Dict]:
        """Return all stored documents metadata."""
        return self._load_metadata()

    def get_document(self, document_id: str) -> Optional[Dict]:
        """Fetch metadata for a specific document if it exists."""
        metadata = self._load_metadata()
        return metadata.get(document_id)

    def save_slide_descriptions(self, document_id: str, descriptions: List[Dict]) -> Path:
        """Persist slide descriptions to disk and update metadata."""
        descriptions_dir = self.data_dir / "document_descriptions"
        descriptions_dir.mkdir(parents=True, exist_ok=True)
        output_path = descriptions_dir / f"{document_id}_slides.json"

        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(descriptions, fh, indent=2, ensure_ascii=False)

        metadata = self._load_metadata()
        if document_id in metadata:
            metadata[document_id]["slide_descriptions_path"] = str(output_path)
            metadata[document_id][
                "slide_descriptions_updated_at"
            ] = datetime.now().isoformat()
            metadata[document_id]["slide_page_count"] = len(descriptions)
            self._save_metadata(metadata)

        return output_path

    def delete_document(self, document_id: str) -> bool:
        """Remove a stored PDF and any generated slide descriptions."""
        metadata = self._load_metadata()
        entry = metadata.get(document_id)
        if not entry:
            return False

        # Delete PDF file
        file_path = Path(entry.get("file_path", ""))
        if file_path.exists():
            file_path.unlink()

        # Delete slide descriptions if present
        slide_path = entry.get("slide_descriptions_path")
        if slide_path:
            slide_file = Path(slide_path)
            if slide_file.exists():
                slide_file.unlink()

        del metadata[document_id]
        self._save_metadata(metadata)
        return True

    def _load_metadata(self) -> Dict[str, Dict]:
        try:
            with open(self.metadata_file, "r") as fh:
                return json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_metadata(self, metadata: Dict[str, Dict]) -> None:
        with open(self.metadata_file, "w") as fh:
            json.dump(metadata, fh, indent=2)
