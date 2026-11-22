"""Median of the three runs written by bench.sh: throughput, latency percentiles, failures."""

import csv
import json
import statistics
import sys
from pathlib import Path

label = sys.argv[1]
runs = []
for i in (1, 2, 3):
    with Path(f"results/{label}-{i}_stats.csv").open() as f:
        row = next(r for r in csv.DictReader(f) if r["Name"] == "Aggregated")
    runs.append(row)


def median(key: str) -> float:
    return statistics.median(float(r[key]) for r in runs)


summary = {
    "label": label,
    "requests_per_second": round(median("Requests/s"), 1),
    "p50_ms": median("50%"),
    "p95_ms": median("95%"),
    "p99_ms": median("99%"),
    "failures": sum(int(r["Failure Count"]) for r in runs),
    "requests": sum(int(r["Request Count"]) for r in runs),
    "runs_rps": [round(float(r["Requests/s"]), 1) for r in runs],
}
Path(f"results/{label}.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
