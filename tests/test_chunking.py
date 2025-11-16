import pytest
from agno.knowledge.document.base import Document

from app.chunking import TimestampAwareChunking


def build_doc(segments=None, content="Hello world"):
    meta = {}
    if segments is not None:
        meta["segments"] = segments
    return Document(
        id="lecture_1",
        name="Concurrency 101",
        content=content,
        meta_data=meta,
    )


def test_timestamp_chunker_preserves_start_end():
    segments = [
        {"text": "Good", "start_ms": 0, "end_ms": 500},
        {"text": "morning", "start_ms": 500, "end_ms": 1100},
        {"text": "everyone", "start_ms": 1100, "end_ms": 1900},
        {"text": "today", "start_ms": 1900, "end_ms": 2600},
    ]
    doc = build_doc(segments=segments)
    chunker = TimestampAwareChunking(max_words=2, max_duration_ms=2_000, overlap_ms=400)

    chunks = chunker.chunk(doc)

    assert len(chunks) == 3
    assert chunks[0].meta_data["start_ms"] == 0
    assert chunks[0].meta_data["end_ms"] == 1100
    assert "Good morning" in chunks[0].content

    assert chunks[1].meta_data["start_ms"] == 500  # overlap preserves previous tail
    assert chunks[1].meta_data["end_ms"] == 1900
    assert "morning everyone" in chunks[1].content

    assert chunks[2].meta_data["start_ms"] == 1900
    assert chunks[2].meta_data["end_ms"] == 2600
    assert "today" in chunks[2].content


def test_timestamp_chunker_fallback_without_segments():
    doc = build_doc(segments=None, content="One two three four five six")
    chunker = TimestampAwareChunking(max_words=2, overlap_ms=0)

    chunks = chunker.chunk(doc)

    assert len(chunks) == 3
    assert chunks[0].meta_data["chunking_strategy"] == "timestamp_aware_fallback"
    assert chunks[0].content == "One two"
