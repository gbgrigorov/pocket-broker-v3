# Pocket Broker: multi-city architecture

## Scope and audited foundation (2026-09-25)

This change implements Phase 1 only. Sofia reconnaissance, new crawling,
accounts, favorites, interest analytics, partner access, leads and saved searches
remain separate phases. No external agency is contacted by this implementation.

The V3 checkout is `main` at `f3c1b9f`, matching GitHub HEAD. The live application
is `/home/mvp/projects/varna-market`, at `f1780a8`; it contains two deployment
commits absent from V3. Both have the same supply models and application code;
live settings additionally configure secure cookies behind nginx. Preserve that
setting when deploying V3. Actual runtime: Python 3.12.3, Django 6.1.1,
psycopg 3.3.5, PostgreSQL 16. nginx fronts gunicorn managed by PM2 on this host.

There is no Unit, Project, BuyerProfile, Favorite or partner/lead model yet.
`Offer.dedup_key` supplies tentative cross-agency groups. Price histories and
image/source provenance already exist. Django sessions and CSRF middleware exist;
there is no public account API. Vue 3, Pinia, PrimeVue and Vue Router remain.

## Exact Phase 1 model and migration plan

All new tables live in `market`; `sourcing.Offer` remains unchanged.

| Model | Fields and constraints |
| --- | --- |
| Country | unique two-character code, name |
| City | protected country FK, globally unique URL slug, Bulgarian/English names, nullable coordinates, active |
| Neighbourhood | protected city FK, city-scoped unique slug, bilingual names, nullable coordinates, active |
| NeighbourhoodAlias | neighbourhood FK, original and normalized alias, unique (neighbourhood, normalized_alias), normalized alias lookup index |
| OfferGeo | one-to-one Offer FK, nullable protected city and neighbourhood FKs, raw/normalized location, nullable coordinates, confidence 0–1, matched_by; (city, neighbourhood) index |

City is nullable only when the city itself cannot be established. A known Sofia
offer with an unknown neighbourhood retains city=Sofia and neighbourhood=NULL.
Ambiguous aliases never force a match. A neighbourhood must belong to its city.
`matched_by=manual` protects curator corrections from later crawler saves.

1. `0005_geography`: create five tables, constraints and indexes only.
2. `0006_seed_geography_backfill`: frozen v1 seed and additive backfill of all
   existing offers. No Offer, history, agency, image, fingerprint, dedup key or
   lifecycle field changes. Reverse is a data no-op; dropping the geography schema
   would lose curation, so normal rollback should revert code, retaining tables.
3. `seed_geography`: repeatable seed plus missing-row backfill; `--resolve` can
   re-evaluate nonmanual geography after alias curation. Seeds Bulgaria, Varna,
   Sofia, the requested Sofia quarters, and practical Varna quarters.

The production database is not Varna-only: it contains inactive Sofia stock,
coastal towns and blank locations. Explicit Varna/Sofia locations are resolved
first. Existing `crawl_live` evidence supplies Varna context only when location
is blank (that command is explicitly Varna-scoped). Other unresolved cities stay
NULL. Coastal towns are not renamed Varna. All original inventory remains
available through the unscoped API; city search deliberately excludes unrelated
towns. No inactive Sofia offer is reactivated to fill the new market.

An application-owned Offer post-save hook resolves geography for normal ORM
ingest without forking the supply models or ingest code. Bulk updates bypass
signals and require the explicit resolution command. Future city-specific
crawlers must supply verified `evidence.city` when their listing omits city.
Explicit source location wins over crawl context. Unknown neighbourhoods do
not prevent storage. No LLM calls or new infrastructure are introduced.

## Search and deduplication

Public city and neighbourhood directories drive the frontend. `city` is optional
on the raw API, required in frontend search state, remembered locally and included
in URLs. Offers, facets, agency counts and header stats share city scope.
Neighbourhood filtering requires a city and uses its scoped slug. Unknown
neighbourhoods remain eligible under that city's filter with reduced geographic
confidence, preserving the existing uncertainty principle. Unknown numeric fields
retain existing filtering behavior. Invalid geography input fails closed.

All sibling comparisons require the same resolved city and deal type. Unresolved
cities cannot cluster. Public cluster identifiers include city and deal; existing
stored dedup hashes and listing identity remain untouched. The fuzzy SQL helper
also adds city scope, recorded as a deliberate vendoring divergence.

## Later phases and privacy boundaries

Phase 2 extends existing SiteProbe and probe commands with city-specific source
evidence, reuses Agency rows, opens actual URLs, and records a verified strategy
or a blocked/unsuitable verdict for each candidate. Phase 3 adds adapters one at
a time with saved fixtures and coverage/retirement safeguards. No full Sofia
crawl is coupled to a schema deployment.

Favorites will use Offer plus a city-scoped cluster snapshot until Unit exists;
anonymous browser saves merge into session-authenticated account saves. A
FAVORITE is anonymous demand, never consent to expose identity. Partner queries
must filter active AgencyMembership on the server. Only an explicit consented
LeadRequest creates an AgencyLead for the selected agency and stable referral
code. Saved searches must carry a city and use deterministic matching. These
contracts guide later work; none of these features is implemented in Phase 1.

## Safety and release gate

The live DB was backed up before schema work, fully restored to the isolated
`pocket_broker_v3_phase1` database, and core row checksums compared. See
CURRENT-STATE.md and OPERATIONS.md for evidence, verification and deployment.
Validate migrations on this copy, run all Django tests/checks, build Vue, compare
core row checksums, and smoke-test Varna/Sofia APIs before any live release.
