# Audited state — 2026-09-25

**Update 2026-09-26:** v3 is deployed separately at `https://pb3.avaflow.xyz`;
[deploy/SERVER.md](../deploy/SERVER.md) supersedes the historical deployment notes
below. The buyer profile, explained matches and browser-persistent wishlist are
now implemented; see [BUYER-WORKFLOW.md](BUYER-WORKFLOW.md). The five Sofia
crawlers are implemented. The first limited imports contained 87 active offers
(43 sale, 44 rent). The full five-source backfill is complete: **8,170 active
Sofia offers (7,024 sale, 1,146 rent)**, including individually identified BP
development units. See [the completed import audit](SOFIA-FULL-CATALOG-2026-09-26.md)
and [sofia-crawl-map.md](sofia-crawl-map.md)
for source recipes, backup verification, run counts and limitations. The current full suite
most recently ran 231 tests: 228 passed and 3 expected skips. Earlier Phase 1 figures below remain the historical
baseline, not a statement that the newer buyer workflow is absent.

- V3: clean `main`, `f3c1b9f`, matches `git ls-remote origin HEAD`.
- Live: `/home/mvp/projects/varna-market`, clean, `f1780a8`; local deployment
  commits `2b01174` and `f1780a8` are absent from the V3 repository.
- Live app code and supply models match V3; deployment differs (nginx, PM2,
  gunicorn, secure proxy settings, DB setup/restore safeguards).
- Actual versions: Python 3.12.3 / Django 6.1.1 / psycopg 3.3.5 / PostgreSQL 16.
  V3 had neither a virtualenv nor .env. Validation uses the installed live Python
  runtime with V3 code and a separately restored database; credentials are never
  copied into versioned files.
- Both baseline suites: 90 tests, passed, 3 upstream-only skips. All pre-existing
  migrations applied (market through 0004, sourcing 0001).

## Database baseline

| Table | Rows |
| --- | ---: |
| Agency | 139 |
| Offer | 2,572 |
| Active Offer | 1,779 |
| OfferHistory | 12 |
| OfferImage | 2,429 |
| CrawlRun | 10 |
| SheetSnapshot | 0 |
| SiteProbe | 225 |

Offers include 245 inactive rows explicitly labelled Sofia. Active stock includes
coastal towns outside Varna and 14 blank locations. Do not blindly mark all rows
Varna or reactivate stale Sofia stock. Existing sources and images remain intact.

Backup: `backups/backup_before_sofia_20260925_182953.dump` (private,
gitignored). SHA-256:
`76c23c4ffc4b2fe5bd91d3216e0dbac8b65ae16d135b82de0108ccc7eca4ed1b`.
Verification: archive TOC read, entire SQL stream decoded, full restore into new
`pocket_broker_v3_phase1`, then counts and complete row SHA-256 compared for all
seven core tables. The adjacent JSON manifest records those checksums.

## Existing functionality

Supply models: Agency, Offer, OfferHistory, OfferImage, CrawlRun, SheetSnapshot.
Market model: SiteProbe. No physical Unit or demand/partner models exist.
Public API: paginated offers, detail with dedup siblings/price spread, facets,
agency directory, stats. Numeric uncertainty remains eligible. Vue has search,
offer detail and agency directory; Pinia installed, public accounts absent.

Crawlers: vendored sheet/catalogue ingestion plus Varna recipes, live JSON/WP/HTML
catalogues, probe evidence, run traces, price repair and image management.
`crawl_live` explicitly filters Varna; the older sitemap discovery captured
off-market/inactive inventory. Latest stored probes include blocked Address and
Imoteka; these are historical observations, not new Sofia reconnaissance.
Several old CrawlRun rows remain `running`; they are not proof of current work
or successful freshness. No crawler is executed as part of Phase 1.

## Phase 1 validation result

The implementation is in V3's working tree and is not deployed. Migrations 0005
and 0006 were applied only to `pocket_broker_v3_phase1`. All seven core table row
checksums still match the backup, in both the validation DB and the live DB.
OfferGeo has 2,572 rows: 1,772 Varna (1,522 active), 245 Sofia (all inactive),
555 unresolved cities (257 active). All 1,767 originally explicit Varna rows
remain in Varna. Unresolved records are predominantly outside-city stock and
remain accessible through the unscoped API. No stock was reactivated or deleted.

The final suite contains 113 tests (23 added); it passes with the same three
skips for absent sheet snapshots in `data/raw`. Checks, migration drift detection,
vendoring checks and production frontend build pass. Browser smoke checks passed
for city selection, persistence, scoped agencies, neighbourhoods, Back navigation,
offer links and mobile layout. Detailed results: [PHASE1-REPORT.md](PHASE1-REPORT.md).
