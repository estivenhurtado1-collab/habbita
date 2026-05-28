#!/bin/sh
set -e
mkdir -p "$(dirname "$PROPINTEL_DB")"
exec uvicorn web.app:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1 \
  --limit-concurrency 8 \
  --timeout-keep-alive 120
