# Changes compared with the uploaded dashboard

- **New `backend/main.py`:** FastAPI image-upload endpoint, remote Ollama `/api/chat` integration for `qwen3.8:27b`, JSON parsing, explicit `unclear`/error handling, and persisted evidence photo URLs.
- **New `backend/.env.example` and `requirements.txt`:** configurable remote server/model settings; installation list.
- **New `my-app/src/AnalysisUpload.jsx`:** model selector, image upload, camera/location input, server connectivity status, inference result and error messages.
- **Modified `my-app/src/App.jsx`:** real-image result -> incidents and notifications, incident details show PPE labels, model, timing, evidence photograph. Preserved existing demo and localStorage data.
- **Modified `my-app/src/App.css`:** styling for upload, result, remote connection, incident evidence and dark mode.
- **Modified `my-app/vite.config.js`:** proxy browser `/api` requests to FastAPI on `127.0.0.1:8000`.
- **New `backend/tests/test_backend.py`:** mocked remote inference tests.

**Unchanged:** Recharts weekly sample chart, sample compliance metric, original incident table columns, notification list text-only design, simulation controls, dark/light theme workflow.

**Still needed later:** real camera feed, shared incident database, alert deduplication, user authentication, Telegram, audited access/evidence controls, live metrics.

## New update — Boots PPE class

- `backend/main.py`: expanded Qwen prompt for visual boots; validates tri-state footwear and includes boots in incident decision. Ambiguous boots have a separate `boots_unverified` result unless `review_unclear_boots=true`.
- `my-app/src/AnalysisUpload.jsx`: shows Helmet / Vest / Boots values and optional boot uncertainty review setting.
- `my-app/src/App.jsx`: adds boots-only incident generation, notification text, and Boots violation in incident Details, retaining evidence photos only in Details.
- `my-app/src/App.css`: styles the new checkbox.
- `backend/tests/test_backend.py`: tests boots-only violation, unknown footwear and review opt-in.

------------------------------------------------------------------------------------------------------------------------

# PPE Safety Manager — Media + AI Results Panel Update

This is a **drop-in update**, not a separate dashboard. Keep using the existing working folder with `backend/main.py`, `my-app/src/App.jsx`, and your local `backend/.env`.

## Install

1. Back up your existing `my-app/src/AnalysisUpload.jsx`, `VideoSampler.jsx`, and any preview customisations you want to retain.
2. Copy the **three files** from this ZIP's `my-app/src/` folder into the same `my-app/src/` folder in your working Qwen + boots dashboard:
   - `AnalysisUpload.jsx` (replace)
   - `VideoSampler.jsx` (replace)
   - `MediaAnalysis.css` (new file)
3. Leave `App.jsx`, `App.css`, `backend/main.py`, and `backend/.env` unchanged.
4. Restart the Vite frontend and ensure the FastAPI backend is running.

Run frontend from `my-app`:

```powershell
npm.cmd run dev
```

Run backend from `backend` using your existing Python environment:

```powershell
py -m uvicorn main:app --reload --port 8000
```

## Features

- Uploaded image preview left, corresponding PPE results right.
- Uploaded video player left; latest sampled frame and its results shown in the same layout.
- Per-worker assessment table, if supplied by the backend.
- Clickable video frame history, keeping results and frames aligned by timestamp.
- Selectable sampling intervals 5, 10, 30, or 60 seconds; **default is 60 seconds**.
- Preserves FastAPI `/api/analyze` and `onResult` callback for existing incidents and notifications.
- Removes duplicate bottom result box.
- One remote inference request at a time; individual frame inference errors are recorded, and remaining frames can continue.

## Important limitations

- Previews and video history live in browser memory and vanish on refresh; existing incident evidence is saved by FastAPI as before.
- A video file is not uploaded in full. Only frames selected for analysis are sent to FastAPI.
- Multiple frames showing the same violation can still create duplicate incidents; this update does not add alert deduplication.
- Results reflect what Qwen reported; there are no object-detection bounding boxes.
- Large videos/long frame histories consume browser memory; keep tests reasonably short.
- The source video and frames require a browser-supported codec (H.264 MP4 recommended).

## Initial test

1. Test one compliant JPG and one known PPE-violation image, ensuring incidents still appear in Details.
2. Use a 23-second MP4 with the interval set to **5 seconds**; expect frames at 0s, 5s, 10s, 15s, and 20s.
3. Click each timestamp and verify that the frame and right-side results change together.
4. Switch to the intended **60-second** interval after testing.
