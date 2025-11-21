"""
Client-facing chat agent that searches lecture or slide knowledge stored in Chroma.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, Iterator, List, Literal, Optional, Sequence, Tuple

from agno.agent import Agent
from agno.knowledge.document.base import Document
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutputEvent
from agno.vectordb.chroma import ChromaDb
from dotenv import load_dotenv

from app.chroma_ingestion import ChromaIngestionConfig


logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(levelname)s] %(name)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False


@dataclass
class ChatAgentResult:
    reply: str
    source: Literal["lectures", "slides", "combined"]
    references: Optional[List[Dict]] = None


class StudyBuddyChatAgent:
    """Wrap Agno Agent so FastAPI routes can relay responses to the frontend."""

    def __init__(
        self,
        config: Optional[ChromaIngestionConfig] = None,
        *, model_id: Optional[str] = None
    ) -> None:
        self._ensure_openai_key()
        self.config = config or ChromaIngestionConfig()
        self.model_id = model_id or os.getenv("CHAT_MODEL_ID", "gpt-4o-mini")

        self.lecture_knowledge = self._build_knowledge(
            collection=self.config.lecture_collection,
            path=self.config.chroma_path,
        )
        self.slide_knowledge = self._build_knowledge(
            collection=self.config.slide_collection,
            path=self.config.chroma_path,
        )

        combined_instructions = (
            "You are Study Buddy, an enthusiastic friend who attends every single lecture and takes meticulous notes. "
            "You're built to help students succeed by providing answers grounded exclusively in the course material.\n\n"
            
            "Your role:\n"
            "- You're the friend who never misses class and remembers everything the instructor said\n"
            "- You provide relevant, accurate answers based solely on the ingested lecture transcripts and slide descriptions\n"
            "- You search through all available lectures and slides to find the most course-relevant information\n"
            "- You keep your answers grounded to what the instructor actually taught - no outside information\n\n"
            
            "When answering:\n"
            "1. Search the relevant lectures and slides thoroughly to find information that addresses the question\n"
            "2. Always cite which specific lecture or slide informed your answer (e.g., 'In Lecture 5 on caching...' or 'According to Slide 12 from the Parallel Systems lecture...')\n"
            "3. If the answer isn't covered in the course material, honestly say so - don't make things up or use outside knowledge\n"
            "4. Be friendly and conversational, like a classmate explaining concepts, but stay factual and grounded in what was taught\n"
            "5. When multiple lectures cover a topic, reference all relevant sources\n\n"
            
            "Remember: Your superpower is perfect attendance and recall of everything the instructor said. "
            "Use that to give students the most relevant, course-specific answers possible."
        )
        self.agent = Agent(
            model=OpenAIChat(id=self.model_id),
            knowledge_retriever=self._knowledge_retriever,
            search_knowledge=True,
            instructions=combined_instructions,
            markdown=True,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def respond(
        self,
        *,
        message: str,
        source: Literal["lectures", "slides", "combined"] = "combined",
        user_id: Optional[str] = None,
    ) -> ChatAgentResult:
        filters: Dict[str, str] = {}
        if user_id:
            filters["user_id"] = user_id

        run_output = self.agent.run(
            message,
            knowledge_filters=filters or None,
            source=source,
        )
        reply = self._normalize_content(run_output.content)
        references = self._normalize_references(run_output.references)
        return ChatAgentResult(reply=reply, source=source, references=references)

    def stream_response(
        self,
        *,
        message: str,
        source: Literal["lectures", "slides", "combined"] = "combined",
        user_id: Optional[str] = None,
    ) -> Iterator[RunOutputEvent]:
        filters: Dict[str, str] = {}
        if user_id:
            filters["user_id"] = user_id
        stream = self.agent.run(
            message,
            knowledge_filters=filters or None,
            source=source,
            stream=True,
            stream_events=True,
        )
        return stream  # Iterator[RunOutputEvent]

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _build_knowledge(self, *, collection: str, path: str) -> Knowledge:
        return Knowledge(
            vector_db=ChromaDb(
                collection=collection,
                path=path,
                persistent_client=True,
            )
        )

    def _knowledge_retriever(
        self,
        *,
        query: str,
        num_documents: Optional[int] = None,
        filters: Optional[Dict[str, str]] = None,
        source: Literal["lectures", "slides", "combined"] = "combined",
        **_: Dict,
    ) -> List[Dict]:
        sources = self._select_sources(source)
        combined_docs: List[Dict] = []
        for label, knowledge in sources:
            docs = self._search_knowledge(knowledge, query, num_documents, filters)
            logger.info("Knowledge retriever fetched %s docs from %s", len(docs), label)
            for doc in docs:
                doc_meta = doc.get("meta_data") or {}
                doc_meta.setdefault("knowledge_source", label)
                doc["meta_data"] = doc_meta
                # preview = (doc.get("content") or "")[:160].replace("\n", " ")
                # logger.debug(
                #     "Doc %s (%s): %s",
                #     doc_meta.get("chunk_id") or doc.get("id") or "unknown",
                #     label,
                #     preview,
                # )
                combined_docs.append(doc)

        combined_docs.sort(key=lambda d: d.get("score") or 0, reverse=True)
        if num_documents:
            combined_docs = combined_docs[:num_documents]
        return combined_docs

    def _select_sources(
        self, source: Literal["lectures", "slides", "combined"]
    ) -> Sequence[Tuple[str, Knowledge]]:
        if source == "lectures":
            return [("lectures", self.lecture_knowledge)]
        if source == "slides":
            return [("slides", self.slide_knowledge)]
        return [
            ("lectures", self.lecture_knowledge),
            ("slides", self.slide_knowledge),
        ]

    def _search_knowledge(
        self,
        knowledge: Knowledge,
        query: str,
        num_documents: Optional[int],
        filters: Optional[Dict[str, str]],
    ) -> List[Dict]:
        documents: List[Document] = knowledge.search(query=query, max_results=num_documents, filters=filters)
        return [doc.to_dict() for doc in documents]

    def _normalize_content(self, content: Optional[object]) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(str(part) for part in content if part is not None)
        return str(content)

    def _normalize_references(self, references: Optional[List]) -> Optional[List[Dict]]:
        if not references:
            return None
        normalized: List[Dict] = []
        for ref in references:
            ref_dict = {}
            if hasattr(ref, "metadata") and ref.metadata:
                ref_dict["metadata"] = ref.metadata
            if hasattr(ref, "source") and ref.source:
                ref_dict["source"] = ref.source
            if ref_dict:
                normalized.append(ref_dict)
        return normalized or None

    def _ensure_openai_key(self) -> None:
        load_dotenv(dotenv_path=".env.local", override=False)
        load_dotenv(override=False)
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY missing. Populate .env.local (or export it) before using the chat agent."
            )
