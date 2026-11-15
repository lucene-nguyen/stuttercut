# StutterCut

StutterCut is a **local web app** that finds stutters, filler words, long pauses and retakes in
short Vietnamese videos (≤ 3 minutes), lets you review the suggested cuts, then renders a clean
video or exports FCP XML.

Everything runs on your machine, including the LLM that reviews cuts (Ollama, by default).
If you opt in to the Anthropic API instead, only transcript text is sent; audio and video
never leave the machine.

> Status: repository foundations only. The API serves `GET /api/health`; the pipeline is not built yet.

## Requirements

- Python 3.11+
- Node.js 22+
- FFmpeg (needed later by the pipeline)

## Setup

```bash
python -m venv .venv
. .venv/bin/activate                 # Windows: .venv\Scripts\Activate.ps1
pip install -e "backend[dev]"
pre-commit install
cp .env.example .env                 # LLM_API_KEY only for the opt-in Anthropic provider
cd frontend && npm install
```

## Run

```bash
uvicorn stuttercut.api.main:app --reload     # API on http://127.0.0.1:8000
cd frontend && npm run dev                   # UI on http://127.0.0.1:5173 (proxies /api)
```

## Quality checks

```bash
ruff check . && ruff format --check .
mypy backend
pytest
cd frontend && npm run lint && npm test
```

## Documentation

- [CLAUDE.md](CLAUDE.md) — architecture summary, layout, conventions and rules
- [docs/README.md](docs/README.md) — index of design documents, diagrams and Jira tasks
- [docs/adr/](docs/adr/) — architecture decision records
