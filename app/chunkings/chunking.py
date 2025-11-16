"""
Custom chunking helpers for Agno Knowledge ingestion.

This module hosts a timestamp-aware chunker that aggregates ElevenLabs word
segments into semantic passages while preserving the millisecond offsets. The
resulting metadata lets downstream agents and UIs deep-link into lectures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document


@dataclass
class TimestampAwareChunking(ChunkingStrategy):
    """
    Chunk transcripts that include ElevenLabs `transcript_segments`.

    Parameters
    ----------
    max_words:
        Maximum number of word-level tokens in a chunk before we force a split.
    max_duration_ms:
        Maximum duration (in milliseconds) of a chunk. The chunker emits a
        chunk as soon as either `max_words` or `max_duration_ms` is reached.
    overlap_ms:
        Number of milliseconds of overlap to include from the previous chunk.
        Overlaps keep semantic continuity for questions that straddle chunk
        boundaries.
    """

    max_words: int = 120
    max_duration_ms: int = 90_000
    overlap_ms: int = 15_000

    def chunk(self, document: Document) -> List[Document]:
        segments = (document.meta_data or {}).get("segments") or []
        if not segments:
            # Fall back to naive splitting when no timestamp metadata exists.
            return self._fallback_chunks(document)

        chunks: List[Document] = []
        buffer: List[Dict[str, Any]] = []

        for item in segments:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            buffer.append(
                {
                    "text": text,
                    "start_ms": item.get("start_ms"),
                    "end_ms": item.get("end_ms"),
                }
            )

            if self._chunk_ready(buffer):
                chunks.append(self._flush_chunk(document, buffer, len(chunks)))
                buffer = self._overlap_tail(buffer)

        if buffer:
            chunks.append(self._flush_chunk(document, buffer, len(chunks)))

        return chunks

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #

    def _chunk_ready(self, buffer: List[Dict[str, Any]]) -> bool:
        if not buffer:
            return False
        if len(buffer) >= self.max_words:
            return True
        start = buffer[0].get("start_ms")
        end = buffer[-1].get("end_ms")
        if start is not None and end is not None:
            return (end - start) >= self.max_duration_ms
        return False

    def _flush_chunk(self, document: Document, buffer: List[Dict[str, Any]], chunk_idx: int) -> Document:
        content = self.clean_text(" ".join(entry["text"] for entry in buffer))
        meta = dict(document.meta_data or {})
        meta.update(
            {
                "chunk_index": chunk_idx + 1,
                "chunking_strategy": "timestamp_aware",
                "start_ms": buffer[0].get("start_ms"),
                "end_ms": buffer[-1].get("end_ms"),
            }
        )
        return Document(
            id=f"{document.id}_{chunk_idx + 1}" if document.id else None,
            name=document.name,
            meta_data=meta,
            content=content,
        )

    def _overlap_tail(self, buffer: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not buffer or self.overlap_ms <= 0:
            return []
        tail_start = buffer[-1].get("end_ms")
        if tail_start is None:
            return []
        tail_start -= self.overlap_ms
        return [entry for entry in buffer if (entry.get("end_ms") or 0) >= tail_start]

    def _fallback_chunks(self, document: Document) -> List[Document]:
        """
        When no timestamp metadata exists (older transcripts), fall back to a
        simple word-count split so ingestion can still proceed.
        """
        words = self.clean_text(document.content or "").split()
        chunks: List[Document] = []
        cursor = 0
        while cursor < len(words):
            chunk_words = words[cursor : cursor + self.max_words]
            cursor += self.max_words
            if not chunk_words:
                continue
            meta = dict(document.meta_data or {})
            meta.update(
                {
                    "chunk_index": len(chunks) + 1,
                    "chunking_strategy": "timestamp_aware_fallback",
                }
            )
            chunks.append(
                Document(
                    id=f"{document.id}_{len(chunks) + 1}" if document.id else None,
                    name=document.name,
                    meta_data=meta,
                    content=" ".join(chunk_words),
                )
            )
        return chunks
