"""Dev-only AG-UI wrapper for the StudyBuddy chat agent (Agno v2-style)."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

from app.chat_agent import StudyBuddyChatAgent
from app.chroma_ingestion import ChromaIngestionConfig


def _load_env() -> None:
    """Load .env files so OpenAI + Chroma settings are present."""
    load_dotenv(".env.local", override=False)
    load_dotenv(override=False)


def _build_agent_os() -> AgentOS:
    """Instantiate StudyBuddyChatAgent and expose it through AGUI."""
    config = ChromaIngestionConfig(
        chroma_path=os.getenv("CHROMA_PATH", "tmp/chromadb"),
        lecture_collection=os.getenv("CHROMA_LECTURE_COLLECTION", "course_lectures"),
        slide_collection=os.getenv("CHROMA_SLIDE_COLLECTION", "course_slides"),
    )
    studybuddy_agent = StudyBuddyChatAgent(config=config)
    agui_interface = AGUI(agent=studybuddy_agent.agent)
    return AgentOS(agents=[studybuddy_agent.agent], interfaces=[agui_interface])


_load_env()
agent_os = _build_agent_os()
app = agent_os.get_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("AGUI_PORT", "8001")))
