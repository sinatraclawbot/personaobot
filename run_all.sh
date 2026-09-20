#!/bin/sh
# PersonaAI consolidated entrypoint: web + worker + maintenance share one disk.
set -e

# Apply pending schema migrations before any process starts.
alembic upgrade head

# Background sidecars share this service's persistent /var/data volume for media.
python -m app.worker &
python -m app.maintenance &

# WhatsApp Web sidecar (only when enabled).
if [ "${WHATSAPP_ENABLED:-false}" = "true" ]; then
  node whatsapp/sidecar.js &
fi

# uvicorn is the foreground process and owns Render's PORT.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log --no-proxy-headers