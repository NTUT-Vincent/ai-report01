from __future__ import annotations

import json
import re
from typing import Any, Literal

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import (
    app,
    approved_mapping,
    db,
    document,
    existing_entities,
    latest_artifact,
    parse_file,
    save_artifact,
    set_status,
    to_json,
    validate_okf_obj,
)


class AgentConnection(BaseModel):
    base_url: str = Field(description="OpenAI-compatible base URL, for example http://localhost:8000/v1")
    model: str = Field(min_length=1)
    api_key: SecretStr = Field(description="Bearer token sent only to the model API; never persisted")
    timeout_seconds: float = Field(default=120, ge=1, le=600)
    temperature: float = Field(default=0.0, ge=0, le=2)
    use_response_format: bool = False


class ProcessAgentRequest(BaseModel):
    agent: AgentConnection


class BuildOKFAgentRequest(BaseModel):
    agent: AgentConnection


class SensitiveSpan(BaseModel):
    text: str
    type: str
    suggested_mask: str | None = None


class ClassificationResult(BaseModel):
    document_id: str
    confidentiality: Literal["public", "internal", "confidential", "restricted"]
    masking_required: bool
    sensitive_spans: list[SensitiveSpan] = []
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class EntityResolutionItem(BaseModel):
    mention: str = Field(min_length=1)
    decision: Literal[
        "existing_entity",
        "alias_candidate",
        "new_entity_candidate",
        "ambiguous",
        "ignored",
    ]
    suggested_entity_id: str | None = None
    suggested_canonical_name: str | None = None
    entity_type: str | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)
    requires_review: bool


class EntityResolutionResult(BaseModel):
    document_id: str
    entities: list[EntityResolutionItem]


def _remove_route(path: str, method: str) -> None:
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method.upper() in getattr(route, "methods", set())
        )
    ]


_remove_route("/documents/{doc_id}/process", "POST")
_remove_route("/documents/{doc_id}/build-okf", "POST")


