#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${LEXILOOP_APP_DIR:-/opt/lexiloop}"
SERVICE="${LEXILOOP_SERVICE:-lexiloop}"
BULK_SERVICE="${LEXILOOP_BULK_SERVICE:-lexiloop-bulk}"
BULK_UNIT="/etc/systemd/system/$BULK_SERVICE.service"
APP_USER="${LEXILOOP_USER:-lexiloop}"
APP_GROUP="${LEXILOOP_GROUP:-lexiloop}"
BACKUP_ROOT="${LEXILOOP_BACKUP_DIR:-/var/backups/lexiloop/releases}"
RELEASE_ZIP="${1:-}"

if [[ ${EUID} -ne 0 ]]; then
  echo "Error: run this updater as root (sudo)." >&2
  exit 1
fi
if [[ -z "$RELEASE_ZIP" || ! -f "$RELEASE_ZIP" ]]; then
  echo "Usage: sudo $0 /root/LexiLoop_AI_Flashcards_vX.Y.Z.zip" >&2
  exit 1
fi
for command in unzip rsync systemctl python3; do
  command -v "$command" >/dev/null 2>&1 || { echo "Error: missing command: $command" >&2; exit 1; }
done
[[ -d "$APP_DIR" ]] || { echo "Error: application directory not found: $APP_DIR" >&2; exit 1; }
[[ -f "$APP_DIR/.env" ]] || { echo "Error: persistent file is missing: $APP_DIR/.env" >&2; exit 1; }

read_database_url() {
  "$APP_DIR/.venv/bin/python" - "$APP_DIR/.env" <<'PYDB'
from dotenv import dotenv_values
import sys
print(dotenv_values(sys.argv[1]).get('DATABASE_URL') or '')
PYDB
}
DATABASE_URL_VALUE="$(read_database_url)"
DATABASE_KIND="sqlite"
if [[ "$DATABASE_URL_VALUE" == postgres* ]]; then
  DATABASE_KIND="postgres"
  for command in pg_dump pg_restore; do
    command -v "$command" >/dev/null 2>&1 || { echo "Error: PostgreSQL deployment requires $command (install postgresql-client)." >&2; exit 1; }
  done
fi

# Reject malformed or path-traversing archives before extracting them.
python3 - "$RELEASE_ZIP" <<'PY'
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile
import sys
archive = Path(sys.argv[1])
try:
    with ZipFile(archive) as zf:
        bad = []
        for info in zf.infolist():
            name = info.filename.replace('\\', '/')
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts:
                bad.append(name)
        if bad:
            raise SystemExit(f"Unsafe paths in archive: {bad[:3]}")
        if zf.testzip() is not None:
            raise SystemExit("Archive integrity check failed")
except BadZipFile as exc:
    raise SystemExit(f"Invalid ZIP archive: {exc}")
PY

STAMP="$(date +%Y%m%d-%H%M%S)"
TMP_DIR="$(mktemp -d /tmp/lexiloop-update.XXXXXX)"
BACKUP_DIR="$BACKUP_ROOT/$STAMP"
mkdir -p "$BACKUP_DIR/app"
chmod 700 "$BACKUP_ROOT" "$BACKUP_DIR"

SERVICE_WAS_ACTIVE=0
BULK_WAS_ACTIVE=0
BULK_UNIT_EXISTED=0
if systemctl is-active --quiet "$SERVICE"; then SERVICE_WAS_ACTIVE=1; fi
if systemctl is-active --quiet "$BULK_SERVICE"; then BULK_WAS_ACTIVE=1; fi
if [[ -f "$BULK_UNIT" ]]; then BULK_UNIT_EXISTED=1; fi

rollback() {
  local status=$?
  local database_restore_failed=0
  trap - ERR INT TERM
  echo "Update failed; restoring release and persistent data from $BACKUP_DIR ..." >&2
  systemctl stop "$BULK_SERVICE" 2>/dev/null || true
  systemctl stop "$SERVICE" 2>/dev/null || true
  rsync -a --delete \
    --exclude='.venv/' \
    --exclude='frontend/node_modules/' \
    --exclude='.env' \
    --exclude='backend/db.sqlite3' \
    --exclude='backend/media/' \
    "$BACKUP_DIR/app/" "$APP_DIR/" || true
  if [[ -d "$BACKUP_DIR/.venv" ]]; then
    rm -rf "$APP_DIR/.venv"
    cp -a "$BACKUP_DIR/.venv" "$APP_DIR/.venv"
  fi
  [[ -f "$BACKUP_DIR/.env" ]] && cp -a "$BACKUP_DIR/.env" "$APP_DIR/.env"
  [[ -f "$BACKUP_DIR/db.sqlite3" ]] && cp -a "$BACKUP_DIR/db.sqlite3" "$APP_DIR/backend/db.sqlite3"
  if [[ -f "$BACKUP_DIR/database.dump" && "$DATABASE_KIND" == "postgres" ]]; then
    if ! pg_restore --exit-on-error --clean --if-exists --no-owner --no-privileges --dbname="$DATABASE_URL_VALUE" "$BACKUP_DIR/database.dump"; then
      database_restore_failed=1
      echo "CRITICAL: PostgreSQL restore failed. Services will remain stopped." >&2
      echo "Restore manually from: $BACKUP_DIR/database.dump" >&2
    fi
  fi
  if [[ -d "$BACKUP_DIR/media" ]]; then
    rm -rf "$APP_DIR/backend/media"
    cp -a "$BACKUP_DIR/media" "$APP_DIR/backend/media"
  fi
  if (( BULK_UNIT_EXISTED )) && [[ -f "$BACKUP_DIR/lexiloop-bulk.service" ]]; then
    cp -a "$BACKUP_DIR/lexiloop-bulk.service" "$BULK_UNIT"
  elif (( ! BULK_UNIT_EXISTED )); then
    systemctl disable "$BULK_SERVICE" 2>/dev/null || true
    rm -f "$BULK_UNIT"
  fi
  systemctl daemon-reload || true
  chown -R "$APP_USER:$APP_GROUP" "$APP_DIR" || true
  if (( ! database_restore_failed )); then
    if (( SERVICE_WAS_ACTIVE )); then systemctl start "$SERVICE" || true; fi
    if (( BULK_WAS_ACTIVE )); then systemctl start "$BULK_SERVICE" || true; fi
  fi
  rm -rf "$TMP_DIR"
  exit "$status"
}
trap rollback ERR INT TERM

