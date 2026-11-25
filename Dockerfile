FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# WeasyPrint (Pango/HarfBuzz), fonts with Latin + Cyrillic, Tesseract OCR languages.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 libffi8 \
        fonts-dejavu-core fonts-liberation2 fonts-noto-core \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-deu tesseract-ocr-ukr tesseract-ocr-rus \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
ARG INSTALL_DEV=false
RUN pip install -r requirements.txt && if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; fi

COPY . .

RUN useradd --create-home --uid 10001 copilot && mkdir -p /app/var && chown -R copilot /app/var
USER copilot

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fs http://localhost:8000/health || exit 1
CMD ["python", "-m", "app.main", "bot"]
