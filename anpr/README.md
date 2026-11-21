# ANPR worker

Number-plate recognition service: YOLOv8 plate detector → OCR → normaliser → client that posts gate events to the API. Built in **Phase 3**.

Planned layout: `gatesense_anpr/` (package), `notebooks/` (Colab training and evaluation), `eval/` (scripts that write measured results to `eval/results/`), `tests/`.

Datasets and model weights **never go in git**. They will be downloaded by a documented script or from GitHub Releases.
