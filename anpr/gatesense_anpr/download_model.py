"""Download the trained plate detector from a GitHub Release.

Model weights never go in git (they're tens of MB). After training on Kaggle or Colab
(notebooks/01_train_plate_detector.ipynb), the owner uploads `plate_detector.onnx` to a
release of the repo, and everyone else runs:

    uv run python -m gatesense_anpr.download_model
    uv run python -m gatesense_anpr.download_model --tag models-v1 --sha256 <hash>

Releases we know about are checked against their SHA-256 automatically, so a corrupted or
swapped file is never installed.
"""

import argparse
import hashlib
import sys
from pathlib import Path

import httpx

from gatesense_anpr.config import ANPR_DIR

REPO = "Akinchan-Jain-7/GateSense"
DEFAULT_TAG = "models-v1"
ASSET = "plate_detector.onnx"
# SHA-256 of each published model, from the training run's detector_comparison.json.
KNOWN_SHA256 = {
    "models-v1": "63e5d3e155b1456076c1438c82f969eab25b517b53c42a62dd384ad94de6a977",
}


def release_url(tag: str, asset: str = ASSET, repo: str = REPO) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{asset}"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_hash(tag: str, url: str | None, given: str | None) -> str | None:
    """The hash to check: the one given, else the known hash for a release download."""
    if given:
        return given
    return None if url else KNOWN_SHA256.get(tag)


def download(url: str, target: Path, expected_sha256: str | None = None) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as response:
        response.raise_for_status()
        with partial.open("wb") as file:
            for chunk in response.iter_bytes():
                file.write(chunk)
    if expected_sha256 and sha256_of(partial) != expected_sha256.lower():
        partial.unlink()
        raise ValueError("Downloaded model doesn't match the expected SHA-256; not installed")
    partial.replace(target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download the plate detector model")
    parser.add_argument("--tag", default=DEFAULT_TAG)
    parser.add_argument("--url", help="download from this URL instead of the release")
    parser.add_argument("--sha256", help="expected SHA-256 of the file")
    parser.add_argument("--out", type=Path, default=ANPR_DIR / "models" / ASSET)
    args = parser.parse_args(argv)
    url = args.url or release_url(args.tag)
    path = download(url, args.out, expected_hash(args.tag, args.url, args.sha256))
    print(f"saved {path} (sha256 {sha256_of(path)})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
