#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export DEBUG=0

[ -x .venv/bin/python ] || { echo 'Run ./scripts/bootstrap-production.sh first.' >&2; exit 1; }

(cd frontend && npm ci --registry=https://registry.npmjs.org --no-audit --no-fund && npm run build)
(cd backend && ../.venv/bin/python manage.py migrate --noinput && ../.venv/bin/python manage.py collectstatic --noinput)

trap 'kill 0' EXIT INT TERM
(cd backend && ../.venv/bin/python manage.py run_bulk_worker) &
(cd backend && exec ../.venv/bin/gunicorn config.wsgi:application \
  --bind "${BIND:-127.0.0.1:8000}" \
  --workers "${WORKERS:-3}" \
  --timeout "${GUNICORN_TIMEOUT:-180}" \
  --access-logfile - \
  --error-logfile -) &
wait -n
