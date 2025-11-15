# Repository Guidelines

## Docs
- We keep all important docs in .agent folder and keep them updated. This is the structure:

.agent
- Tasks: PRD & implementation plan for each feature
- System: Document the current state of the system (project structure, tech stack, integration points, database schema, and core functionalities such as agent architecture, LLM layer, etc.)
- SOP: Best practices of execute certain tasks (e.g. how to add a schema migration, how to add a new page route, etc.)
- README.md: an index of all the documentations we have so people know what & where to look for things

## Project Structure & Module Organization
- `app/main.py` hosts FastAPI routes; `app/downloader.py`, `app/storage.py`, and `app/models.py` contain business logic and schemas. Add new features under `app/` instead of expanding route handlers directly.
- Downloaded assets live in `storage/videos/` with metadata in `data/videos.json`. Treat both as ephemeral runtime state and keep fixtures or contracts inside `data/` subfolders.

## Build and Development Commands
- `python -m venv .venv && source .venv/bin/activate` — create a clean env before dependency installs.
- `pip install -r requirements.txt` or `uv pip install -r requirements.txt` — install FastAPI plus PanoptoDownloader; follow the yarl/multidict guidance embedded in the file when Python 3.11 builds fail.
- `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` — local dev server with auto-reload; use `python -m app.main` for parity with production.

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation, snake_case functions, and PascalCase Pydantic models. Keep type hints and docstrings describing side effects (`download_video` already demonstrates the pattern).
- Route handlers should remain thin: place IO, ffmpeg, or Panopto calls inside helper classes, and keep configuration (storage paths, job IDs) near the top of each module for clarity.
- JSON or metadata edits should remain deterministic; prefer small helper methods over inline dict mutations to keep `LocalStorage` readable.
