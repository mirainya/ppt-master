FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/home/pptmaster \
    CODEX_HOME=/home/pptmaster/.codex

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        fontconfig \
        fonts-liberation2 \
        fonts-noto-cjk \
        fonts-noto-color-emoji \
        libreoffice-impress \
        libreoffice-writer \
        pandoc \
        poppler-utils \
        unzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY service/requirements.lock /app/service/requirements.lock
RUN python -m pip install --require-hashes -r /app/service/requirements.lock

RUN python -m playwright install --with-deps chromium \
    && chmod -R a+rX "${PLAYWRIGHT_BROWSERS_PATH}" \
    && fc-cache -f

COPY AGENTS.md LICENSE /app/
COPY database /app/database
COPY docs/assets/screenshots /app/docs/assets/screenshots
COPY service /app/service
COPY skills/ppt-master /app/skills/ppt-master

RUN useradd --create-home --uid 10001 pptmaster \
    && mkdir -p /app/runtime/jobs "${CODEX_HOME}" \
    && chown -R pptmaster:pptmaster /app/runtime /home/pptmaster

USER pptmaster

RUN python -c "import importlib.metadata; print('openai-codex', importlib.metadata.version('openai-codex'))" \
    && soffice --headless --version \
    && pdftoppm -v \
    && fc-match "Noto Sans CJK SC"

RUN python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(headless=True); b.close(); p.stop()"

EXPOSE 8000

CMD ["uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8000"]