def _chat_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _extract_json(content: str) -> dict[str, Any]:
    value = content.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
        value = re.sub(r"\s*```$", "", value)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model response does not contain a JSON object")
        parsed = json.loads(value[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model response must be a JSON object")
    return parsed


def call_agent(
    config: AgentConnection,
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            },
        ],
        "temperature": config.temperature,
    }
    if config.use_response_format:
        request_payload["response_format"] = {"type": "json_object"}

    headers = {
        "Authorization": f"Bearer {config.api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=config.timeout_seconds) as client:
            response = client.post(_chat_url(config.base_url), headers=headers, json=request_payload)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:1000]
        raise RuntimeError(f"model API returned {exc.response.status_code}: {body}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"model API request failed: {exc}") from exc

    payload = response.json()
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("OpenAI-compatible response is missing choices[0].message.content") from exc
    if isinstance(content, list):
        content = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return _extract_json(str(content))


def call_validated_agent(
    config: AgentConnection,
    *,
    system_prompt: str,
    user_payload: dict[str, Any],
    schema: type[BaseModel],
) -> BaseModel:
    first = call_agent(config, system_prompt=system_prompt, user_payload=user_payload)
    try:
        return schema.model_validate(first)
    except ValidationError as first_error:
        repair_prompt = (
            system_prompt
            + "\nYour previous response failed schema validation. Return only corrected JSON. "
            + "Do not add markdown or explanations."
        )
        repaired = call_agent(
            config,
            system_prompt=repair_prompt,
            user_payload={
                **user_payload,
                "invalid_output": first,
                "validation_errors": first_error.errors(include_url=False),
            },
        )
        return schema.model_validate(repaired)


CLASSIFICATION_PROMPT = """
You are the Classification Agent in an enterprise OKF ingestion pipeline.
Classify the document as public, internal, confidential, or restricted.
Identify sensitive spans that may require masking.
Return ONLY a JSON object with exactly these fields:
document_id, confidentiality, masking_required, sensitive_spans, reason, confidence.
Each sensitive_spans item must contain text, type, and optional suggested_mask.
Use the source default as context, but override it when document content warrants a stricter level.
Never invent sensitive content that is not present in the supplied document.
""".strip()


ENTITY_PROMPT = """
You are the Entity and Alias Resolution Agent in an OKF ingestion pipeline.
Extract only meaningful domain entities from the document and compare them against existing_entities.
For every entity mention, choose exactly one decision:
- existing_entity: exact or clearly confirmed existing canonical name/alias
- alias_candidate: likely a new alias of an existing entity
- new_entity_candidate: important new entity not represented in existing_entities
- ambiguous: uncertain match or meaning
- ignored: not useful as governed knowledge
Return ONLY JSON with fields document_id and entities.
Each entities item must contain mention, decision, suggested_entity_id, suggested_canonical_name,
entity_type, confidence, reason, requires_review.
Never claim an entity exists unless its ID is present in existing_entities.
Only existing_entity with a strong exact match may set requires_review=false.
Alias, new, and ambiguous decisions must set requires_review=true.
""".strip()


OKF_PROMPT = """
You are the OKF Builder Agent.
Convert the parsed document into one canonical OKF JSON object.
Return ONLY JSON. Required top-level fields:
okf_id, schema_version, title, source, confidentiality, summary,
concepts, entities, procedures, relations, evidence, review_status.
Rules:
- review_status must be pending.
- source.document_id and source.source_id must match the supplied metadata.
- preserve the supplied confidentiality exactly.
- use only approved_entity_mapping for governed entities; do not create formal entity IDs.
- every important concept, procedure, and relation must cite one or more evidence_refs.
- every evidence_ref must match an evidence.evidence_id in the same output.
- evidence text must be grounded in parsed_json.
- do not state uncertain information as fact.
""".strip()


def _classification_agent(
    config: AgentConnection,
    *,
    doc_id: str,
    doc: dict[str, Any],
    parsed: dict[str, Any],
) -> dict[str, Any]:
    result = call_validated_agent(
        config,
        system_prompt=CLASSIFICATION_PROMPT,
        user_payload={
            "document_id": doc_id,
            "source_metadata": {
                "source_id": doc["source_id"],
                "file_name": doc["file_name"],
                "file_type": doc["file_type"],
            },
            "parsed_json": parsed,
        },
        schema=ClassificationResult,
    )
    return result.model_dump(mode="json")


def _entity_agent(
    config: AgentConnection,
    *,
    doc_id: str,
    parsed: dict[str, Any],
    entities: list[dict[str, Any]],
) -> dict[str, Any]:
    result = call_validated_agent(
        config,
        system_prompt=ENTITY_PROMPT,
        user_payload={
            "document_id": doc_id,
            "parsed_json": parsed,
            "existing_entities": entities,
        },
        schema=EntityResolutionResult,
    )
    return result.model_dump(mode="json")


def _okf_agent(
    config: AgentConnection,
    *,
    doc_id: str,
    doc: dict[str, Any],
    parsed: dict[str, Any],
    classification: dict[str, Any],
    mapping: list[dict[str, Any]],
) -> dict[str, Any]:
    output = call_agent(
        config,
        system_prompt=OKF_PROMPT,
        user_payload={
            "document_metadata": {
                "document_id": doc_id,
                "source_id": doc["source_id"],
                "file_name": doc["file_name"],
            },
            "parsed_json": parsed,
            "classification_result": classification,
            "approved_entity_mapping": mapping,
            "schema_version": "v1",
        },
    )
    output["source"] = {
        **output.get("source", {}),
        "document_id": doc_id,
        "source_id": doc["source_id"],
        "file_name": doc["file_name"],
    }
    output["confidentiality"] = classification["confidentiality"]
    output["review_status"] = "pending"
    return output


@app.post("/documents/{doc_id}/process")
def process_with_agents(
    doc_id: str,
    req: ProcessAgentRequest,
    s: Session = Depends(db),
) -> dict[str, Any]:
    doc = document(doc_id, s)
    if doc["status"] == "DUPLICATE":
        raise HTTPException(400, "duplicate document cannot be processed")
    try:
        set_status(s, doc_id, "PARSING")
        parsed = parse_file(doc)
        save_artifact(s, doc_id, "parsed_json", parsed)
        set_status(s, doc_id, "PARSED")

        set_status(s, doc_id, "CLASSIFYING")
        classification = _classification_agent(
            req.agent, doc_id=doc_id, doc=doc, parsed=parsed
        )
        save_artifact(s, doc_id, "classification_result", classification)
        set_status(s, doc_id, "CLASSIFIED")

        set_status(s, doc_id, "ENTITY_RESOLVING")
        resolved = _entity_agent(
            req.agent,
            doc_id=doc_id,
            parsed=parsed,
            entities=existing_entities(s),
        )
        save_artifact(s, doc_id, "entity_resolution_result", resolved)
        s.execute(
            text(
                "DELETE FROM entity_resolution_results WHERE document_id=:doc "
                "AND review_status IN ('pending','auto_bound')"
            ),
            {"doc": doc_id},
        )
        for item in resolved["entities"]:
            auto_bound = (
                item["decision"] == "existing_entity"
                and item["confidence"] >= 0.95
                and item.get("suggested_entity_id")
            )
            review_status = "auto_bound" if auto_bound else "pending"
            requires_review = not auto_bound
            s.execute(
                text(
                    """
                    INSERT INTO entity_resolution_results(
                      result_id, document_id, mention, decision, suggested_entity_id,
                      suggested_canonical_name, entity_type, confidence, reason,
                      requires_review, review_status
                    ) VALUES (
                      gen_random_uuid(), :doc, :mention, :decision, :entity_id,
                      :canonical_name, :entity_type, :confidence, :reason,
                      :requires_review, :review_status
                    )
                    """
                ),
                {
                    "doc": doc_id,
                    "mention": item["mention"],
                    "decision": item["decision"],
                    "entity_id": item.get("suggested_entity_id"),
                    "canonical_name": item.get("suggested_canonical_name"),
                    "entity_type": item.get("entity_type"),
                    "confidence": item["confidence"],
                    "reason": item["reason"],
                    "requires_review": requires_review,
                    "review_status": review_status,
                },
            )
        s.commit()
        pending = s.execute(
            text(
                "SELECT COUNT(*) FROM entity_resolution_results "
                "WHERE document_id=:doc AND review_status='pending'"
            ),
            {"doc": doc_id},
        ).scalar_one()
        final_status = "ENTITY_REVIEW_PENDING" if pending else "ENTITY_REVIEWED"
        set_status(s, doc_id, final_status)
        return {"document_id": doc_id, "status": final_status}
    except (ValidationError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        save_artifact(
            s,
            doc_id,
            "raw_agent_output",
            {"stage": "process", "error": str(exc), "model": req.agent.model},
        )
        set_status(s, doc_id, "AGENT_FAILED", str(exc))
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        set_status(s, doc_id, "FAILED", str(exc))
        raise


@app.post("/documents/{doc_id}/build-okf")
def build_okf_with_agent(
    doc_id: str,
    req: BuildOKFAgentRequest,
    s: Session = Depends(db),
) -> dict[str, Any]:
    pending = s.execute(
        text(
            "SELECT COUNT(*) FROM entity_resolution_results "
            "WHERE document_id=:doc AND review_status='pending'"
        ),
        {"doc": doc_id},
    ).scalar_one()
    if pending:
        raise HTTPException(400, "entity review incomplete")
    doc = document(doc_id, s)
    parsed = latest_artifact(s, doc_id, "parsed_json")
    classification = latest_artifact(s, doc_id, "classification_result")
    try:
        set_status(s, doc_id, "BUILDING_OKF")
        okf = _okf_agent(
            req.agent,
            doc_id=doc_id,
            doc=doc,
            parsed=parsed,
            classification=classification,
            mapping=approved_mapping(s, doc_id),
        )
        errors = validate_okf_obj(okf, doc_id)
        if errors:
            repair_prompt = OKF_PROMPT + "\nFix all supplied validation errors and return the entire corrected OKF JSON."
            okf = call_agent(
                req.agent,
                system_prompt=repair_prompt,
                user_payload={
                    "invalid_okf": okf,
                    "validation_errors": errors,
                    "document_metadata": {
                        "document_id": doc_id,
                        "source_id": doc["source_id"],
                        "file_name": doc["file_name"],
                    },
                    "parsed_json": parsed,
                    "classification_result": classification,
                    "approved_entity_mapping": approved_mapping(s, doc_id),
                },
            )
            okf["source"] = {
                **okf.get("source", {}),
                "document_id": doc_id,
                "source_id": doc["source_id"],
                "file_name": doc["file_name"],
            }
            okf["confidentiality"] = classification["confidentiality"]
            okf["review_status"] = "pending"
            errors = validate_okf_obj(okf, doc_id)

        save_artifact(s, doc_id, "okf_candidate", okf)
        save_artifact(
            s,
            doc_id,
            "schema_validation_result",
            {"valid": not errors, "errors": errors},
        )
        status = "OKF_REVIEW_PENDING" if not errors else "SCHEMA_INVALID"
        set_status(s, doc_id, status)
        return {
            "document_id": doc_id,
            "status": status,
            "okf_json": okf,
            "errors": errors,
        }
    except (ValidationError, ValueError, RuntimeError, httpx.HTTPError) as exc:
        save_artifact(
            s,
            doc_id,
            "raw_agent_output",
            {"stage": "build_okf", "error": str(exc), "model": req.agent.model},
        )
        set_status(s, doc_id, "OKF_BUILD_FAILED", str(exc))
        raise HTTPException(502, str(exc)) from exc
