# PPE Compliance — Zero-Shot VLM Evaluation

This repository contains a school-project experiment comparing pretrained vision-language models (VLMs) for identifying potential personal protective equipment (PPE) violations in images. The goal is to evaluate models **without fine-tuning or additional training** before integrating a selected model into a PPE monitoring dashboard for safety managers.

## Project contents

- `load_model*.ipynb` — Jupyter notebooks for model testing and evaluation (different experimental versions).
- `ground_truth_review*.csv` — ground-truth review files used to check image-level PPE labels.
- `model testing images/` — test images; **not necessarily all from the same source**.
- `ppe_model_results/` — generated model predictions and comparison metrics.

Some filenames and notebook options may vary as the project develops.

## Evaluation approach

The VLMs are prompted to identify visible workers and assess safety helmets and high-visibility vests as **worn**, **missing**, or **unclear**. Model predictions are compared with manually checked ground-truth labels to calculate metrics such as accuracy, precision, recall, F1-score, prediction coverage, and processing time. These are experimental results, not proof of fitness for deployment in a safety-critical workplace.

Some tests also ask about boots, but footwear assessments should not be included in quantitative accuracy scores unless verified boot labels are available.

## Dataset attribution and licence

A portion of the evaluation images originated from:

- **Dataset:** Construction Site Safety — Version 30 (`raw-images_latestversion`)
- **Publisher / attribution:** Roboflow Universe Projects
- **Dataset page:** https://universe.roboflow.com/roboflow-universe-projects/construction-site-safety/dataset/30
- **Licence listed on the dataset page:** Creative Commons Attribution 4.0 International (**CC BY 4.0**)
- **Licence terms:** https://creativecommons.org/licenses/by/4.0/

The dataset is used here to evaluate pretrained VLMs for workplace PPE compliance. Ground-truth labels may have been manually reviewed or corrected for the evaluation task; those review labels are not official annotations provided by the dataset publisher. Where cropped, resized, annotated or otherwise altered copies are included, those files are adaptations of the source images.

**Important:** The CC BY 4.0 attribution above applies to the images originating from that Roboflow dataset, **not automatically to every file in `model testing images/`**. Other images, including independently sourced example photographs, may have different copyright or redistribution conditions. Check and credit each additional source before distributing its images publicly. The licence shown on the dataset page also does not independently verify the rights of every upstream image contributor.

## Running the notebooks

1. Open the repository folder in Visual Studio Code.
2. Select a Python environment with Jupyter and the required packages installed.
3. Open the evaluation notebook and update the model name, image folder, and ground-truth CSV path.
4. Run the cells in order, following the instructions within the notebook.
5. Review predictions and exported metrics in `ppe_model_results/`.

Local model testing uses Ollama. Some experiments may use an **authorised remote Ollama server**, allowing larger models to run without downloading their weights to the student's computer. Remote access and available model names depend on the server administrator. Do not publish API keys or other credentials, or upload private network details and sensitive workplace images without authorisation.

## Notes

- This is an academic prototype, not a certified workplace safety system.
- A suspected PPE violation should be verified by a person before being treated as a confirmed incident.
- Results from different models are only directly comparable when they use the same verified images, evaluation rules, and prompt.
- Please respect the applicable dataset and image licences when reusing or redistributing the files.
