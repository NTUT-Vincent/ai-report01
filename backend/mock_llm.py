from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import FastAPI, Request

app = FastAPI(title="Mock OpenAI-compatible LLM")


def _response(content: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(content, ensure_ascii=False),
                },
                "finish_reason": "stop",
            }
        ],
    }


def _user_payload(body: dict[str, Any]) -> dict[str, Any]:
    messages = body.get("messages", [])
    user = next((m for m in reversed(messages) if m.get("role") == "user"), {})
    return json.loads(user.get("content", "{}"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat(request: Request) -> dict[str, Any]:
    body = await request.json()
    system_prompt = "\n".join(
        message.get("content", "")
        for message in body.get("messages", [])
        if message.get("role") == "system"
    )
    payload = _user_payload(body)

    if "Classification Agent" in system_prompt:
        document_id = payload["document_id"]
        return _response(
            {
                "document_id": document_id,
                "confidentiality": "internal",
                "masking_required": False,
                "sensitive_spans": [],
                "reason": "Mock model classified the SOP as internal.",
                "confidence": 0.99,
            }
        )

    if "Entity and Alias Resolution Agent" in system_prompt:
        entities = payload.get("existing_entities", [])
        selected = []
        for entity in entities:
            aliases = [str(value).lower() for value in entity.get("aliases", [])]
            canonical = str(entity.get("canonical_name", "")).lower()
            if canonical in {"equipment", "sop"} or "機台" in aliases or "sop" in aliases:
                mention = "機台" if canonical == "equipment" else "SOP"
                selected.append(
                    {
                        "mention": mention,
                        "decision": "existing_entity",
                        "suggested_entity_id": str(entity["entity_id"]),
                        "suggested_canonical_name": entity["canonical_name"],
                        "entity_type": entity["entity_type"],
                        "confidence": 0.99,
                        "reason": "Exact governed entity match from the supplied registry.",
                        "requires_review": False,
                    }
                )
        return _response({"document_id": payload["document_id"], "entities": selected})

    if "OKF Builder Agent" in system_prompt:
        metadata = payload.get("document_metadata", {})
        parsed = payload.get("parsed_json", {})
        classification = payload.get("classification_result", {})
        mapping = payload.get("approved_entity_mapping", [])
        sections = parsed.get("sections", [])
        body_text = "\n".join(section.get("content", "") for section in sections)
        evidence_id = "evidence_001"
        return _response(
            {
                "okf_id": str(uuid.uuid4()),
                "schema_version": "v1",
                "title": parsed.get("title", "Mock OKF"),
                "source": {
                    "document_id": metadata.get("document_id"),
                    "source_id": metadata.get("source_id"),
                    "file_name": metadata.get("file_name"),
                },
                "confidentiality": classification.get("confidentiality", "internal"),
                "summary": "Mock OKF generated from the uploaded SOP document.",
                "concepts": [
                    {
                        "concept_id": "concept_001",
                        "name": "機台異常處理",
                        "definition": "依照 SOP 處理機台異常與 alarm code。",
                        "evidence_refs": [evidence_id],
                    }
                ],
                "entities": [
                    {
                        "entity_id": str(item.get("entity_id")),
                        "name": item.get("canonical_name") or item.get("mention"),
                        "type": item.get("entity_type") or "domain_term",
                        "aliases": [item.get("mention")],
                    }
                    for item in mapping
                    if item.get("entity_id")
                ],
                "procedures": [
                    {
                        "procedure_id": "procedure_001",
                        "name": "異常處理流程",
                        "steps": [
                            {"order": 1, "description": "確認 alarm code"},
                            {"order": 2, "description": "依照 SOP 執行處置"},
                        ],
                        "evidence_refs": [evidence_id],
                    }
                ],
                "relations": [
                    {
                        "relation_id": "relation_001",
                        "subject": "機台異常",
                        "predicate": "requires",
                        "object": "SOP",
                        "evidence_refs": [evidence_id],
                    }
                ],
                "evidence": [
                    {
                        "evidence_id": evidence_id,
                        "section": sections[0].get("heading", "document") if sections else "document",
                        "text": body_text[:1000] or "機台異常時依照 SOP 處理。",
                    }
                ],
                "review_status": "pending",
            }
        )

    return _response({"error": "unrecognized mock prompt"})
