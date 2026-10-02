#!/bin/sh
set -e

case "$1" in
  api)
    alembic upgrade head
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
    ;;
  worker)
    exec celery -A app.workers.celery_app worker --loglevel=INFO -Q default,publishing,inbox --concurrency="${CELERY_CONCURRENCY:-4}"
    ;;
  beat)
    exec celery -A app.workers.celery_app beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  test)
    exec python -m pytest -q
    ;;
  *)
    exec "$@"
    ;;
esac
