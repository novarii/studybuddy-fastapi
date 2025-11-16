"""
Utilities for ingesting lecture transcripts and slide descriptions into Chroma.

This module exposes a reusable service so ingestion can be triggered from both
scripts and runtime workflows (FastAPI routes, download workers, etc.).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from agno.knowledge.document.base import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.chroma import ChromaDb
from dotenv import load_dotenv

from app.chunkings.chunking import TimestampAwareChunking
from app.chunkings.slide_chunking import chunk_slide_descriptions
from app.document_storage import DocumentStorage
from app.storage import LocalStorage


@dataclass
class ChromaIngestionConfig:
    chroma_path: str = "tmp/chromadb"
    lecture_collection: str = "course_lectures"
    slide_collection: str = "course_slides"


class ChromaIngestionService:
    """
    Shared ingestion utilities so scripts and runtime events can store chunks
    inside Chroma without duplicating Knowledge code.
    """

    def __init__(
        self,
        storage: LocalStorage,
        document_storage: DocumentStorage,
        config: Optional[ChromaIngestionConfig] = None,
    ) -> None:
        self.storage = storage
        self.document_storage = document_storage
        self.config = config or ChromaIngestionConfig()
        self.lecture_chunker = TimestampAwareChunking()
        self._ensure_openai_key()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def ingest_lectures(self, lecture_ids: Iterable[str], user_id: Optional[str] = None) -> int:
        """Chunk and ingest the requested lecture transcripts."""
        chunks: List[Document] = []
        for lecture_id in lecture_ids:
            document = self._build_lecture_document(lecture_id, user_id=user_id)
            if not document:
                continue
            lecture_chunks = self.lecture_chunker.chunk(document)
            for chunk in lecture_chunks:
                chunk.meta_data.pop("segments", None)
            chunks.extend(lecture_chunks)
        if not chunks:
            return 0
        return self._ingest_chunks(
            chunks=chunks,
            collection=self.config.lecture_collection,
        )

    def ingest_slides(
        self,
        document_ids: Iterable[str],
        user_id: Optional[str] = None,
        max_chars: int = 2000,
    ) -> int:
        """Chunk pre-generated slide descriptions and ingest them."""
        chunks: List[Document] = []
        for document_id in document_ids:
            descriptions_path = self._get_slide_description_path(document_id)
            if not descriptions_path:
                continue
            with descriptions_path.open("r", encoding="utf-8") as handle:
                descriptions: List[Dict[str, Any]] = json.load(handle)
            extra_meta = {"source": "slides"}
            if user_id:
                extra_meta["user_id"] = user_id
            slide_chunks = chunk_slide_descriptions(
                descriptions=descriptions,
                document_id=document_id,
                max_chars=max_chars,
                extra_meta=extra_meta,
            )
            chunks.extend(slide_chunks)
        if not chunks:
            return 0
        return self._ingest_chunks(
            chunks=chunks,
            collection=self.config.slide_collection,
        )

    def lecture_ids_for_course(self, course_id: str) -> List[str]:
        """Return all lecture IDs recorded for a given course."""
        return [
            entry["video_id"]
            for entry in self.storage.list_videos()
            if entry.get("course_id") == course_id
        ]

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _build_lecture_document(self, lecture_id: str, user_id: Optional[str]) -> Optional[Document]:
        video = self.storage.get_video(lecture_id)
        if not video:
            print(f"[warn] Lecture {lecture_id} not found in metadata; skipping ingestion")
            return None
        transcript = video.get("transcript")
        if not transcript:
            print(f"[warn] Lecture {lecture_id} has no transcript; skipping ingestion")
            return None
        segments = video.get("transcript_segments") or []
        metadata = {
            "lecture_id": lecture_id,
            "source": "transcript",
            "segments": segments,
        }
        if user_id:
            metadata["user_id"] = user_id
        return Document(
            id=lecture_id,
            name=video.get("title") or lecture_id,
            content=transcript,
            meta_data=metadata,
        )

    def _get_slide_description_path(self, document_id: str) -> Optional[Path]:
        metadata = self.document_storage.get_document(document_id)
        if not metadata:
            print(f"[warn] Document {document_id} missing from metadata; skipping ingestion")
            return None
        descriptions_path = metadata.get("slide_descriptions_path")
        if not descriptions_path:
            print(f"[warn] Document {document_id} has no slide descriptions; skipping ingestion")
            return None
        path = Path(descriptions_path)
        if not path.exists():
            print(f"[warn] Slide description file for {document_id} is missing at {path}")
            return None
        return path

    def _ingest_chunks(self, chunks: List[Document], collection: str) -> int:
        contents = self._documents_to_contents(chunks)
        if not contents:
            return 0
        knowledge = Knowledge(
            vector_db=ChromaDb(
                collection=collection,
                path=self.config.chroma_path,
                persistent_client=True,
            )
        )
        knowledge.add_contents(contents)
        return len(contents)

    def _documents_to_contents(self, documents: List[Document]) -> List[Dict[str, Any]]:
        contents: List[Dict[str, Any]] = []
        for idx, doc in enumerate(documents, start=1):
            text = (doc.content or "").strip()
            if not text:
                continue
            metadata = dict(doc.meta_data or {})
            metadata.pop("course_id", None)
            metadata.pop("course_name", None)
            metadata.pop("segments", None)
            if doc.id:
                metadata.setdefault("chunk_id", doc.id)
            name = doc.name or metadata.get("chunk_id") or doc.id or f"chunk_{idx}"
            contents.append(
                {
                    "name": name,
                    "text_content": text,
                    "metadata": metadata,
                }
            )
        return contents

    def _ensure_openai_key(self) -> None:
        # Loading the dotenv files multiple times is cheap and keeps scripts + server aligned.
        load_dotenv(".env.local", override=False)
        load_dotenv(override=False)
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY missing. Populate it in .env.local or export it before running ingestion."
            )
