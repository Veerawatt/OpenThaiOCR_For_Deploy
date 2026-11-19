"""Download OpenThai OCR-Text from Hugging Face at a pinned revision and verify SHA256SUMS.

Usage: python scripts/download_model.py --out ./models/openthai-ocr [--revision v2.1.4]
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

# The repo was renamed from iapp/OpenThai2.0-OCR-Text; the old name redirects here.
DEFAULT_REPO = "iapp/OpenThai2.1-OCR-Text-20261118"
DEFAULT_REVISION = "v2.1.4"
# Only what inference needs (skips the PyTorch training weights and the README).
PATTERNS = ["*.onnx", "det.yml", "rec_dict.txt", "config.json", "NOTICE", "SHA256SUMS",
            "requirements.txt", "runtime/*.py"]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--revision", default=DEFAULT_REVISION)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    out = Path(a.out)
    snapshot_download(a.repo, revision=a.revision, local_dir=out, allow_patterns=PATTERNS)

    sums = out / "SHA256SUMS"
    checked = 0
    for line in sums.read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        f = out / name.lstrip("./")
        if not f.exists():
            continue  # a file we chose not to download
        if sha256(f) != digest:
            print(f"SHA256 mismatch: {f}", file=sys.stderr)
            return 1
        checked += 1
    for need in ("det.onnx", "rec.onnx", "rec2.onnx", "rec_dict.txt", "config.json", "runtime/line_engine.py"):
        if not (out / need).exists():
            print(f"missing {need}", file=sys.stderr)
            return 1
    (out / "MODEL_VERSION").write_text(f"{a.repo}@{a.revision}\n")
    print(f"OK: {a.repo}@{a.revision} -> {out} ({checked} files verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
