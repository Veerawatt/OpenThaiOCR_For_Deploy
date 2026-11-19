FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Model weights + runtime, pinned and checksum-verified at build time.
ARG MODEL_REPO=iapp/OpenThai2.1-OCR-Text-20261118
ARG MODEL_REVISION=v2.1.4
ENV MODEL_DIR=/models/openthai-ocr \
    PYTHONPATH=/models/openthai-ocr
COPY scripts/download_model.py /tmp/download_model.py
RUN python /tmp/download_model.py --repo "$MODEL_REPO" --revision "$MODEL_REVISION" --out "$MODEL_DIR" \
 && rm -rf /root/.cache /tmp/download_model.py "$MODEL_DIR/.cache"

COPY app ./app

RUN useradd --system --uid 10001 ocr
USER ocr

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
