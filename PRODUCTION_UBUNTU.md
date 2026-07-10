# LexiLoop v1.10.0 — production update guide

This guide updates the currently working PostgreSQL + HTTPS installation at:

```text
/opt/lexiloop
https://lexiloop.ru
```

It assumes:

- PostgreSQL is active through `DATABASE_URL`;
- `lexiloop.service` and `lexiloop-bulk.service` are active;
- Nginx and Let's Encrypt already work;
- the new release ZIP is uploaded as `/root/LexiLoop_AI_Flashcards_v1.10.0.zip`.

v1.10.0 adds one Django migration:

```text
learning.0006_default_emerald_and_openai_catalog
```

The migration changes only the default accent for new users. Existing PostgreSQL data is preserved.

## What v1.10.0 fixes

### Study review result is saved immediately

Checking an answer or revealing a card now records the review immediately. **Next task** only advances to the next card and contains a fallback save path.

### Direct OpenAI API models

Settings now includes readable direct OpenAI choices:

```text
GPT-5.4 mini
GPT-5.4 nano
GPT-5 mini
GPT-5 nano
```

The internal router IDs are hidden from users and use the `openai:` prefix.

### Emerald default

New users and first unauthenticated paint use emerald instead of purple/violet.

### Better smartphone layout

- Open sidebar is full-width below 500 px.
- Overview pool cards no longer overflow on narrow screens.
- Several Overview, Study, Library, and modal layouts are tightened below 430–560 px.

## 1. Upload the release

From your Mac:

```bash
scp ~/Downloads/LexiLoop_AI_Flashcards_v1.10.0.zip \
  root@77.91.69.156:/root/
```

Connect:

```bash
ssh root@77.91.69.156
```

Check the uploaded file:

```bash
sha256sum /root/LexiLoop_AI_Flashcards_v1.10.0.zip
unzip -t /root/LexiLoop_AI_Flashcards_v1.10.0.zip
```

Compare the SHA-256 with the value from the assistant message for this release.

## 2. Confirm current production state

```bash
systemctl is-active lexiloop
systemctl is-active lexiloop-bulk
nginx -t
curl -I https://lexiloop.ru/
```

Confirm PostgreSQL:

```bash
sudo -u lexiloop -H bash -lc '
cd /opt/lexiloop/backend
../.venv/bin/python manage.py shell --no-imports -c "
from django.conf import settings
print(settings.DATABASES[\"default\"][\"ENGINE\"])
print(settings.DATABASES[\"default\"][\"NAME\"])
"
'
```

Expected engine:

```text
django.db.backends.postgresql
```

## 3. Create an independent backup

The updater also creates its own rollback backup, but create a manual one before changing production.

```bash
set -euo pipefail

STAMP="$(date +%Y%m%d-%H%M%S)"
SAFETY="/var/backups/lexiloop/manual-before-v1.10/$STAMP"

install -d -m 700 "$SAFETY"

DATABASE_URL="$(
  /opt/lexiloop/.venv/bin/python - <<'PY'
from dotenv import dotenv_values
print(dotenv_values('/opt/lexiloop/.env').get('DATABASE_URL') or '')
PY
)"

if [[ "$DATABASE_URL" != postgres* ]]; then
  echo "PostgreSQL DATABASE_URL was not found." >&2
  exit 1
fi

pg_dump \
  --format=custom \
  --no-owner \
  --no-privileges \
  --file="$SAFETY/database.dump" \
  "$DATABASE_URL"

cp -a /opt/lexiloop/.env "$SAFETY/.env"
cp -a /opt/lexiloop/backend/media "$SAFETY/media" 2>/dev/null || true

tar -C / \
  --exclude='opt/lexiloop/.venv' \
  --exclude='opt/lexiloop/.env' \
  --exclude='opt/lexiloop/frontend/node_modules' \
  --exclude='opt/lexiloop/backend/staticfiles' \
  --exclude='opt/lexiloop/backend/media' \
  -czf "$SAFETY/application.tar.gz" \
  opt/lexiloop

pg_restore --list "$SAFETY/database.dump" >/dev/null

echo "Independent backup: $SAFETY"
ls -lh "$SAFETY"
```

## 4. Extract the v1.10 updater

