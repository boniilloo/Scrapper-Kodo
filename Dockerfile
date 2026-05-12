# Official Playwright image: ships Python 3.12 + Chromium + every OS dep
# pre-installed. Pin to the matching Playwright version.
FROM mcr.microsoft.com/playwright/python:v1.59.0-noble

WORKDIR /app

# Install Python deps first so the layer is cached when only code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code.
COPY scrape_kodo.py app.py ./

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MAX_CONCURRENCY=2 \
    SCRAPE_TIMEOUT_MS=60000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
