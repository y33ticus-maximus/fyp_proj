"""Data loading and transparent PPE evaluation metrics. No model calls are made."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

DATASETS = {
    "v1_helmet_vest": {
        "title": "Benchmark V1 · Helmet + Vest",
        "description": "Original 60-image verified benchmark (Roboflow Construction Site Safety v30).",
        "items": ("helmet", "vest"),
    },
    "v2_boots": {
        "title": "Benchmark V2 · Helmet + Vest + Boots",
        "description": "68 manually verified validation images from two Roboflow PPE datasets.",
        "items": ("helmet", "vest", "boots"),
    },
}

SCOPES = {"overall": "Overall PPE", "helmet": "Helmet", "vest": "Safety vest", "boots": "Boots"}
OUTCOMES = ("TP", "TN", "FP", "FN", "Unclear", "Error", "Unscored ground truth", "No prediction")


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def reviewed_images(dataset_dir: Path) -> list[dict]:
    return [row for row in read_csv(dataset_dir / "ground_truth.csv")
            if (row.get("review_status") or "").strip().lower() == "verified"]


def model_runs(dataset_dir: Path) -> tuple[dict[str, dict[str, dict]], list[str]]:
    """Load predictions per model, including only rows in CSV. Detect repeated names."""
    runs = {}
    warnings = []
    for path in sorted((dataset_dir / "predictions").glob("predictions_*.csv")):
        rows = read_csv(path)
        if not rows:
            warnings.append(f"{path.name}: contains no rows")
            continue
        model_names = {row.get("model", "").strip() for row in rows if row.get("model", "").strip()}
        if len(model_names) != 1:
            warnings.append(f"{path.name}: expected one model name, found {sorted(model_names)}")
            continue
        model = next(iter(model_names))
        if model in runs:
            warnings.append(f"Duplicate run for {model}: {path.name}; previous file retained")
            continue
        image_rows = {}
        for row in rows:
            image_name = Path(row.get("image", "")).name
            if not image_name:
                continue
            if image_name in image_rows:
                warnings.append(f"{path.name}: duplicate image {image_name}; first row retained")
                continue
            image_rows[image_name] = row
        runs[model] = image_rows
    return runs, warnings


def overall_value(item_values: list[str], *, prediction: bool) -> str:
    """yes means violation. A definite yes takes precedence over obscured items."""
    values = [v.strip().lower() for v in item_values]
    if prediction and any(v == "error" for v in values):
        return "error"
    if any(v == "yes" for v in values):
        return "violation"
    if values and all(v == "no" for v in values):
        return "compliant"
    if any(v == "unclear" for v in values):
        return "unclear"
    return "error" if prediction else "unclear"


def ground_truth(row: dict, scope: str, items: tuple[str, ...]) -> str:
    if scope == "overall":
        return overall_value([row.get(f"verified_{item}", "") for item in items], prediction=False)
    return row.get(f"verified_{scope}", "").strip().lower() or "unclear"


def prediction(row: dict | None, scope: str, items: tuple[str, ...]) -> str:
    if row is None:
        return "missing"
    if scope == "overall":
        raw = row.get("predicted", "").strip().lower()
        if raw in {"violation", "compliant", "unclear", "error"}:
            return raw
        return overall_value([row.get(f"pred_{item}", "") for item in items], prediction=True)
    if row.get("predicted", "").strip().lower() == "error":
        return "error"
    raw = row.get(f"pred_{scope}", "").strip().lower()
    return raw if raw in {"yes", "no", "unclear"} else "error"


def outcome(truth: str, pred: str, scope: str) -> str:
    if truth not in ({"violation", "compliant"} if scope == "overall" else {"yes", "no"}):
        return "Unscored ground truth"
    if pred == "missing":
        return "No prediction"
    if pred == "error":
        return "Error"
    if pred == "unclear":
        return "Unclear"
    pos, neg = ("violation", "compliant") if scope == "overall" else ("yes", "no")
    if pred == pos and truth == pos:
        return "TP"
    if pred == neg and truth == neg:
        return "TN"
    if pred == pos and truth == neg:
        return "FP"
    if pred == neg and truth == pos:
        return "FN"
    return "Error"


def evidence_rows(labels: list[dict], run: dict[str, dict], scope: str,
                  items: tuple[str, ...], *, include_unattempted: bool = False) -> list[dict]:
    output = []
    for label in labels:
        name = label["image"]
        model_row = run.get(name)
        if model_row is None and not include_unattempted:
            continue
        truth = ground_truth(label, scope, items)
        pred = prediction(model_row, scope, items)
        result = outcome(truth, pred, scope)
        output.append({
            "image": name,
            "truth": truth,
            "prediction": pred,
            "outcome": result,
            "model_row": model_row,
            "label_row": label,
        })
    return output


def safe_div(num: float, denom: float) -> float | None:
    return num / denom if denom else None


def metrics(rows: list[dict]) -> dict:
    c = Counter(r["outcome"] for r in rows)
    tp, tn, fp, fn = (c[k] for k in ("TP", "TN", "FP", "FN"))
    decided = tp + tn + fp + fn
    eligible = decided + c["Unclear"] + c["Error"] + c["No prediction"]
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = safe_div(2 * precision * recall, precision + recall) if precision is not None and recall is not None else None
    attempted = len(rows) - c["No prediction"]
    return {
        "attempted": attempted,
        "ground_truth_binary": eligible,
        "decisive": decided,
        "tp": tp, "tn": tn, "fp": fp, "fn": fn,
        "unclear": c["Unclear"], "errors": c["Error"],
        "unscored_truth": c["Unscored ground truth"],
        "accuracy": safe_div(tp + tn, decided),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": safe_div(fp, fp + tn),
        "coverage": safe_div(decided, eligible),
        "strict_accuracy": safe_div(tp + tn, eligible),
        "actionable_recall": safe_div(tp, tp + fn + sum(r['outcome'] in ('Error','Unclear','No prediction') and r['truth'] in ('violation','yes') for r in rows)),
    }


def full_image_rows(labels: list[dict], run: dict[str, dict], scope: str,
                    items: tuple[str, ...]) -> list[dict]:
    return evidence_rows(labels, run, scope, items, include_unattempted=True)