```bash
rm -rf /tmp/lexiloop-v1.10-updater
mkdir -p /tmp/lexiloop-v1.10-updater

unzip -q \
  /root/LexiLoop_AI_Flashcards_v1.10.0.zip \
  -d /tmp/lexiloop-v1.10-updater

bash -n \
  /tmp/lexiloop-v1.10-updater/lexiloop/scripts/update-production.sh
```

## 5. Run the update

```bash
sudo \
  /tmp/lexiloop-v1.10-updater/lexiloop/scripts/update-production.sh \
  /root/LexiLoop_AI_Flashcards_v1.10.0.zip
```

Do not interrupt it.

The updater preserves:

```text
/opt/lexiloop/.env
/opt/lexiloop/.venv/
/opt/lexiloop/backend/media/
PostgreSQL database through pg_dump rollback backup
```

It also:

1. stops `lexiloop` and `lexiloop-bulk`;
2. creates a timestamped rollback backup;
3. installs the v1.10.0 source code;
4. runs production bootstrap;
5. installs frontend dependencies if needed;
6. builds the Vite frontend;
7. runs Django migrations, including `0006`;
8. runs `collectstatic --clear`;
9. restarts both services;
10. validates and reloads Nginx;
11. rolls back automatically if any required step fails.

The updater backup will be stored under:

```text
/var/backups/lexiloop/releases/YYYYMMDD-HHMMSS/
```

## 6. Verify services and migration

```bash
systemctl is-active lexiloop
systemctl is-active lexiloop-bulk

systemctl status lexiloop lexiloop-bulk --no-pager
```

Run Django checks:

```bash
sudo -u lexiloop -H bash -lc '
cd /opt/lexiloop/backend
../.venv/bin/python manage.py check
../.venv/bin/python manage.py showmigrations learning
'
```

Expected migration line:

```text
[X] 0006_default_emerald_and_openai_catalog
```

Check HTTPS:

```bash
curl -I https://lexiloop.ru/
curl -I https://lexiloop.ru/study
curl -I https://lexiloop.ru/settings
curl -I https://lexiloop.ru/admin/
```

## 7. Verify Study persistence

Follow backend logs:

```bash
journalctl -u lexiloop -f
```

In the browser:

1. Open `https://lexiloop.ru/study`.
2. Answer a task and press **Check answer**.
3. Wait until the result panel says **Saved**.
4. Refresh the browser without pressing **Next task**.
5. Confirm the previous review was not lost.
6. Repeat with **Show answer**.
7. Press **Next task** and confirm it advances normally.

Stop log following with `Ctrl+C`.

## 8. Verify OpenAI model settings

Open:

```text
Settings → Flashcard generation
Settings → Definition judge
```

You should now see direct OpenAI choices, including:

```text
GPT-5.4 mini
GPT-5.4 nano
GPT-5 mini
GPT-5 nano
```

Paste an OpenAI API key for a direct OpenAI model. OpenRouter keys still belong only to models marked `[OpenRouter]`.

## 9. Verify mobile layout

Use Firefox responsive mode or a phone:

```text
width 390 px
width 430 px
width 500 px
```

Check:

- Overview → Your pools does not overflow horizontally;
- the sidebar uses the full screen width below 500 px;
- Study progress and answer buttons fit without horizontal scrolling;
- Library toolbar and pagination remain usable.

## 10. Rollback if needed

Prefer the updater's automatic rollback. If you need manual rollback from the independent backup:

```bash
systemctl stop lexiloop-bulk
systemctl stop lexiloop

pg_restore \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  --dbname="$DATABASE_URL" \
  /var/backups/lexiloop/manual-before-v1.10/YYYYMMDD-HHMMSS/database.dump

tar -C / -xzf \
  /var/backups/lexiloop/manual-before-v1.10/YYYYMMDD-HHMMSS/application.tar.gz

cp -a /var/backups/lexiloop/manual-before-v1.10/YYYYMMDD-HHMMSS/.env /opt/lexiloop/.env
cp -a /var/backups/lexiloop/manual-before-v1.10/YYYYMMDD-HHMMSS/media /opt/lexiloop/backend/media 2>/dev/null || true

chown -R lexiloop:lexiloop /opt/lexiloop
systemctl start lexiloop
systemctl start lexiloop-bulk
nginx -t && systemctl reload nginx
```

Keep the v1.9 and v1.10 backups for several days after confirming normal use.
