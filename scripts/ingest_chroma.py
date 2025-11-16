#!/usr/bin/env python3
"""Ingest course transcripts and slide descriptions into Chroma."""

from __future__ import annotations

import argparse
from typing import List, Optional

from app.chroma_ingestion import ChromaIngestionConfig, ChromaIngestionService
from app.database import CourseDatabase
from app.document_storage import DocumentStorage
from app.storage import LocalStorage


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
    parser.add_argument("--documents", help="Comma-separated list of document IDs to ingest.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    course_db = CourseDatabase()
    course = course_db.get_course(args.course_id)
    if not course:
        raise SystemExit(f"Course {args.course_id} not found. Create it via /api/courses first.")
    storage = LocalStorage()
    doc_storage = DocumentStorage()
    service = ChromaIngestionService(
        storage=storage,
        document_storage=doc_storage,
        config=ChromaIngestionConfig(
            chroma_path=args.chroma_path,
            lecture_collection=args.lecture_collection,
            slide_collection=args.slide_collection,
        ),
    )

    if args.lectures:
        lecture_ids: Optional[List[str]] = [item.strip() for item in args.lectures.split(",") if item.strip()]
    else:
        lecture_ids = service.lecture_ids_for_course(args.course_id)

    inserted_lectures = service.ingest_lectures(lecture_ids, user_id=args.user_id) if lecture_ids else 0
    if inserted_lectures:
        print(f"Inserted {inserted_lectures} lecture chunks into collection '{args.lecture_collection}'")

    document_ids = [item.strip() for item in (args.documents or "").split(",") if item.strip()]
    inserted_slides = service.ingest_slides(document_ids, user_id=args.user_id) if document_ids else 0
    if inserted_slides:
        print(f"Inserted {inserted_slides} slide chunks into collection '{args.slide_collection}'")

    if not inserted_lectures and not inserted_slides:
        raise SystemExit("No chunks were ingested. Ensure transcripts/slides exist for the provided IDs.")

    print(f"Data stored under {args.chroma_path}")


if __name__ == "__main__":
    main()
