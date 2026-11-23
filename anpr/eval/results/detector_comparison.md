# Plate detector: YOLOv8n vs YOLOv8s

Data: public Kaggle datasets (CC0 / Apache 2.0), test set from a separate source; images per split {'train': 453, 'valid': 52, 'test': 354}.

| Source | Licence | Role | Images kept | Duplicates | Plate crops dropped |
|---|---|---|---|---|---|
| [deepakat002/indian-vehicle-number-plate-yolo-annotation](https://www.kaggle.com/datasets/deepakat002/indian-vehicle-number-plate-yolo-annotation) | CC0-1.0 | trainval | 160 | 0 | 0 |
| [kedarsai/indian-license-plates-with-labels](https://www.kaggle.com/datasets/kedarsai/indian-license-plates-with-labels) | CC0-1.0 | trainval | 183 | 919 | 919 |
| [tkm22092/indian-number-plate-images](https://www.kaggle.com/datasets/tkm22092/indian-number-plate-images) | CC0-1.0 | trainval | 115 | 0 | 0 |
| [dataclusterlabs/indian-number-plates-dataset](https://www.kaggle.com/datasets/dataclusterlabs/indian-number-plates-dataset) | CC0-1.0 | trainval | 47 | 0 | 0 |
| [paneraghanshyam/gujarat-vehicle-number-plates-yolo-ready](https://www.kaggle.com/datasets/paneraghanshyam/gujarat-vehicle-number-plates-yolo-ready) | Apache-2.0 | test | 354 | 1 | 0 |

Scored on the **test** split (a separate source, never used for training). 60 epochs max (early stop patience 15), image size 640, seed 0.
Trained on Tesla T4 (Kaggle, GPU T4 x2; one GPU used), 2026-11-23, in the notebook's saved version 3 (its output is kept on Kaggle). The first run (2026-11-22, an interactive session whose files expired) gave exactly the same scores: training is seeded. Notebook: `anpr/notebooks/01_train_plate_detector.ipynb`.

| Model | mAP50 | mAP50-95 | Precision | Recall | Val mAP50-95 | ONNX (MB) | Train (min) |
|---|---|---|---|---|---|---|---|
| yolov8n_plate | 0.745 | 0.384 | 0.667 | 0.866 | 0.598 | 12.8 | 9.8 |
| yolov8s_plate | 0.761 | 0.343 | 0.702 | 0.903 | 0.623 | 44.7 | 9.6 |

**Chosen:** yolov8n_plate: the larger model gains < 0.02 mAP50-95 (here it is lower on the test set), and the small one is ~3x faster on CPU. `plate_detector.onnx` SHA-256 `63e5d3e155b1456076c1438c82f969eab25b517b53c42a62dd384ad94de6a977`.

**Reading the numbers.** Validation (52 images from the training sources) is much higher than test (354 photos from Gujarat, a different source and camera): that gap is the honest cost of a new place. YOLOv8s finds a few more plates (recall 0.90 vs 0.87) but its boxes are less tight (lower mAP50-95), so the bigger model buys nothing here. With ~450 training images, more varied local data is the clear next step (`anpr/DATASET.md`).
