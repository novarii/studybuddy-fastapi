#!/usr/bin/env python3
"""Utility to materialize transcript or slide chunks into JSON files for inspection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional

from agno.knowledge.document.base import Document

from app.chunkings.chunking import TimestampAwareChunking
from app.chunkings.slide_chunking import chunk_slide_descriptions

DATA_DIR = Path("data")
CHUNK_DIR = DATA_DIR / "chunks"
VIDEOS_JSON = DATA_DIR / "videos.json"
DOCUMENTS_JSON = DATA_DIR / "documents.json"


def load_json(path: Path) -> Dict:
    if not path.exists():
        raise FileNotFoundError(f"Missing metadata file: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Unable to parse {path}: {exc}") from exc


def export_transcript_chunks(video_id: str, limit: int | None = None) -> Path:
    videos = load_json(VIDEOS_JSON)
    metadata = videos.get(video_id)
    if not metadata:
        raise ValueError(f"Video {video_id} not found in {VIDEOS_JSON}")
    transcript = _load_transcript(metadata)
    segments = _load_transcript_segments(metadata)
    if not transcript:
        raise ValueError(f"Video {video_id} has no transcript text to chunk")

    document = Document(
        id=video_id,
        name=metadata.get("title") or video_id,
        content=transcript,
        meta_data={
            "segments": segments,
            "lecture_id": video_id,
            "course_id": metadata.get("course_id"),
            "source": "transcript",
        },
    )
    chunker = TimestampAwareChunking()
    chunks = chunker.chunk(document)

    if not chunks:
        raise RuntimeError(f"Chunker returned no chunks for {video_id}")

    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CHUNK_DIR / f"{video_id}_transcript_chunks.json"
    payload = [serialize_document(chunk) for chunk in chunks[:limit] if chunk]
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    return output_path


def export_slide_chunks(document_id: str, limit: int | None = None) -> Path:
    documents = load_json(DOCUMENTS_JSON)
    metadata = documents.get(document_id)
    if not metadata:
        raise ValueError(f"Document {document_id} not found in {DOCUMENTS_JSON}")

    descriptions_path = metadata.get("slide_descriptions_path")
    if not descriptions_path:
        raise ValueError(
            f"Document {document_id} has no slide descriptions yet. Run the slide agent first."
        )

    desc_file = Path(descriptions_path)
    if not desc_file.exists():
        raise FileNotFoundError(f"Slide descriptions file missing: {desc_file}")

    with desc_file.open("r", encoding="utf-8") as handle:
        descriptions: List[Dict] = json.load(handle)

    chunks = chunk_slide_descriptions(descriptions, document_id=document_id)
    if not chunks:
        raise RuntimeError(f"Slide chunker returned no chunks for {document_id}")

    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CHUNK_DIR / f"{document_id}_slide_chunks.json"
    payload = [serialize_document(chunk) for chunk in chunks[:limit] if chunk]
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    return output_path


def serialize_document(document: Document) -> Dict:
    return {
        "id": document.id,
        "name": document.name,
        "content": document.content,
        "meta_data": document.meta_data,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export chunks to JSON files for inspection")
    parser.add_argument("--video-id", help="Video ID to export transcript chunks")
    parser.add_argument("--document-id", help="Document ID to export slide chunks")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional number of chunks to export (defaults to all)",
    )
    args = parser.parse_args()
    if not args.video_id and not args.document_id:
        parser.error("Specify at least --video-id or --document-id")
    return args


def main() -> None:
    args = parse_args()
    if args.video_id:
        path = export_transcript_chunks(args.video_id, limit=args.limit)
        print(f"Transcript chunks written to {path}")
    if args.document_id:
        path = export_slide_chunks(args.document_id, limit=args.limit)
        print(f"Slide chunks written to {path}")


def _load_transcript(metadata: Dict) -> Optional[str]:
    text = metadata.get("transcript")
    if text:
        return text
    path = metadata.get("transcript_path")
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8")
    return None


def _load_transcript_segments(metadata: Dict) -> List[Dict]:
    segments = metadata.get("transcript_segments")
    if segments:
        return segments
    path = metadata.get("transcript_segments_path")
    if path and Path(path).exists():
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return []


if __name__ == "__main__":
    main()
