import io
import os
from pathlib import Path
import sys

import httpx
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main


VALID_RESPONSE = '{"worker_count": 2, "workers": [], "helmet_violation": "yes", "vest_violation": "no", "boots_violation": "unclear"}'


def png_bytes():
    image = Image.new('RGB', (32, 32), (200, 220, 200))
    buffer = io.BytesIO()
    image.save(buffer, 'PNG')
    return buffer.getvalue()


def test_parse_and_classify():
    parsed = main.extract_response(f'```json\n{VALID_RESPONSE}\n```')
    assert parsed.helmet_violation == 'yes'
    assert main.overall_status(parsed) == 'violation'
    assert main.overall_status(main.extract_response('{"worker_count":1,"helmet_violation":"no","vest_violation":"no","boots_violation":"no"}')) == 'compliant'
    assert main.overall_status(main.extract_response('{"worker_count":0,"helmet_violation":"unclear","vest_violation":"unclear"}')) == 'no_workers'


def test_empty_invalid_response():
    for content in ('', '{broken}', '{"helmet_violation":"yes"}'):
        try:
            main.extract_response(content)
        except ValueError:
            pass
        else:
            raise AssertionError('An unusable response must fail')


def test_remote_call_and_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'OLLAMA_BASE_URL', 'http://fake-ollama')
    monkeypatch.setattr(main, 'EVIDENCE_DIR', tmp_path)
    def handler(request):
        assert request.url.path == '/api/chat'
        assert request.headers['content-type'] == 'application/json'
        assert request.read().decode().count('images') == 1
        return httpx.Response(200, json={'message': {'content': VALID_RESPONSE}})
    real_client = httpx.Client
    monkeypatch.setattr(main.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    client = TestClient(main.app)
    response = client.post('/api/analyze', data={'model': 'qwen3.8:27b', 'location': 'Warehouse A'}, files={'file': ('test.png', png_bytes(), 'image/png')})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['overall_status'] == 'violation'
    assert data['helmet_violation'] == 'yes'
    assert data['evidence_url'].startswith('/api/evidence/')
    evidence = client.get(data['evidence_url'])
    assert evidence.status_code == 200 and evidence.content[:3] == b'\xff\xd8\xff'
    assert client.get('/api/evidence/../../etc/passwd').status_code == 404


def test_invalid_model_no_network(monkeypatch):
    monkeypatch.setattr(main, 'OLLAMA_BASE_URL', 'http://fake-ollama')
    response = TestClient(main.app).post('/api/analyze', data={'model': 'something-else'}, files={'file': ('test.png', png_bytes(), 'image/png')})
    assert response.status_code == 400


def test_failure_does_not_store_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'OLLAMA_BASE_URL', 'http://fake-ollama')
    monkeypatch.setattr(main, 'EVIDENCE_DIR', tmp_path)
    def handler(request):
        return httpx.Response(200, json={'message': {'content': ''}})
    real_client = httpx.Client
    monkeypatch.setattr(main.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    response = TestClient(main.app).post('/api/analyze', data={'model': 'qwen3.8:27b'}, files={'file': ('test.png', png_bytes(), 'image/png')})
    assert response.status_code == 502
    assert 'empty' in response.json()['detail']
    assert not list(tmp_path.iterdir())


def test_boots_violation_creates_incident_status():
    model = main.extract_response('{"worker_count":2,"helmet_violation":"no","vest_violation":"no","boots_violation":"yes"}')
    assert main.overall_status(model) == 'violation'


def test_unknown_boots_are_not_auto_compliant_or_spam_alarms():
    model = main.extract_response('{"worker_count":2,"helmet_violation":"no","vest_violation":"no","boots_violation":"unclear"}')
    assert main.overall_status(model) == 'boots_unverified'
    assert main.overall_status(model, review_unclear_boots=True) == 'unclear'
    model2 = main.extract_response('{"worker_count":2,"helmet_violation":"no","vest_violation":"no","boots_violation":"no"}')
    assert main.overall_status(model2) == 'compliant'


def test_boots_only_image_via_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'OLLAMA_BASE_URL', 'http://fake-ollama')
    monkeypatch.setattr(main, 'EVIDENCE_DIR', tmp_path)
    answer = '{"worker_count":1,"helmet_violation":"no","vest_violation":"no","boots_violation":"yes"}'
    def handler(request):
        return httpx.Response(200, json={'message': {'content': answer}})
    real_client = httpx.Client
    monkeypatch.setattr(main.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    client = TestClient(main.app)
    response = client.post('/api/analyze', data={'model':'qwen3.8:27b'}, files={'file':('one.png',png_bytes(),'image/png')})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['overall_status'] == 'violation'
    assert body['boots_violation'] == 'yes'
    assert client.get(body['evidence_url']).status_code == 200


def test_ambiguous_boots_review_switch(monkeypatch, tmp_path):
    monkeypatch.setattr(main, 'OLLAMA_BASE_URL', 'http://fake-ollama')
    monkeypatch.setattr(main, 'EVIDENCE_DIR', tmp_path)
    answer = '{"worker_count":1,"helmet_violation":"no","vest_violation":"no","boots_violation":"unclear"}'
    def handler(request):
        return httpx.Response(200, json={'message': {'content': answer}})
    real_client = httpx.Client
    monkeypatch.setattr(main.httpx, 'Client', lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    client = TestClient(main.app)
    file = {'file':('one.png',png_bytes(),'image/png')}
    response = client.post('/api/analyze', data={'model':'qwen3.8:27b'}, files=file)
    assert response.status_code == 200, response.text
    assert response.json()['overall_status'] == 'boots_unverified'
    assert response.json()['evidence_url'] is None
    response = client.post('/api/analyze', data={'model':'qwen3.8:27b','review_unclear_boots':'true'}, files=file)
    assert response.status_code == 200, response.text
    assert response.json()['overall_status'] == 'unclear'
    assert response.json()['evidence_url'] is not None
