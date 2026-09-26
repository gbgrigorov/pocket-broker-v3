# Phase 1 implementation report — 2026-09-25

## CURRENT STATE

- V3 `main` started clean at `f3c1b9f`, matching GitHub HEAD.
- The live checkout is separately deployed at `f1780a8` under
  `/home/mvp/projects/varna-market`, with two deployment commits not in V3.
- Actual runtime: Python 3.12.3, Django 6.1.1, psycopg 3.3.5, PostgreSQL 16;
  nginx/gunicorn/PM2. The V3 checkout initially had no Python runtime or DB env.
- Existing models: Agency, Offer, OfferHistory, OfferImage, CrawlRun,
  SheetSnapshot, SiteProbe. No Unit, buyer accounts, favorites, partner or leads.
- Existing crawler architecture: sheet ingestion, catalogue and sitemap
  discovery, Varna live JSON/WP/HTML sources, probes/traces, images/price repairs.
  Several old runs remain marked running; stored blocked-site results are
  historical. No new crawl or reconnaissance was performed in this phase.
- Existing frontend: Vue 3/Vite/Pinia/PrimeVue, public search, offer detail with
  sibling pricing, agency directory. Existing Django JSON/session/CSRF stack kept.

## CHANGES MADE

### Models and migrations

- New Country, City, Neighbourhood, NeighbourhoodAlias and OfferGeo in `market`.
- `0005_geography`: additive tables, one-to-one Offer geography, city-scoped
  neighbourhood uniqueness, alias constraints, confidence constraints and index.
- `0006_seed_geography_backfill`: frozen v1 Bulgaria/Varna/Sofia seed, 56 Sofia
  and 21 Varna quarters, additive geography for all existing offers.
- `seed_geography`: idempotent seed and missing-row backfill; `--resolve` reruns
  automatic matching and preserves manually curated records.
- Normal ORM ingestion resolves geography through an application-owned hook.
  Original Offer schema, identities, history, prices and provenance are unchanged.
- Exact and fuzzy sibling comparisons require the same resolved city. Public
  cluster keys also include city and deal. The fuzzy helper is an explicitly
  documented vendoring divergence, with updated manifest.

### APIs and frontend

- Added `GET /api/cities/` and `GET /api/neighbourhoods/?city=...`.
- Offers, facets, stats and agency counts accept city scope; offers accept
  city-scoped neighbourhood slugs. Detail optionally validates city scope.
- Unknown neighbourhoods remain eligible within their known city; missing
  numeric characteristics preserve the existing confidence rule. Invalid city
  or neighbourhood filters cannot broaden results.
- Pocket Broker branding, prominent city selector, remembered choice, URL city
  context, neighbourhood selector, honest Sofia empty state and scoped directory.
- Browser Back restores query state; stale requests cannot replace newer city
  results. City context follows navigation and offer links. Fixed narrow-screen
  price inputs and the neighbourhood selector's accessible label.
- Added geography curation admin, including unresolved-city filters and manual
  corrections. Preserved the live deployment's secure TLS proxy settings.

### Files

New backend files:
`market/admin.py`, `market/geography.py`, `market/geography_seed_v1.py`,
`market/management/commands/seed_geography.py`,
`market/migrations/0005_geography.py`,
`market/migrations/0006_seed_geography_backfill.py`,
`market/tests/test_geography.py`.

Updated backend/configuration files:
`market/models.py`, `market/apps.py`, `market/api.py`, `market/views.py`,
`market/upstream.py`, `crm/dedup.py`, `config/settings.py`, `config/urls.py`,
`.env.example`, `.gitignore`. No `sourcing/` files changed.

Frontend:
new `frontend/src/lib/city.js`; updated `frontend/index.html`,
`frontend/src/App.vue`, `frontend/src/router.js`, `frontend/src/style.css`,
`frontend/src/lib/api.js`, `frontend/src/components/OfferCard.vue`,
`frontend/src/views/SearchView.vue`, `frontend/src/views/OfferView.vue`,
`frontend/src/views/AgenciesView.vue`.

Documentation:
new `docs/CURRENT-STATE.md`, `docs/ARCHITECTURE-SOFIA.md`,
`docs/OPERATIONS.md`, `docs/sofia-crawl-map.md`, `docs/DATA-PRIVACY.md`,
`docs/PARTNER-PORTAL.md`, `docs/INVESTOR-DEMO.md`, this report;
updated `README.md`, `docs/PLAN.md`, `docs/CRAWL-POLICY.md`,
`docs/VENDOR-MANIFEST.md`. Future-feature docs explicitly describe planned work.

## DATA SAFETY

Backup: `backups/backup_before_sofia_20260925_182953.dump`, private mode 0600,
outside served media and ignored by Git. Its JSON manifest records SHA-256 and
full-row checksums. It was decoded, fully restored into a new isolated PostgreSQL
database, then compared against the original. No production restore/reset occurred.

