# OKF Knowledge Factory MVP

Local-first MVP for converting raw documents into reviewed OKF knowledge with real OpenAI-compatible agents.

This branch intentionally keeps infrastructure simple:

- No MinIO
- No Dify
- No Celery
- Local file storage
- FastAPI backend
- PostgreSQL + JSONB + pgvector-ready schema
- React + Ant Design frontend
- Playwright browser E2E tests

## Pipeline

```text
Upload file
→ metadata + SHA-256 fingerprint
→ parse into parsed_json
→ Classification Agent
→ Entity / Alias Resolution Agent
→ human entity / alias review when required
→ OKF Builder Agent
→ deterministic schema validation
→ human OKF approval
→ searchable chunks
→ approved OKF search
```

## OpenAI-compatible model payload

The frontend sends the connection configuration only with process and build requests:

```json
{
  "agent": {
    "base_url": "http://localhost:8000/v1",
    "model": "qwen-local",
    "api_key": "local-key",
    "temperature": 0,
    "timeout_seconds": 120,
    "use_response_format": false
  }
}
```

The backend calls:

```text
POST {base_url}/chat/completions
Authorization: Bearer {api_key}
```

The API key is not written to PostgreSQL or pipeline artifacts.

## Quick start

Database:

```bash
docker compose up -d db
```

Backend:

```bash
cd backend
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app_agent:app --reload
```

Initialize tables and seed governed entities:

```text
POST http://localhost:8000/db/init
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open:

- Backend API: http://localhost:8000/docs
- Frontend: http://localhost:5173

## Tests

Backend integration tests:

```bash
cd backend
PYTHONPATH=. pytest -q
```

Frontend production build:

```bash
cd frontend
npm run build
```

Playwright browser tests require PostgreSQL, the backend, frontend, and an OpenAI-compatible endpoint. CI starts the included `backend/mock_llm.py` server automatically and executes:

```bash
cd frontend
npm run test:e2e
```

The browser suite verifies:

- upload through the React UI
- real HTTP calls through the OpenAI-compatible agent client
- classification and entity-resolution stages
- OKF build, validation, approval, chunking, and search
- unreachable model endpoint error handling
- API key is not rendered in error output

GitHub Actions runs backend tests, frontend build, and Playwright Chromium E2E on every PR update.
