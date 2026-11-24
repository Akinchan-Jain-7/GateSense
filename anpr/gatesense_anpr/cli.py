"""Command line entry point.

    gatesense-anpr --source videos/gate.mp4            # a recording
    gatesense-anpr --source 0                          # first USB webcam
    gatesense-anpr --source rtsp://user:pass@cam/stream
    gatesense-anpr --source photos/                    # a folder of images
    gatesense-anpr --simulate 20                       # fake reads, no camera or model
    gatesense-anpr --source 0 --preview                # webcam + live page (demos)
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
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import SecretStr

from gatesense_anpr.buffer import BufferedSender, OfflineBuffer
from gatesense_anpr.client import GateEventClient, GateEventRejectedError
from gatesense_anpr.config import AnprSettings
from gatesense_anpr.models import PlateRead

if TYPE_CHECKING:
    from gatesense_anpr.pipeline import Pipeline

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
    parser.add_argument(
        "--preview",
        action="store_true",
        help="--source: show the camera and each decision on a local web page",
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="--preview: don't open the page by itself"
    )
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


def print_result(read: PlateRead, result: dict[str, object]) -> None:
    event = result.get("event")
    event = event if isinstance(event, dict) else {}
    print(
        f"{read.plate_text:<12} -> {result.get('status')!s:<9} "
        f"{event.get('plate_normalized')} {event.get('match_result')}",
        flush=True,
    )


type ResultCallback = Callable[[PlateRead, dict[str, Any]], None]
type RejectCallback = Callable[[PlateRead, GateEventRejectedError], None]


class Sink:
    """Where reads go: printed (--dry-run), sent directly, or sent through the buffer.

    Calling it returns what happened to the read: "printed", "sent", "buffered" (kept for
    later, the API is unreachable) or "rejected" (the API refused it for good).
    """

    def __init__(
        self,
        deliver: Callable[[PlateRead], str],
        finish: Callable[[], None],
        poll: Callable[[], None] = lambda: None,
    ) -> None:
        self.deliver = deliver
        self.finish = finish
        # Called now and then while no new reads arrive: retries buffered reads.
        self.poll = poll

    def __call__(self, read: PlateRead) -> str:
        return self.deliver(read)


def build_sink(
    args: argparse.Namespace,
    settings: AnprSettings,
    *,
    device_key: SecretStr | None = None,
    buffer_path: Path | None | Literal["default"] = "default",
    on_result: ResultCallback | None = None,
    on_rejected: RejectCallback | None = None,
) -> Sink:
    """`device_key` / `buffer_path` override the settings (the preview's exit lane uses
    its own key and its own buffer file, so a queued read can't replay on the wrong lane).
    `on_result` also gets every API reply, including reads replayed from the buffer, and
    `on_rejected` every read the API refused for good."""
    if args.dry_run:

        def dry(read: PlateRead) -> str:
            print(describe(read), flush=True)
            return "printed"

        return Sink(dry, lambda: None)
    key = device_key or settings.device_key
    if key is None:
        raise SystemExit("Set ANPR_DEVICE_KEY (the camera's device key) or use --dry-run.")
    path = settings.buffer_path if buffer_path == "default" else buffer_path
    client = GateEventClient(
        settings.api_url,
        key.get_secret_value(),
        timeout=settings.request_timeout_seconds,
        max_retries=settings.max_retries,
    )

    def sent(read: PlateRead, result: dict[str, Any]) -> None:
        print_result(read, result)
        if on_result:
            on_result(read, result)

    if path is None or str(path) == "":

        def send(read: PlateRead) -> str:
            try:
                sent(read, client.send(read))
            except GateEventRejectedError as exc:
                logger.error("%s", exc)
                if on_rejected:
                    on_rejected(read, exc)
                return "rejected"
            return "sent"

        return Sink(send, client.close)

    buffer = OfflineBuffer(path)
    sender = BufferedSender(client, buffer, on_sent=sent, on_rejected=on_rejected)
    if len(buffer):
        logger.info("%d read(s) waiting from last time; sending them first", len(buffer))
        sender.flush(force=True)

    def finish() -> None:
        left = sender.flush(force=True).remaining
        if left:
            logger.warning(
                "%d read(s) still waiting in %s; they are sent on the next run",
                left,
                path,
            )
        buffer.close()
        client.close()

    def deliver(read: PlateRead) -> str:
        return sender.send(read)

    def poll() -> None:
        if len(buffer):
            sender.flush()  # respects the backoff, so this is cheap while offline

    return Sink(deliver, finish, poll)


def build_pipeline(settings: AnprSettings) -> "Pipeline":
    from gatesense_anpr.detector import PlateDetector
    from gatesense_anpr.ocr import build_engine
    from gatesense_anpr.pipeline import Pipeline
    from gatesense_anpr.tracker import PlateTracker

    if not settings.detector_model.exists():
        raise SystemExit(
            f"No plate detector at {settings.detector_model}. "
            "Get it with: uv run python -m gatesense_anpr.download_model"
        )
    return Pipeline(
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


def reads_from_source(spec: str, settings: AnprSettings) -> Iterable[PlateRead]:
    from gatesense_anpr.sources import is_folder, open_source

    pipeline = build_pipeline(settings)
    folder = is_folder(spec)
    for frame in open_source(spec, settings.sample_fps):
        yield from pipeline.process(frame)
        if folder:  # each photo is its own sighting
            yield from pipeline.finish()
    yield from pipeline.finish()


def exit_buffer_path(path: Path | None) -> Path | None:
    """The exit lane's own offline buffer, next to the entry lane's."""
    if path is None or str(path) == "":
        return None
    return path.with_name(f"{path.stem}-exit{path.suffix}")


def preview(args: argparse.Namespace, settings: AnprSettings) -> int:
    from gatesense_anpr.live import Lane, LiveState, Mode, run_preview
    from gatesense_anpr.sources import is_folder, is_live, open_capture

    spec = args.source
    if is_folder(spec):
        raise SystemExit("--preview needs a camera or a video, not a folder of photos.")
    if not is_live(spec) and not Path(spec).exists():
        raise SystemExit(f"No such video file: {spec}")
    two_lanes = args.dry_run or settings.exit_device_key is not None
    if not two_lanes:
        logger.info("ANPR_EXIT_DEVICE_KEY isn't set: the preview works as an entry camera only")
    modes: tuple[Mode, ...] = ("entry", "exit") if two_lanes else ("entry",)
    state = LiveState(modes=modes, console_url=settings.console_url, source=spec)

    def callbacks(mode: Mode) -> dict[str, Any]:
        return {
            "on_result": lambda read, result: state.record_result(read, mode, result),
            "on_rejected": lambda read, error: state.record_rejection(
                read, mode, error.status_code, error.detail
            ),
        }

    sinks: dict[Mode, Sink] = {"entry": build_sink(args, settings, **callbacks("entry"))}
    if "exit" in modes:
        sinks["exit"] = (
            sinks["entry"]  # dry run: nothing is sent, one printer is enough
            if args.dry_run
            else build_sink(
                args,
                settings,
                device_key=settings.exit_device_key,
                buffer_path=exit_buffer_path(settings.buffer_path),
                **callbacks("exit"),
            )
        )
    pipeline = build_pipeline(settings)
    try:
        run_preview(
            state,
            pipeline=pipeline,
            lanes={mode: Lane(send=sink, poll=sink.poll) for mode, sink in sinks.items()},
            open_capture=lambda: open_capture(
                spec, width=settings.camera_width, height=settings.camera_height
            ),
            live=is_live(spec),
            sample_fps=settings.sample_fps,
            host=settings.preview_host,
            port=settings.preview_port,
            open_browser=not args.no_browser,
        )
    finally:
        for sink in {id(s): s for s in sinks.values()}.values():
            sink.finish()
    return 0


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
        sink.finish()
        return 0

    if args.preview:
        return preview(args, settings)

    count = 0
    for read in reads_from_source(args.source, settings):
        sink(read)
        count += 1
    sink.finish()
    logger.info("done: %d plate(s)", count)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
