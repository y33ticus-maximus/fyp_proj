"""Automated tests for PPE incident storage.

All tests use temporary databases.
No Ollama connection or real PPE data is required.
"""

from pathlib import Path
import sys

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)

from storage import PPEStore


def make_store(tmp_path):
    return PPEStore(tmp_path / "test.sqlite3")


def result(
    status="violation",
    helmet="yes",
    vest="no",
    boots="unclear",
):
    return {
        "model": "test-model",
        "overall_status": status,
        "helmet_violation": helmet,
        "vest_violation": vest,
        "boots_violation": boots,
        "worker_count": 1,
        "processing_seconds": 0.5,
        "location": "Test site",
        "camera": "TEST-CAMERA",
        "evidence_url": "/api/evidence/test.jpg",
    }


def test_one_video_creates_one_incident(tmp_path):
    store = make_store(tmp_path)

    first = store.save_analysis(
        result(),
        video_session_id="video-a",
        video_name="sample.mp4",
        video_seconds=0,
    )

    second = store.save_analysis(
        result(helmet="no", vest="yes"),
        video_session_id="video-a",
        video_name="sample.mp4",
        video_seconds=2,
    )

    state = store.state()

    assert first["incident_action"] == "created"
    assert second["incident_action"] == "grouped"
    assert first["incident_id"] == second["incident_id"]
    assert len(state["items"]) == 1
    assert len(state["notifications"]) == 1

    incident = state["items"][0]

    assert incident["detectionCount"] == 2
    assert incident["helmetViolation"] == "yes"
    assert incident["vestViolation"] == "yes"


def test_all_video_frames_link_to_incident(tmp_path):
    store = make_store(tmp_path)

    compliant = result(
        status="compliant",
        helmet="no",
        vest="no",
        boots="no",
    )

    before = store.save_analysis(
        compliant,
        video_session_id="video-b",
        video_name="sample.mp4",
        video_seconds=0,
    )

    alert = store.save_analysis(
        result(),
        video_session_id="video-b",
        video_name="sample.mp4",
        video_seconds=2,
    )

    after = store.save_analysis(
        compliant,
        video_session_id="video-b",
        video_name="sample.mp4",
        video_seconds=4,
    )

    frames = store.incident_analyses(alert["incident_id"])

    assert before["incident_id"] is None
    assert after["incident_action"] == "linked"
    assert len(frames) == 3
    assert [f["video_seconds"] for f in frames] == [
        0.0, 2.0, 4.0
    ]
    assert len(store.state()["notifications"]) == 1


def test_different_videos_create_separate_incidents(tmp_path):
    store = make_store(tmp_path)

    a = store.save_analysis(
        result(),
        video_session_id="session-a",
        video_name="video.mp4",
        video_seconds=0,
    )

    b = store.save_analysis(
        result(),
        video_session_id="session-b",
        video_name="video.mp4",
        video_seconds=0,
    )

    assert a["incident_id"] != b["incident_id"]
    assert len(store.state()["items"]) == 2
    assert len(store.state()["notifications"]) == 2


def test_image_uploads_create_separate_incidents(tmp_path):
    store = make_store(tmp_path)

    a = store.save_analysis(result())
    b = store.save_analysis(result())

    assert a["incident_id"] != b["incident_id"]
    assert len(store.state()["items"]) == 2


def test_resolving_incident_clears_notification(tmp_path):
    store = make_store(tmp_path)

    saved = store.save_analysis(
        result(),
        video_session_id="video-resolve",
        video_name="sample.mp4",
        video_seconds=0,
    )

    incident_id = saved["incident_id"]

    assert store.update_status(incident_id, "Resolved")

    state = store.state()

    assert state["items"][0]["status"] == "Resolved"
    assert len(state["notifications"]) == 0

    store.save_analysis(
        result(helmet="no", vest="yes"),
        video_session_id="video-resolve",
        video_name="sample.mp4",
        video_seconds=2,
    )

    assert store.state()["items"][0]["status"] == "Resolved"
    assert len(store.state()["notifications"]) == 0


def test_archiving_preserves_history(tmp_path):
    store = make_store(tmp_path)

    saved = store.save_analysis(
        result(),
        video_session_id="video-archive",
        video_name="sample.mp4",
        video_seconds=0,
    )

    incident_id = saved["incident_id"]

    assert store.archive_incident(incident_id)

    state = store.state()

    assert state["items"][0]["status"] == "Archived"
    assert len(state["notifications"]) == 0

    store.save_analysis(
        result(helmet="no", vest="yes"),
        video_session_id="video-archive",
        video_name="sample.mp4",
        video_seconds=2,
    )

    assert store.state()["items"][0]["status"] == "Archived"
    assert len(store.incident_analyses(incident_id)) == 2
    assert len(store.state()["notifications"]) == 0


def test_model_failure_does_not_create_incident(tmp_path):
    store = make_store(tmp_path)

    store.save_failure(
        model="test-model",
        location="Test site",
        camera="TEST-CAMERA",
        message="Model unavailable",
        processing_seconds=0.5,
    )

    state = store.state()

    assert state["statistics"]["failed"] == 1
    assert len(state["items"]) == 0
    assert len(state["notifications"]) == 0
