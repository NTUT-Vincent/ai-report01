# OKF Knowledge Factory MVP

Local-first MVP for converting raw documents into reviewed OKF knowledge.

This branch intentionally keeps infrastructure simple:

- No MinIO
- No Dify
- No Celery
- Local file storage
- FastAPI backend
- PostgreSQL + JSONB + pgvector-ready schema
- Basic React UI
- Real OpenAI-compatible agents for classification, entity / alias resolution, and OKF building

## Pipeline

```text
Upload file
→ metadata + sha256 fingerprint
→ parse into parsed_json
→ Classification Agent
→ Entity / Alias Resolution Agent
→ human review entity / alias decisions
→ OKF Builder Agent
→ validate OKF schema
→ human approve OKF
→ create searchable chunks
→ search approved OKF
```

## Local model contract

The backend calls an OpenAI-compatible endpoint:

```text
POST {base_url}/chat/completions
Authorization: Bearer {api_key}
```

The model connection is supplied in each process/build request:

```json
{
  "agent": {
    "base_url": "http://localhost:8000/v1",
    "model": "qwen-local",
    "api_key": "your-local-key",
    "temperature": 0,
    "timeout_seconds": 120,
    "use_response_format": false
  }
}
```

`base_url`, `model`, and `api_key` are included in the request payload. The backend uses the key only for the outbound model call and does not persist it in PostgreSQL or artifacts. Error artifacts record only the model name and error message.

Set `use_response_format=true` only when the local server supports OpenAI's `response_format: {"type":"json_object"}` option.

## Quick start

```bash
cp backend/.env.example backend/.env
docker compose up -d db
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app_agent:app --reload
```

Initialize the database once:

```bash
curl -X POST http://localhost:8000/db/init
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

## API examples

Process a parsed document with real agents:

```bash
curl -X POST http://localhost:8000/documents/DOCUMENT_ID/process \
  -H 'Content-Type: application/json' \
  -d '{
    "agent": {
      "base_url": "http://localhost:8000/v1",
      "model": "qwen-local",
      "api_key": "local-key"
    }
  }'
```

Build OKF after entity review is complete:

```bash
curl -X POST http://localhost:8000/documents/DOCUMENT_ID/build-okf \
  -H 'Content-Type: application/json' \
  -d '{
    "agent": {
      "base_url": "http://localhost:8000/v1",
      "model": "qwen-local",
      "api_key": "local-key"
    }
  }'
```

The original `app.py` remains as an offline deterministic reference. Use `app_agent:app` for the real-agent implementation.
