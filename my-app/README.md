# PPE Dashboard — Hybrid Overview Redesign

This package updates **only two frontend files**:

- `src/App.jsx` — dashboard overview layout and navigation presentation.
- `src/App.css` — layout, responsive styles, and dark-mode styling.

The package does **not** change your AI analysis, video sampling, evidence selection,
incident review, PDF generation, or backend API implementations.

## Installation (Windows / VS Code)

1. Make a backup of your current `my-app/src/App.jsx` and `my-app/src/App.css`.
2. Copy the two files from this package's `src` directory into your project's
   `my-app/src` directory, replacing those two files only.
3. Keep all other project files as they are; especially `AnalysisUpload.jsx`,
   `VideoSampler.jsx`, `videoSampling.js`, `ReportPreview.jsx`, and their CSS files.
4. Run the frontend using the same command you currently use (typically `npm run dev`).
5. Check the Overview page, use its links to open the incident queue and Details,
   and recheck AI analysis and PDF reports with your running backend.

Do **not** run `git apply` for this package. It contains complete replacement
source files, not a context-sensitive patch.

## What changed

- Hybrid home: operational overview, model-reported compliance trend,
  attention/review queue, recent incidents, and PPE concern breakdown.
- Contextual shortcuts: cards open Incident management with the intended filter,
  while recent incidents open the existing Details workflow.
- Sidebar styling and visual hierarchy are refreshed.
- Desktop, tablet, mobile and dark-mode rules are included.
- Existing API data is reused; no extra backend endpoints are required.

## Accuracy / safety notes

The compliance percentage, incident signals, and counts are based on existing
AI predictions and incident records. They must not be interpreted as verified
safety audit findings or model accuracy scores. Multiple PPE categories may be
associated with one active incident.

## Verification status

JS/JSX syntax was parsed successfully for the current frontend source set.
The full Vite build and browser integration could not be run here because
the package manifest, dependency installation and live backend were not supplied.
Please run the normal frontend build and exercise incident links locally.
