# Datasets and your own photos

## Public data (used by default)

`notebooks/01_train_plate_detector.ipynb` downloads a public Indian number-plate detection
dataset from **Roboflow Universe** (CC BY 4.0, YOLO format) with a free API key kept in
Colab Secrets. Any YOLO-format plate dataset works: change `ROBOFLOW_WORKSPACE`,
`ROBOFLOW_PROJECT` in the notebook. A large alternative is **NPDS** on Mendeley Data
(19,309 Indian plate images, COCO format; doi:10.17632/sxrnr7hwtk.1). Export or convert it
to YOLO format before using it.

These downloads are blocked from the build machine, which is why training runs in Colab.

## Your own photos (makes the model good *at your gate*)

Public datasets are mostly daytime, front-on, mobile-phone shots. A gate camera sees
night IR, rain, glare, angles and two-wheelers. Even a few hundred of your own photos help.

### Collecting

- Photos of parked or passing vehicles from roughly where a gate camera would be (2–3 m
  high, 3–6 m away, some angle). Phone photos are fine; also take some frames from a video.
- Aim for **at least 50 per condition** for evaluation, and **300+ total** for fine-tuning.
- Privacy: plates are personal data. Photograph your own society's or friends' vehicles with
  permission, keep the photos on your Google Drive, and **never commit them to git**.

| Condition folder | What it means |
|---|---|
| `day/` | daylight, plate clearly visible |
| `night/` | street light, headlights or IR camera |
| `rain/` | wet lens, rain, fog or dust |
| `angled/` | plate at more than ~30° to the camera |
| `hsrp/` | high-security registration plates (IND hologram, the newer font) |
| `two_wheeler/` | scooters and bikes, often 2-line plates |

### Layout on Google Drive

```
gatesense/
├── detector_dataset/          # for notebook 01 (DATASET_SOURCE = "drive")
│   ├── train/images/*.jpg   train/labels/*.txt
│   ├── valid/images/*.jpg   valid/labels/*.txt
│   └── test/images/*.jpg    test/labels/*.txt      (optional but recommended)
├── ocr_eval/                  # for notebook 02 and eval/evaluate_pipeline.py
│   ├── labels.csv
│   ├── day/0001.jpg …
│   ├── night/0001.jpg …
│   └── …
└── plate_detector.onnx        # copied here after notebook 01
```

### Labelling boxes (detector)

1. Create a free project on roboflow.com (*Object Detection*), upload the photos.
2. Draw one tight box around each plate, class name `plate`. Include partly visible
   plates if a human could still read them; skip unreadable blurs.
3. Generate a version with a 70/20/10 train/valid/test split, no augmentations (YOLO
   adds its own), and export as **YOLOv8**. Unzip into `detector_dataset/`.

Each `labels/*.txt` line is `0 cx cy w h`, values 0–1 relative to the image size.
(CVAT or Label Studio work too; export "YOLO 1.1".)

### Labelling text (OCR evaluation)

`ocr_eval/labels.csv`, one row per photo:

```csv
file,plate,condition
day/0001.jpg,DL01AB1234,day
night/0007.jpg,DL3CAS0042,night
two_wheeler/0003.jpg,UP16Z5678,two_wheeler
```

- `plate`: exactly as on the plate, no spaces, upper case. Skip the "IND" mark.
- Two-line plates: top line then bottom line (`UP16Z` + `5678` → `UP16Z5678`).
- Keep evaluation photos **out of** the detector's training set, or the scores flatter it.

### Quick start: label with the webcam

The live preview (`gatesense-anpr --source 0 --preview`) has a **Save for testing** panel:
it saves the current frame and the plate you type straight into this layout under
`anpr/data/eval/webcam/` (conditions: `phone`, `printed`, `car`, `dim`, `angled`). See
[docs/webcam-demo.md](../docs/webcam-demo.md#measure-the-real-reading-accuracy).
