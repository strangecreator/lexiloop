#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Error: .env is missing. Copy .env.example to .env and configure production values first." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required (Python 3.10+)." >&2
  exit 1
fi
if ! python3 - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
then
  echo "Error: Python 3.10 or newer is required. Found: $(python3 --version 2>&1)" >&2
  exit 1
fi
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Error: Node.js 22.12+ LTS or 24 LTS and npm are required." >&2
  exit 1
fi
if ! node - <<'JS'
const [major, minor] = process.versions.node.split('.').map(Number)
process.exit(((major === 22 && minor >= 12) || major === 24) ? 0 : 1)
JS
then
  echo "Error: supported Node.js versions are 22.12+ LTS or 24.x LTS. Found: $(node --version)." >&2
  exit 1
fi

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/pip install -e vendor/tools -e vendor/router

(
  cd frontend
  rm -rf node_modules
  npm ci --registry=https://registry.npmjs.org --no-audit --no-fund --fetch-retries=2 --fetch-timeout=60000
  npm run build
)

(
  cd backend
  ../.venv/bin/python manage.py check --deploy
  ../.venv/bin/python manage.py migrate --noinput
  ../.venv/bin/python manage.py collectstatic --noinput
)

echo "Production build is ready. Start Gunicorn through systemd; see PRODUCTION_UBUNTU.md."
