
"""Controlled FastAPI load tests with mocked Ollama."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from math import ceil
from time import perf_counter, sleep
import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import main
from storage import PPEStore


MODEL = "mock-load-model"

# Adjustable, with limits to avoid accidental huge test runs.
WORKERS = min(16, max(1, int(os.getenv("PPE_LOAD_WORKERS", "8"))))
IMAGE_REQUESTS = min(
    120, max(1, int(os.getenv("PPE_LOAD_IMAGES", "30")))
)
VIDEO_REQUESTS = min(
    120, max(1, int(os.getenv("PPE_LOAD_FRAMES", "50")))
)


def image_bytes():
    buffer = BytesIO()
    Image.new("RGB", (64, 64), "white").save(
        buffer, format="PNG"
    )
    return buffer.getvalue()


MOCK_IMAGE = image_bytes()

MOCK_RESULT = json.dumps({
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


@pytest.fixture
def load_system(tmp_path, monkeypatch):
    store = PPEStore(tmp_path / "load.sqlite3")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    monkeypatch.setattr(main, "STORE", store)
    monkeypatch.setattr(main, "EVIDENCE_DIR", evidence_dir)
    monkeypatch.setattr(main, "ALLOWED_MODELS", [MODEL])
    monkeypatch.setattr(
        main, "OLLAMA_BASE_URL", "http://mock-ollama.invalid"
    )

    class FakeOllamaClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            # Small artificial delay to overlap requests.
            sleep(0.02)

            return httpx.Response(
                200,
                json={
                    "message": {
                        "content": MOCK_RESULT
                    }
                },
                request=httpx.Request("POST", url)
            )

    # Construct the test client before mocking httpx.Client.
    with TestClient(main.app) as client:
        monkeypatch.setattr(
            main.httpx, "Client", FakeOllamaClient
        )
        yield client, store, evidence_dir


def send_request(client, index, video=False):
    fields = {
        "model": MODEL,
        "location": "Load test site",
        "camera": "LOAD-TEST"
    }

    if video:
        fields.update({
            "video_session_id": "one-load-test-video",
            "video_name": "load-test.mp4",
            "video_timestamp_seconds": str(index)
        })

    start = perf_counter()

    try:
        response = client.post(
            "/api/analyze",
            data=fields,
            files={
                "file": (
                    "load-test.png",
                    MOCK_IMAGE,
                    "image/png"
                )
            }
        )

        elapsed = perf_counter() - start

        return {
            "status": response.status_code,
            "seconds": elapsed,
            "body": (
                response.json()
                if response.status_code == 200
                else response.text
            )
        }

    except Exception as error:
        return {
            "status": 0,
            "seconds": perf_counter() - start,
            "body": repr(error)
        }


def run_batch(client, count, video):
    start = perf_counter()

    with ThreadPoolExecutor(
        max_workers=min(WORKERS, count)
    ) as executor:
        results = list(
            executor.map(
                lambda index: send_request(
                    client, index, video
                ),
                range(count)
            )
        )

    wall_seconds = perf_counter() - start

    durations = sorted(r["seconds"] for r in results)

    p50 = durations[ceil(len(durations) * 0.50) - 1]
    p95 = durations[ceil(len(durations) * 0.95) - 1]

    successes = sum(
        r["status"] == 200 for r in results
    )

    print()
    print("Requests:", count)
    print("Concurrent workers:", min(WORKERS, count))
    print("Successful:", successes)
    print("Failed:", count - successes)
    print("Total time: %.3f s" % wall_seconds)
    print("Median latency: %.3f s" % p50)
    print("P95 latency: %.3f s" % p95)
    print(
        "Throughput: %.2f requests/s"
        % (count / wall_seconds)
    )

    failures = [
        r for r in results if r["status"] != 200
    ]

    assert not failures, (
        "Request failures: " + repr(failures[:5])
    )

    return results


def test_concurrent_independent_images(load_system):
    client, store, evidence_dir = load_system

    results = run_batch(
        client, IMAGE_REQUESTS, video=False
    )

    state = store.state()

    # Each separate image is a separate incident.
    assert len(state["items"]) == IMAGE_REQUESTS
    assert len(state["notifications"]) == IMAGE_REQUESTS

    assert len({
        result["body"]["incident_id"]
        for result in results
    }) == IMAGE_REQUESTS

    # Every successful analysis is retained.
    assert state["statistics"]["analyses"] == IMAGE_REQUESTS

    # Each violation has its own evidence photograph.
    assert len(
        list(evidence_dir.glob("*.jpg"))
    ) == IMAGE_REQUESTS


def test_concurrent_frames_one_video(load_system):
    client, store, evidence_dir = load_system

    results = run_batch(
        client, VIDEO_REQUESTS, video=True
    )

    state = store.state()

    # All frames belong to one video incident.
    assert len(state["items"]) == 1
    assert len(state["notifications"]) == 1

    ids = {
        result["body"]["incident_id"]
        for result in results
    }

    assert len(ids) == 1

    assert sum(
        result["body"]["incident_action"] == "created"
        for result in results
    ) == 1

    incident = state["items"][0]

    assert incident["detectionCount"] == VIDEO_REQUESTS

    frames = store.incident_analyses(incident["id"])

    assert len(frames) == VIDEO_REQUESTS

    assert sorted(
        frame["video_seconds"] for frame in frames
    ) == [
        float(i) for i in range(VIDEO_REQUESTS)
    ]

    assert len(
        list(evidence_dir.glob("*.jpg"))
    ) == VIDEO_REQUESTS
