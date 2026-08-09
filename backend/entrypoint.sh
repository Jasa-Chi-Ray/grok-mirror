#!/bin/sh
set -e

mkdir -p /app/backend/logs /app/backend/db

python manage.py migrate --noinput
python cli/create_init_user.py

exec gunicorn app.wsgi:application \
  --bind 0.0.0.0:8100 \
  --workers "${GUNICORN_WORKERS:-3}" \
  --threads "${GUNICORN_THREADS:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-180}" \
  --access-logfile - \
  --error-logfile -
