#!/usr/bin/env python3
"""Ingest course transcripts and slide descriptions into Chroma."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.knowledge.document.base import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.chroma import ChromaDb
from dotenv import load_dotenv

from app.chunkings.chunking import TimestampAwareChunking
from app.chunkings.slide_chunking import chunk_slide_descriptions
from app.database import CourseDatabase
from app.document_storage import DocumentStorage
from app.storage import LocalStorage

TRANSCRIPTS_DIR = Path("data/transcripts")
TRANSCRIPT_SEGMENTS_DIR = Path("data/transcript_segments")
DOCUMENT_DESCRIPTIONS_DIR = Path("data/document_descriptions")


load_dotenv(".env.local", override=False)
load_dotenv(override=False)
if not os.getenv("OPENAI_API_KEY"):
    raise SystemExit("OPENAI_API_KEY missing. Populate it in .env.local or your environment before ingestion.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest course content into Chroma")
    parser.add_argument("--course-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--lecture-collection", default="course_lectures")
    parser.add_argument("--slide-collection", default="course_slides")
    parser.add_argument("--chroma-path", default="tmp/chromadb")
    parser.add_argument(
        "--lectures",
        help="Comma-separated list of lecture (video) IDs to ingest. Defaults to all lectures for the course.",
    )
    parser.add_argument(
        "--documents",
        help="Comma-separated list of document IDs (with slide descriptions) to ingest.",
    )
    return parser.parse_args()


def gather_lecture_chunks(
    storage: LocalStorage,
    course_id: str,
    course_name: str,
    user_id: str,
    lecture_ids: Optional[List[str]] = None,
) -> List[Document]:
    chunker = TimestampAwareChunking()
    chunks: List[Document] = []
    candidates = lecture_ids or [
        entry["video_id"]
        for entry in storage.list_videos()
        if entry.get("course_id") == course_id
    ]
    for video_id in candidates:
        video = storage.get_video(video_id)
        if not video:
            print(f"[warn] Lecture {video_id} missing from metadata; skipping")
            continue
        transcript = video.get("transcript")
        if not transcript:
            print(f"[warn] Lecture {video_id} has no transcript; skipping")
            continue
        segments = video.get("transcript_segments") or []
        doc = Document(
            id=video_id,
            name=video.get("title") or video_id,
            content=transcript,
            meta_data={
                "segments": segments,
                "lecture_id": video_id,
                "course_id": course_id,
                "course_name": video.get("course_name") or course_name,
                "user_id": user_id,
                "source": "transcript",
            },
        )
        lecture_chunks = chunker.chunk(doc)
        for chunk in lecture_chunks:
            chunk.meta_data.pop("segments", None)
        chunks.extend(lecture_chunks)
    return chunks


def gather_slide_chunks(
    documents: DocumentStorage,
    document_ids: List[str],
    course_id: str,
    course_name: str,
    user_id: str,
) -> List[Document]:
    chunks: List[Document] = []
    for doc_id in document_ids:
        metadata = documents.get_document(doc_id)
        if not metadata:
            print(f"[warn] Document {doc_id} not found; skipping")
            continue
        descriptions_path = metadata.get("slide_descriptions_path")
        if not descriptions_path:
            print(f"[warn] Document {doc_id} has no slide descriptions; run the slide agent first")
            continue
        path = Path(descriptions_path)
        if not path.exists():
            print(f"[warn] Slide description file missing for {doc_id}: {path}")
            continue
        with path.open("r", encoding="utf-8") as handle:
            descriptions: List[Dict] = json.load(handle)
        slide_chunks = chunk_slide_descriptions(
            descriptions=descriptions,
            document_id=doc_id,
            max_chars=2000,
            extra_meta={
                "course_id": course_id,
                "course_name": course_name,
                "user_id": user_id,
                "source": "slides",
            },
        )
        chunks.extend(slide_chunks)
    return chunks


def documents_to_contents(documents: List[Document]) -> List[Dict[str, Any]]:
    """
    Convert Document objects into Knowledge.add_contents payloads.
    """
    contents: List[Dict[str, Any]] = []
    for idx, doc in enumerate(documents, start=1):
        text = (doc.content or "").strip()
        if not text:
            continue
        metadata = dict(doc.meta_data or {})
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


def main() -> None:
    args = parse_args()
    course_db = CourseDatabase()
    course = course_db.get_course(args.course_id)
    if not course:
        raise SystemExit(f"Course {args.course_id} not found. Create it via /api/courses first.")
    course_name = course["name"]

    storage = LocalStorage()
    doc_storage = DocumentStorage()

    lecture_ids = [item.strip() for item in args.lectures.split(",") if item.strip()] if args.lectures else None
    document_ids = [item.strip() for item in args.documents.split(",") if item.strip()] if args.documents else []

    lecture_chunks = gather_lecture_chunks(storage, args.course_id, course_name, args.user_id, lecture_ids)
    slide_chunks = (
        gather_slide_chunks(doc_storage, document_ids, args.course_id, course_name, args.user_id)
        if document_ids else []
    )

    if not lecture_chunks and not slide_chunks:
        raise SystemExit("No chunks were produced. Ensure transcripts/slides exist for the provided inputs.")

    if lecture_chunks:
        lecture_knowledge = Knowledge(
            vector_db=ChromaDb(
                collection=args.lecture_collection,
                path=args.chroma_path,
                persistent_client=True,
            )
        )
        lecture_contents = documents_to_contents(lecture_chunks)
        lecture_knowledge.add_contents(lecture_contents)
        print(
            f"Inserted {len(lecture_chunks)} lecture chunks into collection '{args.lecture_collection}'"
        )

    if slide_chunks:
        slide_knowledge = Knowledge(
            vector_db=ChromaDb(
                collection=args.slide_collection,
                path=args.chroma_path,
                persistent_client=True,
            )
        )
        slide_contents = documents_to_contents(slide_chunks)
        slide_knowledge.add_contents(slide_contents)
        print(
            f"Inserted {len(slide_chunks)} slide chunks into collection '{args.slide_collection}'"
        )

    print(f"Data stored under {args.chroma_path}")


if __name__ == "__main__":
    main()
