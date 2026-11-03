# Included sources and implementation notes

- Imported your existing 60 verified original images and all seven models' per-image prediction CSVs from the previously uploaded `test model.zip`.
- Imported the 68 verified images from `PPE_Boots_V2_Zero_Shot_Evaluation.zip` and all 90 review decisions from its CSV. Excluded candidate images are not included in the V2 image folder or performance scoring.
- Retained saved V1 `metrics_*.csv` files and the original `model_comparison.csv` as reproducibility artifacts; the dashboard **recalculates** the displayed scores from per-image predictions to make every image-to-metric link auditable.
- Added separate V1/V2 benchmarking to prevent mixing different numbers of PPE categories.
- Included a filterable evidence gallery, full detail view, individual item predictions, raw model responses, and model-vs-model comparison on identical images.
- Added optional future V2 prediction ingestion via `data/v2_boots/predictions/`.
- Source files do not contain Python virtual environments, Git internals, remote Ollama server configuration, or API credentials.
- Verified all model/scope counts against the original 21-row comparison table with automated tests.
