# OKF Knowledge Factory MVP Demo

## 1. Start database

```bash
docker compose up -d db
```

## 2. Start backend

```bash
cd backend
cp .env.example .env
pip install -r requirements.txt
uvicorn app_agent:app --reload
```

Open http://localhost:8000/docs and call:

```text
POST /db/init
```

This creates tables and seeds starter entities / aliases:

- Intelligent Manufacturing Center: CIM, IMC, 智慧製造中心
- equipment: 機台, tool, equipment
- SOP: 標準作業程序, Standard Operating Procedure, SOP
- alarm code: alarm, 警報碼, alarm code

## 3. Start your local OpenAI-compatible model API

The API must support:

```text
POST {base_url}/chat/completions
```

A standard response must include:

```json
{
  "choices": [
    {
      "message": {
        "content": "{\"valid\": \"JSON produced by the agent\"}"
      }
    }
  ]
}
```

Prepare these three values:

- Base URL, for example `http://localhost:8000/v1`
- Model name, for example `qwen-local`
- API key

## 4. Start frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## 5. Demo flow

1. Enter the local model Base URL, model name, and API key.
2. Upload `samples/sample_alias_case.txt`.
3. Click **Process with Agents**.
4. The backend calls the real Classification Agent and Entity / Alias Resolution Agent and creates:
   - `parsed_json`
   - `classification_result`
   - `entity_resolution_result`
5. Review pending entity decisions through the entity review API.
6. Click **Build OKF with Agent** after entity review is complete.
7. Inspect `okf_candidate` and `schema_validation_result`.
8. Click **Approve latest OKF**.
9. Search `機台` or `SOP` in the Search tab.

## 6. Agent payload

Both process and OKF build accept:

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

The API key is used for the outbound request only. It is not stored in PostgreSQL or artifacts.

## 7. Notes

This branch is a compact MVP scaffold, not the final enterprise architecture. It intentionally uses:

- local file storage instead of MinIO
- direct FastAPI processing instead of Celery
- PostgreSQL full-text search instead of Dify / OpenSearch
- real OpenAI-compatible agents with structured JSON validation