| Core data | Before | After (validation copy and live) |
| --- | ---: | ---: |
| Agencies | 139 | 139 |
| Offers | 2,572 | 2,572 |
| Active offers | 1,779 | 1,779 |
| Offer history | 12 | 12 |
| Images | 2,429 | 2,429 |
| Crawl runs | 10 | 10 |
| Sheet snapshots | 0 | 0 |
| Site probes | 225 | 225 |

Every core row checksum matches the backup, not just row counts. Geography adds
2,572 sidecar rows. All 1,767 explicit Varna rows resolve to Varna. Including
raw-location/source evidence, 1,772 rows resolve to Varna (1,522 active). The 245
Sofia rows remain inactive, so Sofia is a selectable empty active market.

555 cities remain unresolved, including 257 active offers. Many are coastal
towns outside Varna, rather than bad Varna data. These remain stored and available
via the raw unscoped API, but do not appear under Varna/Sofia city filtering.
The 14 active records with blank locations remain unresolved. Do not claim the
previous broad Varna-market total is the new exact Varna-city total.

Live Varna code, schema and service were not changed or restarted. New migrations
were applied only to `pocket_broker_v3_phase1`, a disposable validation copy.
No deployment, Git commit, push or agency crawl was performed.

## TESTS

- Baseline: both live checkout and V3 ran 90 tests successfully, 3 skips.
- Final: 113 tests successfully, same 3 skips (missing sheet snapshot fixtures).
- 23 new tests cover geography, aliases, ambiguity, numeric uncertainty,
  same-name quarters in different cities, no substring city matches, source
  context conflicts, future city additions, idempotence/manual curation, bulk
  backfill, migration preservation, web identity and price history, city-scoped
  counts/details/exact and fuzzy dedupe, constraints and empty Sofia.
- `check`, `makemigrations --check --dry-run`, `vendor_check`, `git diff --check`
  and `npm run build` passed. No dependency or framework changes.
- Chromium smoke checks passed: city switch, reload and default persistence,
  agency scope, neighbourhood filtering, Back navigation, detail context,
  390px mobile layout and no JavaScript runtime errors. Two discovered UI
  defects (accessible label and input overflow) were fixed and rechecked.
- API smoke requests returned HTTP 200, with offers paginated to 24. On this
  restored database, measured in-process requests took roughly 2–80 ms; this is
  a local smoke measurement, not a production load-test/SLA claim.
- No outstanding test failures. Initial environment/test-harness/browser setup
  problems were resolved; no system package installation or live-service change
  was needed for browser checks.

## RISKS

- Crawler: existing commands are not Sofia-ready. Historical block verdicts
  require fresh evidence. Agency-wide retirement must not run on a partial city
  crawl; valid per-city coverage and quality gates belong in Phase 3.
- Dedupe: hashes remain heuristic, not verified physical Unit identities.
  Unresolved cities cannot form sibling groups; no offer merging was introduced.
- Geography: missing cities and quarters require curation. Alias ambiguity stays
  unresolved; neighbourhood filters include unknown quarters and label them.
  Bulk SQL/ORM updates bypass the save hook and require explicit re-resolution.
- Privacy: Phase 1 collects no new buyer contact data. Future favorites must
  expose aggregate interest only; contact details require explicit named-agency
  consent and membership-scoped authorization tests. Validation DB/dumps remain
  private because they contain the production snapshot.
- Deployment: V3 is not the live checkout. Reconcile the existing deployment
  commits and follow OPERATIONS.md before release; do not run an old blanket
  deploy/restore procedure that discards those server fixes.

## NEXT STEP

Phase 2 only, after reviewing this result:

1. Reconcile the ten candidate names against the existing Agency registry;
   reuse canonical rows/slugs (including `adres`), with idempotent Sofia cohort
   membership instead of duplicate city-specific agencies.
2. Extend SiteProbe with nullable City, city/run-aware latest selection and
   structured source-strategy evidence; preserve historical Varna probe rows.
   Extend the existing `probe_agencies` command with `--city` and agency scope.
3. For each candidate, open its canonical public domain and actual catalogue,
   sitemap/JSON/listing/pagination URLs before recording any recipe. Capture sale
   and rent city filters, encoding, images, project/unit distinction, robots and
   block/rate behavior, discovery counts and evidence timestamps.
4. Populate `docs/sofia-crawl-map.md` from those observations. Each target gets a
   verified strategy or a documented blocked/unsuitable reason; replace unsuitable
   targets when warranted. No bypasses and no fabricated coverage figures.
5. Report the Phase 2 gate before Phase 3 adapters, fixture extraction tests and
   limited end-to-end crawls. No full ten-source crawl accompanies migrations.
