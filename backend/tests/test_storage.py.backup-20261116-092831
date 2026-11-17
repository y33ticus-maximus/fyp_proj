"""Run offline: cd backend && python -m pytest -q"""
from pathlib import Path
from types import SimpleNamespace
import io
import json

from fastapi.testclient import TestClient
from PIL import Image
import pytest

import main
from storage import PPEStore


@pytest.fixture
def store(tmp_path):
    return PPEStore(tmp_path / 'ppe.sqlite3', cooldown_seconds=120)


def prediction(status='violation', helmet='yes', vest='no', boots='unclear'):
    return dict(model='openbmb/minicpm-v4.7:1b', overall_status=status,
                helmet_violation=helmet, vest_violation=vest, boots_violation=boots,
                location='Construction site', camera='UPLOAD', worker_count=1,
                processing_seconds=2.5, evidence_url='/api/evidence/abc.jpg',
                analyzed_at='2026-11-06T03:00:00+00:00')


def test_video_duplicate_grouping_and_all_frames_saved(store):
    entries = [store.save_analysis(prediction(), video_session_id='one-run',
                                   video_name='video.mp4', video_seconds=t)
               for t in [0, 5, 10, 135]]
    assert [e['incident_action'] for e in entries] == ['created', 'grouped', 'grouped', 'created']
    assert entries[0]['incident_id'] == entries[1]['incident_id'] == entries[2]['incident_id']
    assert entries[3]['incident_id'] != entries[0]['incident_id']
    state = store.state()
    assert state['statistics']['analyses'] == 4
    assert state['statistics']['incidents'] == 2
    assert [i['detectionCount'] for i in sorted(state['items'], key=lambda x:x['id'])] == [3, 1]
    assert len(state['notifications']) == 2
    assert [x['video_seconds'] for x in store.incident_analyses(entries[0]['incident_id'])] == [0, 5, 10]


def test_compliance_denominator_excludes_undetermined_and_errors(store):
    store.save_analysis(prediction('compliant', 'no', 'no', 'no'))
    store.save_analysis(prediction('violation', 'yes', 'no', 'unclear'))
    store.save_analysis(prediction('boots_unverified', 'no', 'no', 'unclear'))
    store.save_analysis(prediction('unclear', 'unclear', 'no', 'unclear'))
    store.save_analysis(prediction('no_workers', 'unclear', 'unclear', 'unclear'))
    store.save_failure(model='bad', location='Test', camera='UPLOAD',
                       message='unavailable', processing_seconds=0.2)
    stats = store.state()['statistics']
    assert stats['complianceRate'] == 50.0
    assert stats['decisive'] == 2
    assert stats['failed'] == stats['bootsUnverified'] == stats['noWorkers'] == stats['unclear'] == 1
    assert stats['analyses'] == 6
    assert stats['incidents'] == 2


def test_separate_runs_and_resolved_incidents_do_not_merge(store):
    a = store.save_analysis(prediction(), video_session_id='first', video_seconds=0)
    b = store.save_analysis(prediction(), video_session_id='second', video_seconds=5)
    assert a['incident_id'] != b['incident_id']
    store.update_status(a['incident_id'], 'Resolved')
    c = store.save_analysis(prediction(), video_session_id='first', video_seconds=10)
    assert c['incident_action'] == 'created'
    assert c['incident_id'] not in {a['incident_id'], b['incident_id']}


def test_legacy_browser_import_keeps_real_records_only_and_is_idempotent(store):
    browser_items = [
        {'id': 1, 'model': 'qwen3.8:27b', 'issue': 'Missing hard hat',
         'status': 'Resolved', 'source': 'Remote VLM',
         'evidenceUrl': '/api/evidence/abc.jpg', 'createdAt': '2026-11-01T00:00:00+00:00'},
        {},
        {'id': 2, 'issue': 'Missing goggles', 'source': 'Simulation', 'model': 'demo'},
    ]
    old_notifications = [{'incidentId': 1, 'read': True}]
    assert store.import_browser_incidents('browser-one', browser_items, old_notifications) == 1
    assert store.import_browser_incidents('browser-one', browser_items, old_notifications) == 0
    state = store.state()
    assert state['statistics']['incidents'] == 1
    assert state['statistics']['analyses'] == 0  # old analyses were not persisted
    assert state['notifications'][0]['read'] is True
    assert state['items'][0]['status'] == 'Resolved'
    assert state['items'][0]['evidenceUrl'] == '/api/evidence/abc.jpg'


def test_persistence_across_store_instances(tmp_path):
    path = tmp_path / 'store.db'
    first = PPEStore(path)
    first.save_analysis(prediction())
    second = PPEStore(path)
    assert second.state()['statistics']['incidents'] == 1
    incident_id = second.state()['items'][0]['id']
    second.update_status(incident_id, 'Resolved')
    assert PPEStore(path).state()['items'][0]['status'] == 'Resolved'


def test_api_state_and_notification_updates(monkeypatch, store):
    monkeypatch.setattr(main, 'STORE', store)
    item = store.save_analysis(prediction())
    with TestClient(main.app) as client:
        result = client.get('/api/state')
        assert result.status_code == 200
        state = result.json()
        assert state['statistics']['incidents'] == 1
        notification_id = state['notifications'][0]['id']
        assert client.patch('/api/notifications/' + notification_id, json={'read': True}).status_code == 200
        assert client.patch('/api/incidents/' + str(item['incident_id']), json={'status': 'Resolved'}).status_code == 200
        state = client.get('/api/state').json()
        assert state['notifications'][0]['read'] is True
        assert state['items'][0]['status'] == 'Resolved'


def test_api_image_inference_mocked_no_real_ollama(monkeypatch, store):
    monkeypatch.setattr(main, 'STORE', store)
    monkeypatch.setattr(main, 'OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    monkeypatch.setattr(main, 'ALLOWED_MODELS', ['openbmb/minicpm-v4.7:1b'])
    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {'message': {'content': json.dumps({'worker_count':1, 'workers': [],
                         'helmet_violation':'yes','vest_violation':'no','boots_violation':'unclear'})}}
    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, *a, **kw): return FakeResponse()
    orig_httpx = main.httpx
    monkeypatch.setattr(main, 'httpx', SimpleNamespace(Client=FakeClient,
        TimeoutException=orig_httpx.TimeoutException, HTTPStatusError=orig_httpx.HTTPStatusError,
        RequestError=orig_httpx.RequestError, InvalidURL=orig_httpx.InvalidURL))
    memory = io.BytesIO()
    Image.new('RGB', (40,40), 'white').save(memory, format='JPEG')
    with TestClient(main.app) as client:
        for second in (0, 5):
            response = client.post('/api/analyze', files={'file': ('frame.jpg', memory.getvalue(), 'image/jpeg')},
              data={'model':'openbmb/minicpm-v4.7:1b','location':'Test','camera':'CAM',
                    'video_session_id':'test-session','video_name':'sample.mp4',
                    'video_timestamp_seconds':str(second)})
            assert response.status_code == 200, response.text
            assert response.json()['overall_status'] == 'violation'
            assert response.json()['incident_action'] == ('created' if second==0 else 'grouped')
    assert store.state()['statistics']['incidents'] == 1
    assert store.state()['statistics']['analyses'] == 2
