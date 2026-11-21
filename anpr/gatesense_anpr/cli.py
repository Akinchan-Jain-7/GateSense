"""Command line entry point.

    gatesense-anpr --source videos/gate.mp4            # a recording
    gatesense-anpr --source 0                          # first USB webcam
    gatesense-anpr --source rtsp://user:pass@cam/stream
    gatesense-anpr --source photos/                    # a folder of images
    gatesense-anpr --simulate 20                       # fake reads, no camera or model
    add --dry-run to print reads instead of sending them

Settings (API URL, device key, model path, OCR engine…) come from ANPR_* environment
variables or a .env file; see gatesense_anpr/config.py.
"""

import argparse
import json
import logging
import sys
import time
from collections.abc import Callable, Iterable

from gatesense_anpr.client import GateEventClient, GateEventRejectedError
from gatesense_anpr.config import AnprSettings
from gatesense_anpr.models import PlateRead

logger = logging.getLogger("gatesense_anpr")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="gatesense-anpr", description=__doc__.split("\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source", help="camera index, RTSP/HTTP URL, video file or folder")
    mode.add_argument("--simulate", type=int, metavar="N", help="send N simulated reads")
    parser.add_argument("--plates", help="comma-separated plates for --simulate")
    parser.add_argument(
        "--interval", type=float, default=2.0, help="seconds between simulated reads"
    )
    parser.add_argument(
        "--realtime", action="store_true", help="--simulate: wait --interval between reads"
    )
    parser.add_argument("--dry-run", action="store_true", help="print reads, don't send them")
    parser.add_argument("--seed", type=int, help="random seed for --simulate")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def describe(read: PlateRead) -> str:
    return json.dumps(
        {
            "plate_text": read.plate_text,
            "confidence": read.confidence,
            "captured_at": read.captured_at.isoformat(),
            "votes": read.votes,
            "raw_texts": list(read.raw_texts),
            "snapshot_bytes": len(read.snapshot_jpeg or b""),
        }
    )


def build_sink(args: argparse.Namespace, settings: AnprSettings) -> Callable[[PlateRead], None]:
    if args.dry_run:
        return lambda read: print(describe(read), flush=True)
    if settings.device_key is None:
        raise SystemExit("Set ANPR_DEVICE_KEY (the camera's device key) or use --dry-run.")
    client = GateEventClient(
        settings.api_url,
        settings.device_key.get_secret_value(),
        timeout=settings.request_timeout_seconds,
        max_retries=settings.max_retries,
    )

    def send(read: PlateRead) -> None:
        try:
            result = client.send(read)
        except GateEventRejectedError as exc:
            logger.error("%s", exc)
            return
        event = result.get("event") or {}
        print(
            f"{read.plate_text:<12} -> {result['status']:<9} "
            f"{event.get('plate_normalized')} {event.get('match_result')}",
            flush=True,
        )

    return send


def reads_from_source(spec: str, settings: AnprSettings) -> Iterable[PlateRead]:
    from gatesense_anpr.detector import PlateDetector
    from gatesense_anpr.ocr import build_engine
    from gatesense_anpr.pipeline import Pipeline
    from gatesense_anpr.sources import is_folder, open_source
    from gatesense_anpr.tracker import PlateTracker

    pipeline = Pipeline(
        PlateDetector(
            settings.detector_model,
            input_size=settings.detector_input_size,
            confidence=settings.detector_confidence,
            iou_threshold=settings.detector_iou,
        ),
        build_engine(settings.ocr_engine),
        PlateTracker(
            gap_seconds=settings.track_gap_seconds,
            min_agreeing_reads=settings.track_min_agreeing_reads,
        ),
    )
    folder = is_folder(spec)
    for frame in open_source(spec, settings.sample_fps):
        yield from pipeline.process(frame)
        if folder:  # each photo is its own sighting
            yield from pipeline.finish()
    yield from pipeline.finish()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = AnprSettings()
    sink = build_sink(args, settings)

    if args.simulate is not None:
        from gatesense_anpr.simulate import DEFAULT_PLATES, simulated_reads

        plates = [p.strip() for p in args.plates.split(",")] if args.plates else DEFAULT_PLATES
        for read in simulated_reads(
            args.simulate, plates=plates, interval_seconds=args.interval, seed=args.seed
        ):
            sink(read)
            if args.realtime:
                time.sleep(args.interval)
        return 0

    count = 0
    for read in reads_from_source(args.source, settings):
        sink(read)
        count += 1
    logger.info("done: %d plate(s)", count)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
