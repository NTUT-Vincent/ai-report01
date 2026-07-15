from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app_agent


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app_agent.app)


def test_json_extraction_variants() -> None:
    assert app_agent._extract_json('{"ok": true}') == {"ok": True}
    assert app_agent._extract_json('```json\n{"ok": true}\n```') == {"ok": True}
    assert app_agent._extract_json('prefix {"ok": true} suffix') == {"ok": True}
    with pytest.raises(ValueError):
        app_agent._extract_json('not json')


def test_chat_url_normalization() -> None:
    assert app_agent._chat_url('http://localhost:8000/v1') == 'http://localhost:8000/v1/chat/completions'
    assert app_agent._chat_url('http://localhost:8000/v1/') == 'http://localhost:8000/v1/chat/completions'
    assert app_agent._chat_url('http://localhost:8000/v1/chat/completions') == 'http://localhost:8000/v1/chat/completions'


def test_validated_agent_repairs_invalid_output(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter([
        {"document_id": "d", "confidentiality": "wrong"},
        {
            "document_id": "d",
            "confidentiality": "internal",
            "masking_required": False,
            "sensitive_spans": [],
            "reason": "valid after repair",
            "confidence": 0.9,
        },
    ])

    monkeypatch.setattr(app_agent, "call_agent", lambda *args, **kwargs: next(responses))
    config = app_agent.AgentConnection(base_url="http://model/v1", model="test", api_key="secret")
    result = app_agent.call_validated_agent(
        config,
        system_prompt="test",
        user_payload={"document_id": "d"},
        schema=app_agent.ClassificationResult,
    )
    assert result.confidentiality == "internal"


def test_full_pipeline_with_real_agent_boundaries(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    init = client.post('/db/init')
    assert init.status_code == 200, init.text

    unique = str(uuid.uuid4())
    content = f"CIM uses equipment and SOP. ABC Flow {unique} is a new internal process."
    upload = client.post('/documents/upload', files={'file': (f'{unique}.txt', content.encode('utf-8'), 'text/plain')})
    assert upload.status_code == 200, upload.text
    document_id = upload.json()['document_id']
    assert upload.json()['status'] == 'RECEIVED'

    entities = client.get('/entities').json()
    by_alias = {}
    for entity in entities:
        for alias in entity.get('aliases') or []:
            by_alias[str(alias).lower()] = entity
    cim = by_alias['cim']

    agent_outputs = iter([
        {
            'document_id': document_id,
            'confidentiality': 'internal',
            'masking_required': False,
            'sensitive_spans': [],
            'reason': 'Internal process document.',
            'confidence': 0.96,
        },
        {
            'document_id': document_id,
            'entities': [
                {
                    'mention': 'CIM',
                    'decision': 'existing_entity',
                    'suggested_entity_id': str(cim['entity_id']),
                    'suggested_canonical_name': cim['canonical_name'],
                    'entity_type': cim['entity_type'],
                    'confidence': 0.99,
                    'reason': 'Exact alias match.',
                    'requires_review': False,
                },
                {
                    'mention': f'ABC Flow {unique}',
                    'decision': 'new_entity_candidate',
                    'suggested_entity_id': None,
                    'suggested_canonical_name': f'ABC Flow {unique}',
                    'entity_type': 'process',
                    'confidence': 0.88,
                    'reason': 'No governed entity exists.',
                    'requires_review': True,
                },
            ],
        },
    ])
    monkeypatch.setattr(app_agent, 'call_agent', lambda *args, **kwargs: next(agent_outputs))

    request = {
        'agent': {
            'base_url': 'http://local-model/v1',
            'model': 'test-model',
            'api_key': 'must-not-persist',
            'temperature': 0,
            'timeout_seconds': 30,
            'use_response_format': False,
        }
    }
    process = client.post(f'/documents/{document_id}/process', json=request)
    assert process.status_code == 200, process.text
    assert process.json()['status'] == 'ENTITY_REVIEW_PENDING'

    artifacts = client.get(f'/documents/{document_id}/artifacts').json()['artifacts']
    serialized = str(artifacts)
    assert 'must-not-persist' not in serialized

    results = client.get(f'/documents/{document_id}/entity-results').json()
    pending = [item for item in results if item['review_status'] == 'pending']
    auto_bound = [item for item in results if item['review_status'] == 'auto_bound']
    assert len(pending) == 1
    assert len(auto_bound) == 1

    review = client.post(
        f'/documents/{document_id}/entity-review',
        json={
            'reviewed_by': 'pytest',
            'actions': [
                {
                    'result_id': str(pending[0]['result_id']),
                    'action': 'create_new_entity',
                    'canonical_name': pending[0]['suggested_canonical_name'],
                    'entity_type': 'process',
                }
            ],
        },
    )
    assert review.status_code == 200, review.text
    assert review.json()['status'] == 'ENTITY_REVIEWED'

    okf_id = str(uuid.uuid4())
    valid_okf = {
        'okf_id': okf_id,
        'schema_version': 'v1',
        'title': f'Test SOP {unique}',
        'source': {'document_id': document_id, 'source_id': 'local_sop', 'file_name': f'{unique}.txt'},
        'confidentiality': 'internal',
        'summary': 'A governed internal process.',
        'concepts': [{'concept_id': 'c1', 'name': 'Internal process', 'definition': 'A test process.', 'evidence_refs': ['e1']}],
        'entities': [],
        'procedures': [{'procedure_id': 'p1', 'name': 'Test procedure', 'steps': [{'order': 1, 'description': 'Review the process.'}], 'evidence_refs': ['e1']}],
        'relations': [{'relation_id': 'r1', 'subject': 'CIM', 'predicate': 'uses', 'object': 'ABC Flow', 'evidence_refs': ['e1']}],
        'evidence': [{'evidence_id': 'e1', 'section': 'document', 'text': content}],
        'review_status': 'pending',
    }
    monkeypatch.setattr(app_agent, 'call_agent', lambda *args, **kwargs: dict(valid_okf))
    build = client.post(f'/documents/{document_id}/build-okf', json=request)
    assert build.status_code == 200, build.text
    assert build.json()['status'] == 'OKF_REVIEW_PENDING'

    approve = client.post(
        f'/documents/{document_id}/approve-okf',
        json={'okf_json': build.json()['okf_json'], 'approved_by': 'pytest'},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()['status'] == 'READY'

    search = client.get('/search', params={'q': 'governed internal process'})
    assert search.status_code == 200, search.text
    assert any(item['okf_id'] == okf_id for item in search.json()['results'])


def test_invalid_model_endpoint_is_safely_reported(client: TestClient) -> None:
    unique = str(uuid.uuid4())
    upload = client.post('/documents/upload', files={'file': (f'{unique}.txt', b'hello', 'text/plain')})
    assert upload.status_code == 200
    document_id = upload.json()['document_id']
    response = client.post(
        f'/documents/{document_id}/process',
        json={
            'agent': {
                'base_url': 'http://127.0.0.1:1/v1',
                'model': 'missing',
                'api_key': 'not-persisted',
                'timeout_seconds': 1,
            }
        },
    )
    assert response.status_code == 502
    document = client.get(f'/documents/{document_id}').json()
    assert document['status'] == 'AGENT_FAILED'
    artifacts = client.get(f'/documents/{document_id}/artifacts').json()['artifacts']
    assert 'not-persisted' not in str(artifacts)
