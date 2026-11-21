"""Accuracy and latency numbers for the evaluation scripts and notebooks.

- **Plate accuracy**: the read equals the true plate exactly (after cleaning). What matters
  at a gate: a plate one character off is a wrong plate.
- **Character accuracy**: 1 - (edit distance / true length), floored at 0. Shows *how*
  wrong the misses are (one look-alike vs garbage), which guides fixes.
"""

import math
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from gatesense_anpr.normaliser import clean, edit_distance


def char_accuracy(predicted: str, truth: str) -> float:
    truth, predicted = clean(truth), clean(predicted)
    if not truth:
        return 1.0 if not predicted else 0.0
    return max(0.0, 1.0 - edit_distance(predicted, truth) / len(truth))


@dataclass(frozen=True)
class Sample:
    condition: str  # day, night, rain, angled, hsrp, two_wheeler…
    truth: str
    predicted: str  # "" when nothing was read
    latency_ms: float


@dataclass(frozen=True)
class Summary:
    condition: str
    samples: int
    plate_accuracy: float
    char_accuracy: float
    read_rate: float  # share of images where *something* was read
    mean_latency_ms: float


def summarise(samples: Iterable[Sample]) -> list[Summary]:
    """One row per condition, plus an 'all' row at the end."""
    groups: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        groups[sample.condition].append(sample)
        groups["all"].append(sample)
    rows = []
    for condition in sorted(groups, key=lambda c: (c == "all", c)):
        group = groups[condition]
        rows.append(
            Summary(
                condition=condition,
                samples=len(group),
                plate_accuracy=sum(clean(s.predicted) == clean(s.truth) for s in group)
                / len(group),
                char_accuracy=statistics.fmean(char_accuracy(s.predicted, s.truth) for s in group),
                read_rate=sum(bool(s.predicted) for s in group) / len(group),
                mean_latency_ms=statistics.fmean(s.latency_ms for s in group),
            )
        )
    return rows


def latency_stats(milliseconds: Sequence[float]) -> dict[str, float]:
    ordered = sorted(milliseconds)
    p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]  # nearest-rank percentile
    mean = statistics.fmean(ordered)
    return {
        "mean_ms": round(mean, 2),
        "p50_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(p95, 2),
        "fps": round(1000 / mean, 1),
    }


def markdown_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    def cell(value: object) -> str:
        return f"{value:.1%}" if isinstance(value, float) and 0 <= value <= 1 else str(value)

    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)
