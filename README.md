# Pocket Broker

Search agency inventory across Varna and Sofia in one Django/PostgreSQL database
and one Vue frontend, retaining source provenance and price history.

## The premise

Preserve each agency's offer and show related listings and their price spread.
Physical property and building clustering remain future work; current groups
are tentative dedup-key matches within the same city and deal type. Incomplete
listing data remains visible with uncertainty indicated.

## Status

The live Varna application already has crawlers, inventory, images, public JSON
search, offer details and an agency directory. Expansion Phase 1 adds geography,
city-scoped APIs, a remembered city selector and neighbourhood filtering.
The five Sofia crawlers are implemented and the full public catalog import is
complete: **8,170 active Sofia listings**, comprising 7,024 sales and 1,146
rentals. See [the import audit](docs/SOFIA-FULL-CATALOG-2026-09-26.md).
The buyer workflow now has **Потребител** (`/user`), **Оферти за теб** (`/for-you`)
and **Желани имоти** (`/wishlist`). Buyers save housing criteria and household
context in their browser, receive explained matches against current inventory,
and maintain a wishlist with refreshed prices and availability. See
[buyer workflow](docs/BUYER-WORKFLOW.md) for persistence and matching rules.
Accounts with cross-device sync, partner analytics, consented leads and scheduled
search alerts remain planned.

**Deployed at https://pb3.avaflow.xyz** since 2026-09-25, from this checkout,
alongside the older live app at `varna.avaflow.xyz`. Read
[deploy/SERVER.md](deploy/SERVER.md) before changing configuration, paths or the
database, and [AGENTS.md](AGENTS.md) first if you are an agent.

See [audited state](docs/CURRENT-STATE.md), [architecture and migration plan](docs/ARCHITECTURE-SOFIA.md),
[operations](docs/OPERATIONS.md) and [plan](docs/PLAN.md).

## Running it

Requires PostgreSQL and the pinned Python packages. The audited server runs
Python 3.12.3; the original development environment used Python 3.14.
Back up an existing database before migrations; do not recreate it.

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env          # then set DJANGO_SECRET_KEY
createdb varna_market                 # fresh development database ONLY
./.venv/bin/python manage.py migrate   # installs pg_trgm, unaccent, btree_gin too
./.venv/bin/python manage.py seed_geography
./.venv/bin/python manage.py test
```

Public geography API: `/api/cities/`, `/api/neighbourhoods/?city=sofia`,
`/api/offers/?city=varna`, `/api/offers/?city=sofia&neighbourhood=lozenets`.
The raw API permits an unscoped inventory query; frontend searches always have
a city. Unresolved neighbourhoods remain eligible in their known city.

Sofia crawling uses five verified agencies: Bulgarian Properties, Yavlena,
Home2U, LUXIMMO and ARCO Real Estate. See
[docs/sofia-crawl-map.md](docs/sofia-crawl-map.md) for source recipes and results.

```bash
# Full public Sofia catalogs, including BP individual development units.
./.venv/bin/python manage.py crawl_live --city sofia --max-pages 1000
# Limited details per source, two pages per sale/rent catalogue.
./.venv/bin/python manage.py crawl_live --city sofia --limit 20 --max-pages 2
# Discovery without importing offers, one selected source.
./.venv/bin/python manage.py crawl_live --city sofia --agency yavlena --discover-only
```

Omitting `--agency` selects exactly these five; repeat it to select a subset.
Sofia sources run sequentially, preserve source IDs and price history, honour
opt-outs and never retire missing offers. `--no-images` skips thumbnails.
Limited imports report partial coverage. Older vendored crawling remains
available for its existing scope:

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
