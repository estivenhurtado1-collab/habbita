# Habitta ia — imagen con Playwright para scraping
FROM mcr.microsoft.com/playwright/python:v1.60.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    PROPINTEL_DB=/data/propintel.db \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

RUN mkdir -p /data

EXPOSE 8000

CMD ["sh", "scripts/start.sh"]
