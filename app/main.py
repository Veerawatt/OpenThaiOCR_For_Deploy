"""OpenThai OCR-Text as an HTTP service.

POST /ocr        upload an image (png/jpg/webp/bmp/tiff) or a PDF -> text + lines with boxes
GET  /health     liveness + model version
GET  /           small web page for trying it out
GET  /docs       OpenAPI docs
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/models/openthai-ocr")).resolve()
WORKERS = int(os.environ.get("OCR_WORKERS", "2"))          # one process per vCPU
API_KEY = os.environ.get("API_KEY", "").strip()             # empty = no auth
MAX_UPLOAD_MB = float(os.environ.get("MAX_UPLOAD_MB", "25"))
MAX_PDF_PAGES = int(os.environ.get("MAX_PDF_PAGES", "50"))
PDF_DPI = int(os.environ.get("PDF_DPI", "200"))
MAX_IMAGE_PIXELS = int(os.environ.get("MAX_IMAGE_PIXELS", str(60_000_000)))

# The model ships its runtime as a `runtime` package next to the weights.
# Spawned worker processes inherit sys.path, so this also covers them.
sys.path.insert(0, str(MODEL_DIR))
from runtime.line_engine import LineEngine  # noqa: E402

log = logging.getLogger("openthai-ocr")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

STATIC = Path(__file__).parent / "static"
MODEL_VERSION = (MODEL_DIR / "MODEL_VERSION").read_text().strip() if (MODEL_DIR / "MODEL_VERSION").exists() else "unknown"
engine: LineEngine | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global engine
    engine = LineEngine(str(MODEL_DIR), workers=WORKERS, threads=1)
    # Warm every worker so the first real request is not slow.
    warm = _blank_png()
    await asyncio.gather(*(engine.transcribe(warm) for _ in range(WORKERS)))
    log.info("model ready: %s, %d workers, auth=%s", MODEL_VERSION, WORKERS, "on" if API_KEY else "off")
    yield
    await engine.close()


app = FastAPI(title="OpenThai OCR-Text API", version="1.0", lifespan=lifespan)


def _blank_png() -> bytes:
    import cv2
    import numpy as np

    return cv2.imencode(".png", np.full((64, 256, 3), 255, np.uint8))[1].tobytes()


def require_key(x_api_key: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    if not API_KEY:
        return
    given = x_api_key or (authorization[7:] if authorization and authorization.lower().startswith("bearer ") else "")
    if not given or not secrets.compare_digest(given.encode(), API_KEY.encode()):
        raise HTTPException(401, "invalid or missing API key (send header X-API-Key)")


def _pdf_to_pngs(data: bytes, dpi: int, max_pages: int) -> list[bytes]:
    import cv2
    import numpy as np
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        raise HTTPException(400, f"cannot open PDF: {e}") from e
    try:
        n = len(pdf)
        if n > max_pages:
            raise HTTPException(413, f"PDF has {n} pages; the limit is {max_pages} (MAX_PDF_PAGES)")
        out = []
        for i in range(n):
            bitmap = pdf[i].render(scale=dpi / 72, grayscale=False)
            rgb = np.asarray(bitmap.to_pil().convert("RGB"))
            out.append(cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))[1].tobytes())
        return out
    finally:
        pdf.close()


def _check_image(data: bytes) -> None:
    import cv2
    import numpy as np

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_8)
    if img is None:
        raise HTTPException(415, "unsupported file: send an image (png, jpg, webp, bmp, tiff) or a PDF")
    if img.shape[0] * img.shape[1] * 64 > MAX_IMAGE_PIXELS:
        raise HTTPException(413, f"image too large (over {MAX_IMAGE_PIXELS:,} pixels)")


@app.get("/health")
async def health():
    return {"status": "ok" if engine else "starting", "model": MODEL_VERSION, "workers": WORKERS}


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC / "index.html")


@app.post("/ocr", dependencies=[Depends(require_key)])
async def ocr(
    file: UploadFile = File(..., description="image or PDF"),
    format: str = Query("json", pattern="^(json|text)$", description="json = text + lines/boxes, text = plain text"),
    dpi: int = Query(PDF_DPI, ge=72, le=400, description="PDF render resolution"),
):
    if engine is None:
        raise HTTPException(503, "model is still loading")
    data = await file.read(int(MAX_UPLOAD_MB * 1024 * 1024) + 1)
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"file over {MAX_UPLOAD_MB:g} MB (MAX_UPLOAD_MB)")
    if not data:
        raise HTTPException(400, "empty file")

    t0 = time.perf_counter()
    is_pdf = data[:5] == b"%PDF-"
    if is_pdf:
        images = await run_in_threadpool(_pdf_to_pngs, data, dpi, MAX_PDF_PAGES)
    else:
        await run_in_threadpool(_check_image, data)
        images = [data]

    try:
        results = await asyncio.gather(*(engine.transcribe(img) for img in images))
    except ValueError as e:
        raise HTTPException(415, str(e)) from e

    pages = [{"page": i + 1, "text": r["text"], "confidence": r["confidence"], "ms": r["ms"], "lines": r["lines"]}
             for i, r in enumerate(results)]
    text = "\n\n".join(p["text"] for p in pages)
    ms = round((time.perf_counter() - t0) * 1000)
    log.info("ocr %s: %d page(s), %d chars, %d ms", "pdf" if is_pdf else "image", len(pages), len(text), ms)

    if format == "text":
        return PlainTextResponse(text)
    return {"model": MODEL_VERSION, "filename": file.filename, "pages": len(pages), "ms": ms,
            "text": text, "results": pages}
