"""Run OpenThai OCR-Text directly on this machine — no server, no internet.

  python ocr_local.py page.jpg                 print the text
  python ocr_local.py doc.pdf scans/ -o out/   write one .txt per file (folders are scanned)
  python ocr_local.py page.png --json          text + boxes + confidence as JSON

Model files: models/openthai-ocr (get them with scripts/download_model.py --out models/openthai-ocr).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_DIR = Path(os.environ.get("MODEL_DIR", HERE / "models" / "openthai-ocr")).resolve()
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

sys.path.insert(0, str(MODEL_DIR))
from runtime.line_engine import LineOCR  # noqa: E402


def pdf_pages(path: Path, dpi: int):
    import numpy as np
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        for i in range(len(pdf)):
            rgb = np.asarray(pdf[i].render(scale=dpi / 72).to_pil().convert("RGB"))
            yield np.ascontiguousarray(rgb[:, :, ::-1])  # RGB -> BGR
    finally:
        pdf.close()


def collect(inputs: list[str]) -> list[Path]:
    files = []
    for s in inputs:
        p = Path(s)
        if p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.suffix.lower() in IMAGE_EXT | {".pdf"})
        elif p.exists():
            files.append(p)
        else:
            print(f"not found: {p}", file=sys.stderr)
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenThai OCR-Text, local")
    ap.add_argument("inputs", nargs="+", help="images, PDFs or folders")
    ap.add_argument("-o", "--out", help="folder for .txt (or .json) results; default: print")
    ap.add_argument("--json", action="store_true", help="output text + lines/boxes/confidence as JSON")
    ap.add_argument("--dpi", type=int, default=200, help="PDF render resolution (default 200)")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--paragraphs", action="store_true", help="blank line between paragraphs")
    a = ap.parse_args()

    files = collect(a.inputs)
    if not files:
        return 1
    over = {"join": {"paragraphs": True}} if a.paragraphs else {}
    ocr = LineOCR(MODEL_DIR, threads=a.threads, **over)
    out = Path(a.out) if a.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)

    for f in files:
        t0 = time.perf_counter()
        sources = pdf_pages(f, a.dpi) if f.suffix.lower() == ".pdf" else [str(f)]
        pages = []
        for i, img in enumerate(sources, 1):
            r = ocr.read(img)
            pages.append({"page": i, "text": r["text"], "lines": r["lines"]})
        text = "\n\n".join(p["text"] for p in pages)
        took = time.perf_counter() - t0
        body = json.dumps({"file": str(f), "text": text, "pages": pages}, ensure_ascii=False, indent=1) if a.json else text

        if out:
            dest = out / (f.name + (".json" if a.json else ".txt"))  # page.pdf -> page.pdf.txt
            dest.write_text(body + "\n", encoding="utf-8")
            print(f"{f} -> {dest}  ({len(pages)} page(s), {took:.2f}s)", file=sys.stderr)
        else:
            if len(files) > 1:
                print(f"===== {f} =====")
            print(body)
            print(f"[{len(pages)} page(s), {took:.2f}s]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
