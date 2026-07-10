#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[ -x .venv/bin/python ] || { echo 'Run ./scripts/bootstrap.sh first.'; exit 1; }
trap 'kill 0' EXIT INT TERM
(cd backend && ../.venv/bin/python manage.py runserver 127.0.0.1:8000) &
(cd backend && ../.venv/bin/python manage.py run_bulk_worker) &
(cd frontend && npm run dev) &
wait
