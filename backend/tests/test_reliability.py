
"""PPE backend reliability tests.

No real Ollama connection or production database is used.
"""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main
from storage import PPEStore


MODEL = "reliability-test-model"


@pytest.fixture
def system(tmp_path, monkeypatch):
    store = PPEStore(tmp_path / "reliability.sqlite3")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    monkeypatch.setattr(main, "STORE", store)
    monkeypatch.setattr(
        main, "OLLAMA_BASE_URL", "http://mock-ollama.invalid"
    )
    monkeypatch.setattr(main, "ALLOWED_MODELS", [MODEL])
    monkeypatch.setattr(main, "EVIDENCE_DIR", evidence_dir)
    monkeypatch.setattr(main, "REQUEST_TIMEOUT", 3.0)

    with TestClient(main.app) as client:
        yield client, store


def make_image():
    buffer = BytesIO()
    Image.new("RGB", (32, 32), "white").save(
        buffer, format="PNG"
    )
    return buffer.getvalue()


def valid_model_response():
    return json.dumps({
        "worker_count": 1,
        "workers": [{
            "position": "centre",
            "helmet": "missing",
            "vest": "worn",
            "boots": "worn"
        }],
        "helmet_violation": "yes",
        "vest_violation": "no",
        "boots_violation": "no"
    })


def mock_ollama(monkeypatch, outcome):
    """Intercept Ollama requests without using the network."""

    class FakeOllamaClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            if isinstance(outcome, Exception):
                raise outcome

            return httpx.Response(
                200,
                json={"message": {"content": outcome}},
                request=httpx.Request("POST", url)
            )

    monkeypatch.setattr(
        main.httpx, "Client", FakeOllamaClient
    )


def upload(client, frame_second=None):
    data = {
        "model": MODEL,
        "location": "Reliability test site",
        "camera": "TEST"
    }

    if frame_second is not None:
        data.update({
            "video_session_id": "concurrent-video-test",
            "video_name": "test.mp4",
            "video_timestamp_seconds": str(frame_second)
        })

    return client.post(
        "/api/analyze",
        data=data,
        files={
            "file": (
                "test.png",
                make_image(),
                "image/png"
            )
        }
    )


def test_ollama_disconnection(system, monkeypatch):
    client, store = system

    error = httpx.ConnectError(
        "Connection refused",
        request=httpx.Request(
            "POST", "http://mock-ollama.invalid/api/chat"
        )
    )

    mock_ollama(monkeypatch, error)

    response = upload(client)

    assert response.status_code == 502

    state = store.state()
    assert state["statistics"]["failed"] == 1
    assert len(state["items"]) == 0
    assert len(state["notifications"]) == 0


def test_inference_timeout(system, monkeypatch):
    client, store = system

    error = httpx.ReadTimeout(
        "Timed out",
        request=httpx.Request(
            "POST", "http://mock-ollama.invalid/api/chat"
        )
    )

    mock_ollama(monkeypatch, error)

    response = upload(client)

    assert response.status_code == 504
    assert store.state()["statistics"]["failed"] == 1
    assert len(store.state()["items"]) == 0


def test_malformed_json(system, monkeypatch):
    client, store = system

    mock_ollama(
        monkeypatch,
        "This is not a valid JSON response."
    )

    response = upload(client)

    assert response.status_code == 502
    assert store.state()["statistics"]["failed"] == 1
    assert len(store.state()["items"]) == 0


def test_missing_classification_fields(system, monkeypatch):
    client, store = system

    mock_ollama(monkeypatch, '{"worker_count": 1}')

    response = upload(client)

    assert response.status_code == 502
    assert store.state()["statistics"]["failed"] == 1
    assert len(store.state()["items"]) == 0


def test_recovery_after_model_failure(system, monkeypatch):
    client, store = system

    mock_ollama(monkeypatch, "Invalid response")
    failed = upload(client)

    assert failed.status_code == 502

    # Simulate Ollama recovering.
    mock_ollama(monkeypatch, valid_model_response())
    recovered = upload(client)

    assert recovered.status_code == 200
    assert recovered.json()["incident_action"] == "created"

    state = store.state()

    assert state["statistics"]["failed"] == 1
    assert len(state["items"]) == 1
    assert len(state["notifications"]) == 1


def test_concurrent_video_requests(system, monkeypatch):
    client, store = system

    mock_ollama(monkeypatch, valid_model_response())

    # Simulate several clients sending video frames together.
    with ThreadPoolExecutor(max_workers=6) as executor:
        responses = list(
            executor.map(
                lambda second: upload(client, second),
                range(8)
            )
        )

    assert all(r.status_code == 200 for r in responses), [
        (r.status_code, r.text) for r in responses
    ]

    results = [r.json() for r in responses]
    incident_ids = {r["incident_id"] for r in results}

    assert len(incident_ids) == 1
    assert sum(
        r["incident_action"] == "created"
        for r in results
    ) == 1

    state = store.state()

    assert len(state["items"]) == 1
    assert len(state["notifications"]) == 1
    assert state["items"][0]["detectionCount"] == 8

    incident_id = next(iter(incident_ids))
    frames = store.incident_analyses(incident_id)

    assert len(frames) == 8
    assert sorted(f["video_seconds"] for f in frames) == [
        float(i) for i in range(8)
    ]
