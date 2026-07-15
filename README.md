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
- Semantic stages for classification, entity / alias resolution, and OKF building

## Pipeline

```text
Upload file
→ metadata + sha256 fingerprint
→ parse into parsed_json
→ classify confidentiality
→ resolve entity / alias candidates
→ human review entity / alias decisions
→ build OKF candidate
→ validate OKF schema
→ human approve OKF
→ create searchable chunks
→ search approved OKF
```

## Quick start

```bash
cp backend/.env.example backend/.env
docker compose up -d db
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
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

The backend has deterministic fallbacks, so it can run without an LLM key. Add `OPENAI_API_KEY` later to replace heuristic stages with real LLM calls.
