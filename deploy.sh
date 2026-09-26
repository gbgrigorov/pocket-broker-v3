#!/bin/bash
set -e

# Pocket Broker v3 — Django 6.1 (gunicorn) + Vue 3 SPA + PostgreSQL 16.
#
# Shape on this box:
#   gunicorn  config.wsgi  ->  127.0.0.1:8501, under PM2 as `pb3`
#   nginx     pb3.avaflow.xyz  ->  proxy to 8501, and serves the two
#             static trees itself out of /var/www/pb3/
#   database  pocket_broker_v3_phase1  — the ISOLATED validated copy.
#
# ⚠️ This runs SIDE BY SIDE with varna.avaflow.xyz (projects/varna-market, port
# 8500, database varna_market). It does not replace it. The two apps share a
# PostgreSQL role and the photo corpus, but NOT a database: v3 carries
# migrations 0005-0007 that the live app has never seen, which is exactly why
# it points at its own copy. Never repoint DB_NAME at varna_market without
# reading deploy/SERVER.md first.
#
# Why static lives in /var/www and not in the repo: /home/mvp is drwxr-x---,
# so www-data cannot traverse into the project at all. `staticfiles/` is
# rsynced there on every deploy, and `data/images` is a SYMLINK to
# /var/www/pb3/media/images so that photos a crawl writes tonight are served
# by nginx immediately, with no deploy and no copy. Deliberately only `images`
# — data/raw, data/runs and data/recon are saved copies of other people's
# pages and stay inside the home dir, unreachable from the web.

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

VENV="$PROJECT_DIR/.venv"
PY="$VENV/bin/python"
WEBROOT=/var/www/pb3
PORT=8501

[[ -x "$PY" ]] || { echo "No venv at $VENV — see deploy/SERVER.md"; exit 1; }
[[ -e "$PROJECT_DIR/.env" ]] || { echo "No .env symlink — see deploy/SERVER.md"; exit 1; }

echo "==> Pulling latest code..."
git pull

echo "==> Python deps..."
"$VENV/bin/pip" install -q -r requirements-server.txt

echo "==> Frontend build..."
( cd frontend && npm ci && npm run build )

echo "==> Vendored-crawler integrity..."
# The supply half is a vendored copy of broker-crm. A silent local edit to it
# is the one thing that makes a fix stop moving between the two projects.
"$PY" manage.py vendor_check || echo "    (vendor_check reported drift — see docs/VENDORING.md)"

echo "==> Migrations..."
"$PY" manage.py migrate --noinput

echo "==> collectstatic..."
"$PY" manage.py collectstatic --noinput --clear >/dev/null

echo "==> Publishing static to $WEBROOT/static ..."
# --delete is safe here: this tree is generated output, nothing else writes it.
rsync -a --delete staticfiles/ "$WEBROOT/static/"
# nginx reads these as www-data; collectstatic's umask can be tighter.
chmod -R a+rX "$WEBROOT/static"

echo "==> Restarting PM2 process (pb3)..."
# --interpreter is load-bearing: .venv/bin/gunicorn has no file extension, so
# PM2 defaults to node and dies with "SyntaxError: Unexpected identifier
# 'gunicorn'" in a crash loop. PM2 is not Node-only here -- seaside runs Python
# the same way.
pm2 restart pb3 2>/dev/null || \
  pm2 start "$VENV/bin/gunicorn" --name pb3 --cwd "$PROJECT_DIR" \
    --interpreter "$PY" -- \
    config.wsgi:application \
    --bind 127.0.0.1:$PORT --workers 3 --timeout 120 \
    --access-logfile - --error-logfile -
pm2 save

echo "==> Done. https://pb3.avaflow.xyz  (nginx → 127.0.0.1:$PORT)"
