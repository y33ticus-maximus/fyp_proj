# PPE Safety Manager Dashboard

This dashboard now supports **remote Ollama image inference through FastAPI**. For the full startup instructions, including configuring `qwen3.8:27b`, see **`../README.md`** in the top-level project folder.

The existing sample data, demo simulator, filters, notification bell, incident workflow and dark/light mode are preserved. Images from remote VLM incidents appear **only in the incident Details modal**, not the notification list.

PPE Safety Manager — ONE VIDEO, ONE INCIDENT (Change 2)
======================================================

This small update contains ONE code file: backend/storage.py

Prerequisite: Your project already uses the previously supplied SQLite update
and backend/main.py accepts video_session_id and video_timestamp_seconds.

Before installation:
1. Stop FastAPI (Ctrl+C).
2. Back up backend/storage.py and backend/data/ppe_monitoring.sqlite3.
   Do not delete the database, or the evidence images in backend/data/evidence.

Installation:
3. Copy backend/storage.py from this ZIP over YOUR backend/storage.py.
4. Restart FastAPI with your usual uvicorn command.
5. Analyze a NEW short video; different PPE findings should produce one
   SQLite incident and one notification. Each frame is still recorded.

How it works:
- Groups by UUID video_session_id, not just identical PPE labels.
- A video with no flagged PPE results creates no incident.
- Still-image violations retain their existing one-image behavior.
- A fresh analysis run (even for the same filename) creates a new session.
- Existing incident records remain unchanged: this does NOT merge old alerts.
- Reported helmet/vest/boots concerns accumulate across video frames.
- The existing Details view can inspect saved flagged-frame photos;
  non-alert frames still retain their predictions/timestamps in SQLite.

Verification without Ollama:
  py -3.12 -m py_compile backend/storage.py

If you have customized storage.py since the original SQLite update,
compare with your local file before overwriting it.
