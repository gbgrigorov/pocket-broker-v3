# Pocket Broker operations — Phase 1

## Current deployment boundary

**Updated 2026-09-25: V3 is now deployed in its own right, at
https://pb3.avaflow.xyz. Full contract in [deploy/SERVER.md](../deploy/SERVER.md).**

The older live checkout `/home/mvp/projects/varna-market` still serves
`varna.avaflow.xyz` on port 8500 from PostgreSQL `varna_market`, unchanged and
unrestarted. V3 runs alongside it from `/home/mvp/projects/pocket-broker-v3` on
port 8501, under PM2 as `pb3`, behind nginx vhost `pb3.avaflow.xyz`.

V3 was pointed at `pocket_broker_v3_phase1` — the restored validation copy — and
that is now its permanent database rather than a throwaway. This keeps
migrations 0005-0007 off the database the live application serves, at the cost of
the two datasets drifting apart from this date. `varna_market` remains untouched
at market 0004. Neither is a second city DB; the city split is `City`/`OfferGeo`
rows inside one database, exactly as designed.

Keep the live deployment fixes in commits `2b01174` and `f1780a8` (still
local-only and unpushed in the varna-market checkout). V3 preserves
`DJANGO_BEHIND_PROXY` and now has its own nginx block and process supervision;
it does not replace the live app's.

## Backup and release order

Use the configured PostgreSQL connection (PGHOST/PGPORT/PGUSER/PGDATABASE and
PGPASSFILE or protected environment). Keep credentials out of command arguments
and logs. Keep backups outside any served media path and out of Git.

```bash
umask 077
mkdir -p backups
pg_dump -Fc --file backups/backup_before_sofia.dump
pg_restore --list backups/backup_before_sofia.dump > /dev/null
pg_restore --file /dev/null backups/backup_before_sofia.dump
```

Use a unique dated filename on each real release. Verify with a full restore
into a **new, empty validation database** using `pg_restore --no-owner
--no-privileges --exit-on-error --dbname <new_validation_database> <dump>`, then
compare counts and full-row checksums. Never restore over production. The
Phase 1 restore/checksum evidence is recorded in CURRENT-STATE.md.

Before a live release, in the intended checkout and environment:

```bash
python manage.py check
python manage.py test
python manage.py makemigrations --check --dry-run
python manage.py vendor_check
cd frontend
npm ci
npm run build
cd ..
```

After a fresh verified backup, apply `python manage.py migrate`, followed by
`python manage.py seed_geography`. Migration 0006 seeds and backfills; the command
is intentionally repeatable. Preserve the live media and static publication
layout, collect/publish static using the existing deployment script, restart the
existing process, then smoke-test search/detail/agencies for both cities.
Sofia had zero active offers at the geography release. Deliberate five-source
imports began on 2026-09-26 in a separate operation; see `sofia-crawl-map.md`.
Inherited inactive records reactivate only when their own public listing is
verified, preserving row IDs and history. Never bulk-reactivate that history.

## Geography maintenance

The live v3 seed was verified on 2026-09-26 with `manage.py seed_geography`
run twice: 2 cities, 77 neighbourhoods, 124 aliases and 10,744 OfferGeo rows,
with no missing geography rows. It processed zero offers because the database
was already fully seeded. All eleven checked supply and geography table
checksums remained unchanged, including manual edits and the 8,170 active
Sofia listings. This seed initializes geography; real inventory is populated
by the documented public catalog imports, not by fabricated sample offers.

Backup before this operation:
`backups/before_seed_commit_20260926_105047.dump`, SHA-256
`152e9707e4c9b41b04883fc0c8902d49e658aeb3f25eb162f3475fe889d162a5`.
A full restore into a new empty verification database matched all eleven
model counts and full-row checksums. The private seed audit is
`data/runs/database-seed-20260926.json`. Dumps, credentials, raw evidence and
downloaded photos remain outside Git; code, migrations and seed rules are
versioned.

The OfferGeo admin filters by city, neighbourhood, agency, active status and
matching method. `city` empty identifies unknown cities; `neighbourhood` empty
identifies unresolved quarters. Correct rows there to set `matched_by=manual`.
Manual changes survive ingest and repeat seeds. Add spelling aliases on a
neighbourhood and run `python manage.py seed_geography --resolve` to reevaluate
automatic rows. Review before bulk repair; normal ORM saves resolve automatically,
while `bulk_create` and SQL updates require this explicit command.

Coastal towns outside Varna are preserved as unclassified cities, not renamed.
Their offers remain in the unscoped API; additional city seeds/curation can bring
them into future selectable markets. A known city's unknown quarter stays in
its filtered results, visibly unresolved.

Rollback code first: the new tables are additive and old code ignores them.
Do not reverse schema migrations on a live system with curator edits unless
you have explicitly arranged to preserve that geography. No supply rows are
modified by these migrations.
