# PPE Safety Manager Dashboard — Remote Ollama VLM Prototype

This project is based on your supplied React/Vite dashboard, with a small **FastAPI backend** added to connect to a **remote Ollama vision-language model** such as `qwen3.8:27b`.

## What works

- Upload one JPG / PNG / WebP image in the dashboard.
- Choose a model from the backend-configured remote-model list (default `qwen3.8:27b`).
- FastAPI sends the image **from the backend to the remote Ollama server**, not from the browser directly.
- Model classifies missing **hard hats** and **high-visibility vests**, with `yes`/`no`/`unclear` labels.
- A **violation** creates an Open incident and an unread notification.
- An **unclear** helmet/vest assessment creates an Under Review incident and notification; it is **not falsely marked compliant**.
- **No-workers**, **compliant**, and **failed/incomplete model responses** do not create violation notifications.
- A detected incident's **evidence photograph appears only when you open Incident Details** (including by clicking a bell notification). **No images in the notification dropdown or incident table.**
- Existing sample data, simulation button, incident workflow, charts and dark/light mode are preserved.

## Folder structure

```text
PPE_Dashboard_Remote_Qwen_Integrated/
├── backend/
│   ├── main.py                  # FastAPI → remote Ollama inference
│   ├── requirements.txt
│   ├── .env.example             # Example remote-server configuration
│   ├── .env                     # You create this privately; not in ZIP
│   └── data/evidence/           # Evidence photos (untracked)
└── my-app/
    ├── src/App.jsx             # Original dashboard + incident details evidence
    ├── src/AnalysisUpload.jsx  # Image upload + model selection
    ├── src/App.css             # Original CSS + upload/evidence styles
    ├── vite.config.js          # Forwards /api requests to FastAPI
    └── package.json
```

## Step 1: Configure the remote model (VS Code)

1. Extract this ZIP and open the **top-level project folder** in VS Code.
2. Copy `backend/.env.example` to a new file named `backend/.env`.
3. Change `OLLAMA_BASE_URL` to the **same remote Ollama server address that already worked in your Jupyter notebook**, including its port. Do not use `localhost` unless Ollama runs on your own PC.
4. Keep `OLLAMA_MODELS=qwen3.8:27b` to start. To enable more remote *vision-capable* models already installed on the server, use a comma-separated list, e.g. `OLLAMA_MODELS=qwen3.8:27b,qwen3.6:27b`.
5. Ensure you can access the remote server from your PC and that your supervisor authorizes its use. The local FastAPI backend must be running on a machine that can reach the remote Ollama server.

**Never commit `backend/.env` or expose private remote-server endpoints or credentials inside frontend code.**

## Step 2: Start FastAPI (Terminal 1)

Open a VS Code terminal in the `backend` folder, then run:

```powershell
py -m pip install -r requirements.txt
py -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

If `py` does not work, use `python -m pip` and `python -m uvicorn` with your project Python environment instead.

Check: `http://127.0.0.1:8000/api/health` and `http://127.0.0.1:8000/api/models`.

- `remote_configured: true` in `/api/health` means the URL was loaded, **not** that the remote server was reached.
- `connected: true` and the expected model in `available` from `/api/models` confirm basic connectivity and the model name (but not that image inference succeeds).

## Step 3: Start React (Terminal 2)

Open another VS Code terminal in `my-app`:

```powershell
npm.cmd install
npm.cmd run dev
```

PowerShell users can use `npm.cmd` to avoid execution policy problems with `npm.ps1`.

Open the URL printed by Vite (usually `http://localhost:5173`, sometimes `5174`). The Vite proxy forwards any browser `/api/` requests to `http://127.0.0.1:8000`.

## Step 4: Try a remote inference

1. Select a construction-site photo containing visible workers.
2. Check that the status says **Remote Ollama connected**, and select `qwen3.8:27b`.
3. Click **Analyse image** and leave the page open until the response arrives.
4. For violation/unclear results, an incident appears in the table and the bell's unread count increases.
5. Click **Notifications** → the incident → **Details**. You will see the uploaded evidence image **inside the details modal**, not on the notification list.
6. Review the evidence before resolving or dismissing the incident.

If no workers or no missing helmet/vest is found, the result appears under the form but **no incident is created**. If the server times out or emits invalid JSON, an error appears and **no incident is created**.

## Important limitations (prototype)

- **No continuous camera/video capture yet.** Only manual single-image upload.
- **No shared incident database yet.** Incident details/statuses/notifications are stored in the **current browser's localStorage**. Evidence photos are stored separately under `backend/data/evidence/`; keep that folder and the backend running for images to remain available. Reset demo does not delete server evidence photos.
- **Do not delete `backend/data/evidence`** if you want previously created photo evidence to remain accessible. No automated cleanup has been implemented; manage retention manually.
- **No login, role-based access control, TLS, or audit log**. Do not expose the backend or the development server publicly and do not use real workplace-sensitive imagery without permission. The remote Ollama connection may use **unencrypted HTTP** on an internal network.
- The existing **compliance percentage, detected people count and weekly graph are still SAMPLE figures**, not measured from the real model. Incoming incidents only affect incident counters.
- **No calibrated model confidence** is returned. The details panel correctly displays "Not provided by model" instead of inventing a percentage.
- **Model results are unverified**. They should be reviewed by a human and cannot replace workplace PPE enforcement or professional safety checks.
- If your existing browser contains demo data, it may still appear after opening this version. Use *Reset demo* if desired.
- A model saying `helmet_violation=yes` means at least one worker in the **image** is suspected of missing a helmet. The current prototype is **image-level**, not reliably person-level.

## Tests

From the `backend` directory:

```powershell
py -m pip install pytest
py -m pytest tests -q
```

The included tests mock the remote Ollama response (they do **not** contact your supervisor's server). This checks correct parsing, error handling, evidence photo storage and endpoint structure.
