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
uvicorn app:app --reload
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

## 3. Start frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## 4. Demo flow

1. Upload `samples/sample_alias_case.txt`.
2. Click **Process**.
3. The backend creates:
   - `parsed_json`
   - `classification_result`
   - `entity_resolution_result`
4. If any entity is pending, call entity review API from Swagger UI or leave it for later UI expansion.
5. Click **Build OKF**.
6. Click **Approve latest OKF**.
7. Search `機台` or `SOP` in the Search tab.

## 5. Notes

This branch is a compact MVP scaffold, not the final enterprise architecture.
It intentionally uses:

- local file storage instead of MinIO
- direct FastAPI processing instead of Celery
- PostgreSQL full-text search instead of Dify / OpenSearch
- deterministic placeholder agents that can later be swapped with LLM structured-output agents
