#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
(cd backend && ../.venv/bin/python manage.py check && ../.venv/bin/python manage.py makemigrations --check --dry-run && ../.venv/bin/python manage.py test learning.tests)
(cd frontend && npm run build)
(cd vendor/router && ../../.venv/bin/pytest -q)
(cd vendor/tools && ../../.venv/bin/pytest -q)
.venv/bin/python -m compileall -q backend vendor/tools/src vendor/router/src
echo 'All executable checks passed (router provider tests are skipped by the supplied test module).'
