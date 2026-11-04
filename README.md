# PPE Model Evaluation Viewer

A **read-only Streamlit dashboard** to present your zero-shot PPE Vision-Language Model experiments to a supervisor. Every image shown is an **actual photograph from your reviewed evaluation datasets**, and every model prediction comes from your saved CSV output. This app never runs or downloads a VLM.

## What's included

| Benchmark | Reviewed test images | Saved model runs | PPE categories |
| --- | ---: | ---: | --- |
| V1 — original PPE benchmark | **60** | **7** | Helmet, vest |
| V2 — expanded boots validation | **68** | **0** (awaiting your evaluation CSVs) | Helmet, vest, boots |

For V1, the included model results are `gemma3:4b`, `llava:7b`, `llava:13b`, `minicpm-v4.6:1b`, `openbmb/minicpm-v4.7:1b`, `qwen3.8:27b`, and the failed attempt `dlasher/MiniCPM-V-4.7-35B-A3B:IQ4_NL`. A failed model run shows a response error, **not 0% model accuracy**.

### App pages

- **Overview** — cross-model accuracy, precision, recall, F1, false-positive rate, coverage and request time; confusion matrices and **actual example photos of model mistakes**.
- **Evidence Explorer** — image gallery with filters for True Positive, True Negative, False Positive, False Negative, Unclear and Error. Inspect ground truth, model output, per-PPE predictions, worker count, inference time, and original text/JSON.
- **Model vs Model** — same image with two models' predictions side by side; optionally show only images where they disagree.
- **Ground-truth gallery** — view actual photographs and verified labels, including the V2 boots set before its model predictions are available.
- **Methodology** — metric definitions, label conventions and data attribution.

## 1. Run locally on Windows using VS Code

Extract the entire ZIP (including `data/`). Open the extracted `PPE_Model_Evaluation_Viewer` folder in VS Code. Open a **PowerShell terminal** in this folder.

A Python 3.11 or 3.12 virtual environment is recommended. Your earlier Windows Python 3.15 setup ran into restrictions with compiled pandas libraries, so using a normal Python 3.12 environment may be easier.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

If `py -3.12` isn't available, install Python 3.12 or use another installed supported Python version (e.g. `py -3.11`). The Streamlit dependencies are installed *into this new environment* rather than modifying the existing Jupyter environment.

Open the URL shown in your terminal, commonly `http://localhost:8501`.

> No Ollama server, GPU, model weights, FastAPI backend, or Jupyter notebook is needed to **view** the evaluation results. All the images shown are bundled with this project.

## 2. Share it online with your supervisor

