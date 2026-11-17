"""FastAPI integration tests using isolated SQLite databases."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from storage import PPEStore


@pytest.fixture
def setup_api(tmp_path, monkeypatch):
    # Redirect database initialization before importing main.
    monkeypatch.setenv(
        "PPE_DB_PATH", str(tmp_path / "startup.sqlite3")
    )
    monkeypatch.setenv(
        "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
    )
    monkeypatch.setenv("OLLAMA_MODELS", "test-model")

    import main

    store = PPEStore(tmp_path / "api.sqlite3")
    monkeypatch.setattr(main, "STORE", store)

    with TestClient(main.app) as client:
        yield client, store


def sample_result():
    return {
        "model": "test-model",
        "overall_status": "violation",
        "helmet_violation": "yes",
        "vest_violation": "no",
        "boots_violation": "unclear",
        "worker_count": 1,
        "processing_seconds": 0.5,
        "location": "Test site",
        "camera": "TEST",
        "evidence_url": "/api/evidence/test.jpg",
    }


def create_incident(store):
    record = store.save_analysis(
        sample_result(),
        video_session_id="api-test-video",
        video_name="sample.mp4",
        video_seconds=0,
    )
    return record["incident_id"]


def test_health_endpoint(setup_api):
    client, _ = setup_api
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_dashboard_state_endpoint(setup_api):
    client, store = setup_api
    create_incident(store)

    response = client.get("/api/state")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert len(response.json()["notifications"]) == 1


def test_incident_frame_history_endpoint(setup_api):
    client, store = setup_api
    incident_id = create_incident(store)

    store.save_analysis(
        sample_result(),
        video_session_id="api-test-video",
        video_name="sample.mp4",
        video_seconds=2,
    )

    response = client.get(
        f"/api/incidents/{incident_id}/analyses"
    )

    assert response.status_code == 200
    assert len(response.json()["analyses"]) == 2


def test_resolve_endpoint(setup_api):
    client, store = setup_api
    incident_id = create_incident(store)

    response = client.patch(
        f"/api/incidents/{incident_id}",
        json={"status": "Resolved"},
    )

    assert response.status_code == 200

    state = client.get("/api/state").json()

    assert state["items"][0]["status"] == "Resolved"
    assert len(state["notifications"]) == 0


def test_archive_endpoint(setup_api):
    client, store = setup_api
    incident_id = create_incident(store)

    response = client.post(
        f"/api/incidents/{incident_id}/archive"
    )

    assert response.status_code == 200

    state = client.get("/api/state").json()

    assert state["items"][0]["status"] == "Archived"
    assert len(state["notifications"]) == 0

    # An already archived incident cannot be archived again.
    assert client.post(
        f"/api/incidents/{incident_id}/archive"
    ).status_code == 404


def test_delete_notification_endpoint(setup_api):
    client, store = setup_api
    incident_id = create_incident(store)

    response = client.delete(
        f"/api/incidents/{incident_id}/notification"
    )

    assert response.status_code == 200

    state = client.get("/api/state").json()

    # Notification removed, but incident remains.
    assert len(state["notifications"]) == 0
    assert len(state["items"]) == 1
    assert state["items"][0]["status"] == "Open"
