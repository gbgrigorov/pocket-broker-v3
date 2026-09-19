# Varna Market

Every apartment on the Varna market, in one searchable place — crawled from
vetted agency websites, clustered so each real thing appears once.

## The premise

Searching for a flat in Varna today means searching imot.bg, where **up to half
the listings are fake or duplicated**, and then searching twenty agency sites
that each show you the same tower forty times, once per floor.

So this is not "more listings than imot.bg". It is fewer, and all of them real:

- **One flat = one result**, whoever lists it. The same apartment marketed by
  five agencies collapses into one card showing all five prices and the spread.
- **One building = one result.** An under-construction development is one card
  with its units inside it, not forty results. Even when two agencies market it
  under completely different names — one sold a *skyscraper*, another *luxury
  apartments*, and it was the same building.
- **Only vetted agencies.** Admission is on association membership, review
  record and years in the market. The exclusion list is public.

## Status

Phase 1 of 10. The engine is in and the schema is live; nothing has been
crawled yet.

| | Phase | State |
|---|---|---|
| 0 | Repo, database, settings | ✅ |
| 1 | Vendor the crawler, prove parity | ✅ 48 tests |
| 2 | Varna agency registry + reconnaissance | next |
| 3 | Site recipes, first crawl, images | |
| 4 | Varna neighbourhood geography | |
| 5 | Clustering — units, then projects | |
| 6 | Buyer profile & matching | |
| 7 | Public API | |
| 8 | Frontend | |
| 9 | The "no fakes" proof | |
| 10 | Deploy | |

Full plan: [`docs/PLAN.md`](docs/PLAN.md).

## Running it

Requires PostgreSQL and Python 3.14.

```bash
python3.14 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env          # then set DJANGO_SECRET_KEY
createdb varna_market
./.venv/bin/python manage.py migrate   # installs pg_trgm, unaccent, btree_gin too
./.venv/bin/python manage.py test
```

Crawling:

```bash
./.venv/bin/python manage.py crawl_sites --discover-only   # what would we fetch?
./.venv/bin/python manage.py crawl_sites       # fetch and ingest
./.venv/bin/python manage.py vendor_check --upstream  # has broker-crm moved?
```

## Design notes worth knowing before reading the code

**A missing value never fails a filter.** It costs confidence, not score. A flat
whose floor the agency never published still appears in a search that does not
filter on floor — labelled unverified rather than silently dropped. Inherited
from broker-crm and load-bearing here, because agency data is patchy and the
portals' habit of hiding incomplete records is part of what makes them unusable.

**Cross-agency duplicates are the product, not a bug.** They are clustered and
shown together, never merged — the price spread between five agencies selling
one flat is the single most interesting number on the page.

**Identity never includes price.** A price cut must read as a change to an
existing offer, never as one listing dying and a new one being born. This was
an expensive lesson upstream: 157 of 1,150 offers once carried price in their
fingerprint, and every reduction minted a phantom "new" listing.

## Documentation

| | |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | The full build plan and the reasoning behind it |
| [`docs/CRAWL-POLICY.md`](docs/CRAWL-POLICY.md) | What the crawler does, what it refuses to do, and the known legal exposures |
| [`docs/VENDORING.md`](docs/VENDORING.md) | Where the code came from and how divergence is tracked |
| [`docs/VENDOR-MANIFEST.md`](docs/VENDOR-MANIFEST.md) | Generated checksums — do not edit by hand |
