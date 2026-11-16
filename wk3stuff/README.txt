Boots validation image review kit — zero-shot VLM evaluation
==============================================================
Contains 90 candidate validation images ONLY (no train/test images):
  45 annotated "No-Boots", 35 annotated "Boots", 10 with no boot annotations.

IMPORTANT: These are candidates, NOT verified ground truth!
- Complete verified_helmet, verified_vest, verified_boots as yes/no/unclear.
- yes: definite PPE violation, no: no visible violation and all relevant workers assessable,
  unclear: uncertain visibility/footwear; avoid inferring safety certification from appearance.
- For out-of-scope images (product-only boots, non-workplace scenes, no relevant workers),
  set review_status = excluded.
- Set review_status = verified ONLY after manually assessing all three categories.
- Existing notebook is NOT ready to score boots yet. Add boots ground truth and boots metrics
  before treating scores as a three-category result.
- Source annotations are hints only. Missing YOLO box does NOT establish compliance.
- Dataset 2 includes grayscale, stretched/rotated images. Consider image realism.
- This kit is kept separate from your original 60-image helmet/vest benchmark.
- source_dataset, source_url and source_license are saved in the CSV for attribution.
- In the current notebook you can point IMAGE_DIR to extracted images/, and LABELS_CSV
  to ground_truth_boots_review.csv after updating the notebook to score boots.
