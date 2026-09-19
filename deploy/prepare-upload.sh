#!/usr/bin/env bash
# Build a server bundle: the database, the photos, and what is needed to
# restore them. Run from the project root.
#
#   ./deploy/prepare-upload.sh [--with-snapshots]
#
# Snapshots (data/runs) are the saved HTML of every page ever fetched. They are
# 111 MB and entirely regenerable by re-crawling, so they are excluded unless
# asked for. Include them when the server should be able to re-run extraction
# over old pages without touching anybody's website again.
set -euo pipefail

OUT="${OUT:-upload}"
DB="${DB_NAME:-varna_market}"
STAMP="$(date +%Y-%m-%d)"
WITH_SNAPSHOTS=0
[[ "${1:-}" == "--with-snapshots" ]] && WITH_SNAPSHOTS=1

rm -rf "$OUT"
mkdir -p "$OUT"

echo "==> database"
# Custom format: compressed, and restorable table by table if a restore goes
# wrong halfway. --no-owner so it loads under whatever role the server uses.
pg_dump --format=custom --no-owner --no-privileges "$DB" > "$OUT/varna_market-$STAMP.dump"

echo "==> photos"
# Stored under a content hash, so this archive is append-only in practice:
# re-running it never renames or rewrites a file the server already has.
tar -czf "$OUT/images-$STAMP.tar.gz" -C data images

if [[ $WITH_SNAPSHOTS == 1 ]]; then
  echo "==> page snapshots"
  tar -czf "$OUT/runs-$STAMP.tar.gz" -C data runs
fi

echo "==> manifest"
{
  echo "bundle:   $STAMP"
  echo "database: $DB"
  echo "offers:   $(psql -tAq -d "$DB" -c 'SELECT count(*) FROM sourcing_offer WHERE is_active')"
  echo "images:   $(psql -tAq -d "$DB" -c 'SELECT count(*) FROM sourcing_offerimage')"
  echo "agencies: $(psql -tAq -d "$DB" -c "SELECT count(*) FROM sourcing_agency WHERE website <> ''")"
  echo
  echo "sha256:"
  (cd "$OUT" && shasum -a 256 ./*.dump ./*.tar.gz 2>/dev/null)
} > "$OUT/MANIFEST.txt"

cp deploy/RESTORE.md "$OUT/RESTORE.md"
echo
cat "$OUT/MANIFEST.txt"
echo
du -sh "$OUT"/*
echo
echo "Upload with:  rsync -avh --progress $OUT/ user@server:/srv/varna-market/incoming/"
echo "Then on the server, follow RESTORE.md."
