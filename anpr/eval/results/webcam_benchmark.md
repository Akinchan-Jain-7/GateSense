# Synthetic webcam benchmark

`eval/webcam_benchmark.py`: 140 cars (20 plates x 7 conditions), 6 frames each, easyocr on CPU, seed 7. Rendered plates, not photos: compare settings here, and use labelled webcam photos for real accuracy (see the script's docstring).

## Settings (all conditions)

| Setting | What changes | Frame exact | Car exact | Car after server repair | ms / read |
|---|---|---|---|---|---|
| baseline | Before: 5% margin, upscale to 64 px, whole-string votes | 65.1% | 68.6% | 80.0% | 233.5 |
| margin | + 12% margin around the box | 63.9% | 68.6% | 78.6% | 260.8 |
| upscale | + upscale to 96 px | 65.7% | 70.7% | 81.4% | 266.5 |
| contrast | + grey and CLAHE contrast | 67.7% | 71.4% | 80.7% | 436.0 * |
| chars | + per-character voting across frames | 67.7% | 72.1% | 80.7% | 264.2 |
| chars-no-contrast | margin + upscale + per-character voting | 65.7% | 69.3% | 80.0% | 273.0 |

\* measured while another job shared the 2-core CPU; the other runs had it to themselves.

## `baseline` per condition

| Condition | Frame exact | Car exact | Car after server repair | Character accuracy |
|---|---|---|---|---|
| clear | 74.2% | 75.0% | 90.0% | 97.4% |
| all | 65.1% | 68.6% | 80.0% | 95.7% |
| small | 60.0% | 70.0% | 80.0% | 95.9% |
| blurry | 58.3% | 65.0% | 70.0% | 94.8% |
| tilted | 51.7% | 50.0% | 70.0% | 92.3% |
| dim | 68.3% | 75.0% | 85.0% | 96.4% |
| glare | 67.5% | 70.0% | 80.0% | 95.8% |
| phone | 75.8% | 75.0% | 85.0% | 97.4% |

## `margin` per condition

| Condition | Frame exact | Car exact | Car after server repair | Character accuracy |
|---|---|---|---|---|
| clear | 72.5% | 75.0% | 90.0% | 96.9% |
| all | 63.9% | 68.6% | 78.6% | 95.3% |
| small | 56.7% | 70.0% | 75.0% | 95.8% |
| blurry | 56.7% | 60.0% | 65.0% | 93.8% |
| tilted | 51.7% | 55.0% | 75.0% | 94.8% |
| dim | 68.3% | 75.0% | 80.0% | 96.8% |
| glare | 67.5% | 70.0% | 80.0% | 95.9% |
| phone | 74.2% | 75.0% | 85.0% | 92.9% |

## `upscale` per condition

| Condition | Frame exact | Car exact | Car after server repair | Character accuracy |
|---|---|---|---|---|
| clear | 72.5% | 75.0% | 90.0% | 96.9% |
| all | 65.7% | 70.7% | 81.4% | 95.4% |
| small | 61.7% | 80.0% | 85.0% | 96.3% |
| blurry | 59.2% | 60.0% | 70.0% | 94.3% |
| tilted | 55.0% | 55.0% | 75.0% | 94.2% |
| dim | 70.0% | 80.0% | 85.0% | 97.4% |
| glare | 67.5% | 70.0% | 80.0% | 95.9% |
| phone | 74.2% | 75.0% | 85.0% | 92.9% |

## `contrast` per condition

| Condition | Frame exact | Car exact | Car after server repair | Character accuracy |
|---|---|---|---|---|
| clear | 76.7% | 80.0% | 90.0% | 97.4% |
| all | 67.7% | 71.4% | 80.7% | 96.2% |
| small | 60.8% | 75.0% | 80.0% | 95.3% |
| blurry | 66.7% | 60.0% | 65.0% | 94.8% |
| tilted | 60.0% | 60.0% | 75.0% | 94.8% |
| dim | 70.0% | 80.0% | 90.0% | 97.4% |
| glare | 70.0% | 70.0% | 80.0% | 96.3% |
| phone | 70.0% | 75.0% | 85.0% | 97.4% |

## `chars` per condition

| Condition | Frame exact | Car exact | Car after server repair | Character accuracy |
|---|---|---|---|---|
| clear | 76.7% | 75.0% | 90.0% | 96.9% |
| all | 67.7% | 72.1% | 80.7% | 96.5% |
| small | 60.8% | 75.0% | 80.0% | 95.3% |
| blurry | 66.7% | 65.0% | 65.0% | 96.3% |
| tilted | 60.0% | 70.0% | 80.0% | 96.4% |
| dim | 70.0% | 75.0% | 85.0% | 96.9% |
| glare | 70.0% | 70.0% | 80.0% | 96.3% |
| phone | 70.0% | 75.0% | 85.0% | 97.4% |

## `chars-no-contrast` per condition

| Condition | Frame exact | Car exact | Car after server repair | Character accuracy |
|---|---|---|---|---|
| clear | 72.5% | 80.0% | 90.0% | 97.4% |
| all | 65.7% | 69.3% | 80.0% | 95.4% |
| small | 61.7% | 75.0% | 85.0% | 95.8% |
| blurry | 59.2% | 55.0% | 65.0% | 93.8% |
| tilted | 55.0% | 55.0% | 75.0% | 94.3% |
| dim | 70.0% | 75.0% | 80.0% | 96.8% |
| glare | 67.5% | 70.0% | 80.0% | 96.3% |
| phone | 74.2% | 75.0% | 85.0% | 93.4% |