unzip -q "$RELEASE_ZIP" -d "$TMP_DIR"
if [[ -d "$TMP_DIR/lexiloop" ]]; then
  RELEASE_DIR="$TMP_DIR/lexiloop"
elif [[ -f "$TMP_DIR/README.md" && -d "$TMP_DIR/backend" ]]; then
  RELEASE_DIR="$TMP_DIR"
else
  echo "Error: archive must contain lexiloop/README.md and the project directories." >&2
  false
fi
[[ -x "$RELEASE_DIR/scripts/bootstrap-production.sh" ]] || {
  echo "Error: release is missing executable scripts/bootstrap-production.sh" >&2
  false
}

# Stop both writers before copying SQLite.
systemctl stop "$BULK_SERVICE" 2>/dev/null || true
systemctl stop "$SERVICE" 2>/dev/null || true

# Back up the currently deployable application, plus explicit copies of mutable state.
rsync -a \
  --exclude='.venv/' \
  --exclude='frontend/node_modules/' \
  --exclude='.env' \
  --exclude='backend/db.sqlite3' \
  --exclude='backend/media/' \
  "$APP_DIR/" "$BACKUP_DIR/app/"
cp -a "$APP_DIR/.env" "$BACKUP_DIR/.env"
[[ -f "$APP_DIR/backend/db.sqlite3" ]] && cp -a "$APP_DIR/backend/db.sqlite3" "$BACKUP_DIR/db.sqlite3"
if [[ "$DATABASE_KIND" == "postgres" ]]; then
  pg_dump --format=custom --no-owner --file="$BACKUP_DIR/database.dump" "$DATABASE_URL_VALUE"
fi
[[ -d "$APP_DIR/backend/media" ]] && cp -a "$APP_DIR/backend/media" "$BACKUP_DIR/media"
[[ -d "$APP_DIR/.venv" ]] && cp -a "$APP_DIR/.venv" "$BACKUP_DIR/.venv"
[[ -f "$BULK_UNIT" ]] && cp -a "$BULK_UNIT" "$BACKUP_DIR/lexiloop-bulk.service"
printf 'Created: %s\nSource archive: %s\nDatabase: %s\n' "$(date --iso-8601=seconds)" "$RELEASE_ZIP" "$DATABASE_KIND" > "$BACKUP_DIR/release-info.txt"

# Replace code only. Environment, database, cached audio, and the existing virtualenv survive.
rsync -a --delete \
  --exclude='.env' \
  --exclude='.venv/' \
  --exclude='backend/db.sqlite3' \
  --exclude='backend/media/' \
  --exclude='frontend/node_modules/' \
  "$RELEASE_DIR/" "$APP_DIR/"

chown -R "$APP_USER:$APP_GROUP" "$APP_DIR"
chmod 600 "$APP_DIR/.env"

if command -v sudo >/dev/null 2>&1; then
  sudo -u "$APP_USER" -H bash -lc "cd '$APP_DIR' && ./scripts/bootstrap-production.sh"
else
  runuser -u "$APP_USER" -- bash -lc "cd '$APP_DIR' && ./scripts/bootstrap-production.sh"
fi

# v1.6 adds a separate durable worker so bulk requests never occupy a Gunicorn
# request until Nginx times out.
if [[ -f "$APP_DIR/deploy/systemd/lexiloop-bulk.service" ]]; then
  sed -e "s|User=lexiloop|User=$APP_USER|" \
      -e "s|Group=lexiloop|Group=$APP_GROUP|" \
      -e "s|/opt/lexiloop|$APP_DIR|g" \
      "$APP_DIR/deploy/systemd/lexiloop-bulk.service" > "$BULK_UNIT"
fi
systemctl daemon-reload
systemctl enable "$BULK_SERVICE"
systemctl restart "$SERVICE"
systemctl restart "$BULK_SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE"
systemctl is-active --quiet "$BULK_SERVICE"
if command -v nginx >/dev/null 2>&1; then
  nginx -t
  systemctl reload nginx
fi

trap - ERR INT TERM
rm -rf "$TMP_DIR"
echo "LexiLoop update completed. Backup: $BACKUP_DIR"
systemctl --no-pager --full status "$SERVICE" | sed -n '1,12p'
systemctl --no-pager --full status "$BULK_SERVICE" | sed -n '1,12p'
