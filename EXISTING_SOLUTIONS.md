# Existing AI PPE detection and notification solutions

Research checked in November 2026. These are vendor-described capabilities, not independent validation of performance. Do not assume their advertised recognition accuracies generalize to your site.

| Solution | PPE / use case | Alerts and management | Product URL |
| --- | --- | --- | --- |
| viAct | Helmets, hi-vis vests, safety boots and other PPE; construction, warehouses, industry | CCTV monitoring; dashboard and email/SMS/WhatsApp alerts | https://www.viact.ai/ppedetection?lang=zh |
| Invigilo AI | Helmet, vest, gloves, goggles, harness and zone rules | Alerts to WhatsApp/Teams/Telegram/email, evidence, task ownership and escalation | https://www.invigilo.ai/ppe-detection |
| Intenseye | Broad PPE library: hard hats, reflective vests, gloves, eye protection, respiratory and other gear | On-camera monitoring, event history, alerts; image/video review | https://www.intenseye.com/detection-library/ppe |
| Protex AI | Configurable PPE rules for industry and warehouse zones | Event feed, dashboards, trends and corrective-action workflow | https://www.protex.ai/safety/ppe-detection |
| Voxel | Hard hats, safety vests, gloves, bump caps, hairnets | Incident triage, assigned actions, reporting on existing CCTV | https://www.voxelai.com/ppe |
| Intelense | PPE including boots, helmets, vests, gloves and masks | Zone rules, dashboard evidence and email/SMS/webhook escalation | https://www.intelense.com/solutions/ppe-detection-software |

## How our prototype differs

Our school project focuses on a no-fine-tuning, open-weight VLM using a remotely hosted Ollama model (`qwen3.8:27b`), a Python/FastAPI backend, and a React safety-manager dashboard. It currently handles **manual uploaded images**, labels helmet/vest/apparent boots, creates incidents and displays evidence **only in incident Details**. It includes explicit uncertainty and model-error handling.

The listed commercial products offer more mature camera integration, rule-by-zone functions and workflow/alert delivery. Ours should not be described as the first PPE detection/alert product, nor as validated for use in actual worker safety enforcement.

## Important limitations of visual boot detection

A photograph cannot confirm that apparent work boots meet a required safety-toe, puncture-resistance, or other certification. Footwear at a distance or out of frame must be marked *unclear*. Camera angle and image quality strongly affect footwear assessments. Independent validation using images with verified footwear labels is needed.

Reference on camera suitability: https://electriceye.ai/solutions/ppe-compliance-monitoring
