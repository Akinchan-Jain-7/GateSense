# Plate detector latency on CPU

Full `detect()` call on a 1280x720 frame (letterbox + model + NMS), 100 runs after 5 warm-up runs, one thread pool per process (ONNX Runtime defaults).

| Model | Precision | Size (MB) | Mean (ms) | p50 (ms) | p95 (ms) | FPS |
|---|---|---|---|---|---|---|
| yolov8n_plate | FP32 | 12.2 | 65.24 | 64.1 | 68.01 | 15.3 |
| yolov8n_plate | INT8 dynamic | 3.3 | 87.77 | 87.69 | 89.36 | 11.4 |
| yolov8n_plate | INT8 static | 3.4 | 32.35 | 32.25 | 32.95 | 30.9 |
| yolov8s_plate | FP32 | 44.7 | 194.1 | 193.92 | 213.02 | 5.2 |
| yolov8s_plate | INT8 dynamic | 11.5 | 283.43 | 289.67 | 295.23 | 3.5 |
| yolov8s_plate | INT8 static | 11.5 | 76.26 | 76.59 | 77.7 | 13.1 |

Machine: x86_64, 2 cores, Linux-6.18.44-fc-v726-x86_64-with-glibc2.39, Python 3.12.3. Measured 2026-11-21T23:23:02+00:00.

Note: Untrained 1-class YOLOv8n/s: the same architecture and size as the trained plate model, and latency doesn't depend on the weights. INT8 static was calibrated on random frames, which is fine for speed; accuracy needs real photos (--calibration-images). Measured on the 2-core cloud build machine, not the owner's laptop or gate hardware: rerun there with the trained model.
