#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

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
  echo "Error: Node.js and npm are required. Install Node.js 22 LTS or 24 LTS." >&2
  exit 1
fi

if ! node - <<'JS'
const [major, minor] = process.versions.node.split('.').map(Number)
const supported = (major === 22 && minor >= 12) || major === 24
process.exit(supported ? 0 : 1)
JS
then
  echo "Error: supported Node.js versions are 22.12+ LTS or 24.x LTS." >&2
  echo "Found: Node $(node --version), npm $(npm --version)." >&2
  echo "Node 26 is a Current release and is intentionally not used for this project yet." >&2
  exit 1
fi

[ -f .env ] || cp .env.example .env
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r backend/requirements-dev.txt
.venv/bin/pip install -e vendor/tools -e vendor/router

echo "Installing frontend packages from the public npm registry..."
(
  cd frontend
  rm -rf node_modules
  npm ci \
    --registry=https://registry.npmjs.org \
    --no-audit \
    --no-fund \
    --fetch-retries=2 \
    --fetch-timeout=60000
)

(cd backend && ../.venv/bin/python manage.py migrate --noinput)
(cd frontend && npm run build)
echo "LexiLoop is ready. Run: ./scripts/dev.sh"