The simplest way is to use [Streamlit Community Cloud](https://streamlit.io/cloud) with a GitHub repository.

1. Make a **separate repository** for this evaluation viewer; upload `app.py`, `evaluation.py`, `requirements.txt`, `.streamlit/config.toml`, and the entire `data` folder. Do **not** upload `.venv/`, your private Ollama host settings, credentials, or unrelated `.git` folders from the source project.
2. Deploy that repository as a Streamlit app, selecting `app.py` as the entrypoint.
3. Give your supervisor the deployment URL. They will view **photos and results in the browser**, without running the notebook or downloading an image dataset manually.
4. If you need restricted viewing, check the access-control and private-app options provided by your chosen hosting plan. **A private GitHub repository does not, by itself, make the deployed website private.**

Images sent to a web browser are inherently retrievable by that viewer. The viewer is intended to avoid *manual dataset downloads*, not to provide digital-rights protection.

## 3. Add results from your expanded boots evaluation

When your V2 notebook produces predictions, copy **each model's** exported predictions file into:

```text
data/v2_boots/predictions/predictions_qwen3_8_27b.csv
data/v2_boots/predictions/predictions_llava_13b.csv
```

Use **your actual exported filenames** (`predictions_*.csv`); the examples above are illustrative. Required columns:

- `image` (must match the name of a V2 image)
- `model` (the model name)
- `predicted` (`violation`, `compliant`, `unclear`, or `error`)
- `pred_helmet`, `pred_vest`, `pred_boots` (`yes`, `no`, `unclear`; empty on errors)

Optional detail columns include `seconds`, `error`, `pred_worker_count`, and `raw_response`.

Refresh the app. It will **recalculate** comparison metrics directly from the per-image predictions and display the corresponding photographs. The original model runs are **never mixed** with the boots runs because they live in separate benchmark folders.

**Important:** Use predictions on the exact same reviewed V2 images with the same prompt/settings to make a fair model comparison. If you change your prompt or run a distinct dataset, create a new benchmark folder/version rather than silently overwriting the old one.

## 4. Folder structure

```text
PPE_Model_Evaluation_Viewer/
├── app.py                           # Streamlit interface
├── evaluation.py                    # Metric logic independent of UI
├── requirements.txt
├── .streamlit/config.toml
├── data/
│   ├── v1_helmet_vest/
│   │   ├── ground_truth.csv         # 60 manually reviewed images
│   │   ├── images/                  # All 60 original photos
│   │   ├── predictions/             # Seven models' saved image predictions
│   │   ├── metrics/                 # Original exported per-model metrics
│   │   └── model_comparison.csv     # Original comparison (reference)
│   └── v2_boots/
│       ├── ground_truth.csv         # All 90 reviews, 68 verified
│       ├── images/                  # Only the 68 verified photos
│       └── predictions/             # Drop new V2 prediction CSVs here
└── tests/test_evaluation.py
```

## 5. Metric interpretation

The violation is the *positive* class:

- **TP:** violation found correctly.
- **TN:** compliant scene classified correctly.
- **FP:** false safety alert.
- **FN:** actual PPE violation missed.
- **Accuracy:** `(TP + TN) / (TP + TN + FP + FN)` on decisive, binary-labelled images only.
- **Recall:** `TP / (TP + FN)`; **Precision:** `TP / (TP + FP)`; **F1:** harmonic mean of precision and recall.
- **Coverage:** decisive classifications / images with binary ground truth.
- **Strict accuracy:** correct decisive classifications / images with binary ground truth (including unclear/error as non-correct).
- **Actionable recall:** detected true positives / all positive ground truth images, including those where the model was unclear or errored.

No model-output confidence percentage is invented. Undefined ratios are displayed as `N/A`, not as zero.

The V1 and V2 **overall** classifications measure different category sets (V1: helmet/vest; V2: helmet/vest/boots) and should not be compared as if identical benchmarks.

## 6. Image attribution and usage

- **V1:** [Construction Site Safety — Roboflow Universe Projects, version 30](https://universe.roboflow.com/roboflow-universe-projects/construction-site-safety/dataset/30), listed as **CC BY 4.0**.
- **V2, source A:** [PPE Detection v1](https://universe.roboflow.com/testcasque/ppe-detection-qlq3d/dataset/1), source metadata lists **CC BY 4.0**.
- **V2, source B:** [Vest-Boots v6](https://universe.roboflow.com/epidataset-fnaft/vest-boots/dataset/6), source metadata lists **Public Domain**.

Image labels were independently reviewed for this project; some candidate images were excluded. Source licence labels do not guarantee that third-party underlying photographs have no restrictions; confirm rights before publishing a public app. Use an access-controlled app first if unsure. Images cannot prove safety-boot certification.

## 7. Verification

Run the included tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests verify that all 60 V1 predictions have matching image files, that all 68 verified V2 image files are present, and that the recomputed TP/TN/FP/FN metrics match **every row** in your original 21-row V1 model comparison CSV.

## Limitations

The app is **read-only** and intended for demonstration/review, not actual hazard alerting. It is not connected to your supervisor's Ollama service, and it does not automatically update when notebook evaluations run on another computer; copy/sync the CSVs into the relevant benchmark folder and redeploy or refresh as needed.
