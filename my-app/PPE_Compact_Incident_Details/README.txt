PPE DASHBOARD - COMPACT INCIDENT DETAILS

This update modifies ONLY the incident-information layout in App.jsx + App.css.
It moves the metadata below the video frame reviewer and groups the remaining
information into two compact areas: Site & Source and Activity & Timing.

It deliberately removes:
 - repeated video filename embedded in Camera
 - "Confidence: Not provided by model"
 - global Helmet/Vest/Boots fields for videos (already in frame reviewer)
 - inference time and worker count from the global video summary (per-frame values)

It retains status, severity, location, model, video filename once, initial and
last detection times, frame range, and the count of flagged frames. Standalone
image incidents retain PPE labels below the summary.

HOW TO APPLY (Windows)
1) Extract the ZIP.
2) Copy apply_compact_incident_details.py into the project root (next to my-app),
   or directly into the my-app folder.
3) Open PowerShell in that folder and run:

   py -3.12 apply_compact_incident_details.py

4) From my-app, run:

   npm.cmd run build

5) Open an incident's Details panel. Scroll past the frame reviewer to see the
   grouped incident information and the review actions.

The script creates timestamped backups of App.jsx and App.css. It preserves your
existing cross-device dashboard auto-refresh and other unrelated edits.
It refuses to make a change if it cannot locate the expected code.
