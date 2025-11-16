# CopilotKit Dev Bridge

This lightweight Express server forwards `POST /api/copilotkit` calls from CopilotKit to the AG-UI endpoint exposed by `agent/dev_agui.py`.

## Prerequisites

Install the runtime dependencies inside this folder (or copy the script into your frontend repo):

```bash
npm install
```

## Running locally

```bash
# 1. Start the AG-UI backend bridge
python -m agent.dev_agui  # from repo root, serves http://localhost:8001/agui (override via AGUI_PORT)

# 2. Start the CopilotKit dev server (port defaults to 3000)
cd dev/copilotkit-server
AGNO_AGENT_URL=http://localhost:8001/agui npm run dev
```

Environment variables:

- `AGNO_AGENT_URL` – AG-UI endpoint (defaults to `http://localhost:8001/agui`).
- `COPILOTKIT_PORT` – Port for this server (defaults to `3000`).

With both services running, the Vite app can call `http://localhost:3000/api/copilotkit` and CopilotKit will stream responses from the StudyBuddy agent.
