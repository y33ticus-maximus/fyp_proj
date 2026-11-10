# PPE Safety Manager — SQLite + Live Metrics + Video Alert Grouping

This is an **update-only** package for your current working React/Vite + FastAPI dashboard. It does **not** contain an Ollama model, `.env`, videos, saved evidence, `node_modules`, or your virtual environment. Do not use it to replace your entire working folder.

## Changes

1. **Duplicate video alerts:** Frames from the **same video analysis run** with the same reported PPE violation are grouped into one incident when successive matching detections are no more than 120 seconds apart *in video time*. Only one initial notification is created. Different runs, different violation sets, and resolved/dismissed incidents are not merged. Grouping does **not** identify or track individual workers.
2. **Real statistics:** Statistics use SQLite analyses instead of hardcoded examples. The compliance metric is `compliant / (compliant + violation)` from **decisive model predictions only**; unclear, unknown boots, failed inferences, and no-worker frames are not counted as compliant. Worker counts are **observations per image/frame**, not unique people. The seven-day chart uses Singapore time; days with no decisive data have no plotted value. Statistics pool predictions from all models, **not a ground-truth performance benchmark**.
3. **SQLite records:** Every accepted analysis is stored, including successful compliant results, unclear/no-worker results and model-call failures. Incidents, in-app notifications, status changes, video timestamps and evidence paths persist across restarts. Incident Details shows individual saved violation frames for grouped incidents.
4. **Existing data migration:** On first opening the updated dashboard, real incidents saved in the old `localStorage` entry `ppe-manager-demo-v1` are copied once into SQLite. Old browser data is **not deleted**. Empty objects, examples without model records and simulation incidents are not imported. Imported historical incidents count in incident totals, but not in compliance/trend metrics because their complete classification history was not stored.
5. **Ollama preserved:** The existing `/api/chat` request and PPE prompt are unchanged. The backend uses whatever local or remote Ollama URL and allowed model(s) you have configured in your existing `.env`. UI labels are now neutral.

## Before installation: back up your working project

1. Stop your Vite and FastAPI terminals (`Ctrl+C`).
2. Copy your **entire current working dashboard folder** to a backup location.
3. In particular, retain `backend/.env`, `backend/data/evidence/` and the browser profile where your old incidents are stored. Do not clear local storage.
4. Keep your existing `my-app/node_modules` and `.venv` — nothing in this update replaces them.

## Install by copying into your existing project

Extract this archive to a temporary location. **Copy and overwrite only these paths** in your working dashboard:

| From this update | To your existing working dashboard |
|---|---|
| `backend/main.py` | `backend/main.py` |
| `backend/storage.py` (NEW) | `backend/storage.py` |
| `backend/.gitignore` | `backend/.gitignore` (adds SQLite exclusions) |
| `my-app/src/App.jsx` | `my-app/src/App.jsx` |
| `my-app/src/AnalysisUpload.jsx` | `my-app/src/AnalysisUpload.jsx` |
| `my-app/src/VideoSampler.jsx` | `my-app/src/VideoSampler.jsx` |
| `my-app/src/App.css` | `my-app/src/App.css` |

Unchanged `MediaAnalysis.css`, `index.css`, `package.json`, `vite.config.js` and `requirements.txt` are **not** required to be replaced. The test file `backend/tests/test_storage.py` is optional to copy.

**Important:** `backend/storage.py` is a new required file. Without it, FastAPI will fail with `ModuleNotFoundError: No module named 'storage'`.

## Start locally with your already-working model

From your existing project:

**Backend (first terminal):**

```powershell
cd backend
py -m uvicorn main:app --reload --port 8000
```

**Frontend (second terminal):**

```powershell
cd my-app
npm.cmd run dev
```

Continue using your **existing** `backend/.env`. For the local MiniCPM model, it may already contain:

```dotenv
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODELS=openbmb/minicpm-v4.7:1b
OLLAMA_TIMEOUT_SECONDS=240
```

No change is required if the local model already works. When the remote server is restored, change just your existing `.env` model/URL settings and restart FastAPI. The database will remain unchanged.

## Verify it works (also works when Ollama is disconnected)

- Open `http://127.0.0.1:8000/api/state` — you should see JSON with `items`, `notifications`, `statistics`, and `trend`.
- Open your dashboard, check whether your earlier *real* browser incidents were imported (simulated entries will be excluded). They will appear in `Recorded incidents`.
- Analyze one compliant image: one analysis is saved, **no incident** is created, and the statistics update.
- Analyze an image with a PPE violation: one incident, one notification, and a preserved evidence image in Details.
- Analyze a short video at 5-second intervals. For repeated violations of the same type, you should see **one incident with multiple detections**, rather than a new alert for every frame. Select its Details > Saved detection frames to review individual stored evidence.
- Mark a notification read, change an incident to Resolved, refresh the browser or restart FastAPI. The changes should persist.
- If Ollama is disconnected, you can still open the dashboard, review incidents and view live database statistics. New model inference requires an available Ollama model.

Database location: `backend/data/ppe_monitoring.sqlite3` (plus temporary `-wal`/`-shm` files as needed). **Do not delete this file** after you have collected results. Evidence images remain in `backend/data/evidence/`; the database contains references to those images, not embedded blobs.

Optional `.env` setting for changing the alert grouping window (seconds of **video**, default 120):

```dotenv
PPE_DUPLICATE_WINDOW_SECONDS=120
```

If you enable Git, check that `.env`, the SQLite database and evidence photographs are not being committed. These are prototype data, and your local FastAPI service has **no authentication**; do not expose it publicly.

## Tests and rollback

Run offline backend tests (requires `pytest`):

```powershell
cd backend
py -m pytest tests/test_storage.py -q
```

The update has been checked against **16 backend tests** (the nine original FastAPI tests plus seven new tests) and all three modified JSX files were syntax-parsed successfully. The full React Vite production build was **not run here** because npm package installation from the registry was unavailable in this environment. On your computer, validate with:

```powershell
cd my-app
npm.cmd run build
```

If you need to roll back, stop both servers and restore the old source files from your backup. **Keep** `backend/data/ppe_monitoring.sqlite3` and your evidence directory, because newer data saved there may be useful when you re-apply the update. The old browser `localStorage` entry has not been deleted by this version.
