# Pocket Broker — implementation plan

## Sofia expansion checkpoint (2026-09-26)

The historical plan below records the original Varna work and its crawler
lessons; it is not the current implementation status. Follow
[ARCHITECTURE-SOFIA.md](ARCHITECTURE-SOFIA.md) and [CURRENT-STATE.md](CURRENT-STATE.md).

Geography and city-scoped search are deployed. The buyer profile, explained
matches and browser-persistent wishlist were implemented at the user's request.
The Sofia cohort is now five verified sources with fixture-tested adapters,
city-specific probes and quality metrics. The first sample contained 87 offers;
the full backfill is complete with 8,170 active Sofia listings and includes BP
development-unit availability tables. See [the import audit](SOFIA-FULL-CATALOG-2026-09-26.md)
and [sofia-crawl-map.md](sofia-crawl-map.md).
Automatic scheduling and missing-offer retirement remain separate work.
Accounts, cross-device saved profiles, partner memberships and consented leads
remain future scope; anonymous browser preferences already work.

## Context

Gabe wants an investor-demo MVP: **every apartment on the Varna market, in one searchable place** — a
market-wide version of what `~/Dev/broker-crm` already does for one Burgas broker. If it works, it
scales to all of Bulgaria.

Three things sharpened the product during scoping, all from Gabe:

**1. Portal listings are not trustworthy.** Up to 50% of imot.bg stock is fake or duplicated. That is
not a limitation to apologise for — it is the product. *Not more listings than imot.bg — fewer, and
all of them real.*

**2. The market is unreadable because nothing is clustered.** The same flat appears under five
agencies at five prices. Worse, an under-construction building is exploded into one offer per
apartment — search "two-bedroom" and get the same tower forty times, one per floor. And agencies
market the same building under completely different names: one sold it as *a skyscraper*, another as
*luxury apartments*. **They were the same building.**

**3. Search is not enough — the buyer should describe himself, not a filter.** Enter a buyer profile
and the system works the whole market for him and explains its reasoning.

> One card per real thing. One flat = one result, whoever lists it. One building = one result,
> however many units are in it. And one profile = a standing search across every vetted agency.

### Decisions already taken
| | |
|---|---|
| Foundation | New repo `~/Dev/varna-market`, vendoring `broker-crm/` |
| Crawl scope | Vetted agency websites. **Crawl everything we need — robots.txt not treated as a blocker.** No portal ad scraping. |
| Hero screen | Apartment search, with buyer-profile matching beside it |
| Timeline | No fixed date — build it properly (git, tests, deploy from day one) |

---

## Verdict: is broker-crm's architecture right for this?

**Yes — more of it than I first thought.** Adding buyer-profile matching means we vendor nearly the
whole application, not just the crawler. What we drop is only the *broker's daily workflow*.

`broker-crm/sourcing/` is not a CRM module — it is already a **multi-source aggregator**. The
brokerage owns zero listings in that schema. Every row carries `agency_id`, `source`, `source_url`,
`fingerprint`, `dedup_key`. It holds **5,358 live offers from 40 agencies** today.

**Take — supply side:**

| What | Where | Why it matters |
|---|---|---|
| `Offer` schema w/ provenance + price history | `sourcing/models.py` | Multi-agency from the ground up |
| Sitemap-diff crawler, 17 site recipes | `sourcing/web/` (2,030 LOC) | A recipe is **~5 lines** |
| 4-tier extractor (spec table → JSON-LD → regex → text window) | `sourcing/web/extract.py` | BG/RU/EN/DE, BGN→EUR, sold/reserved |
| **Unit-level** cross-agency dedupe | `crm/dedup.py` | Cyrillic→Latin translit + `pg_trgm` ≥0.55 |
| BG field parsers, fingerprinting, `dup_group` | `sourcing/vendor/normalize.py` (~700 LOC) | Rooms→bedrooms, junk-ref rejection, value quarantine |
| Change log | `sourcing/models.py::OfferHistory` | "price dropped €10k yesterday" already queryable |

**Take — demand side (the buyer-profile engine, previously mis-scoped as droppable):**

| What | Where | Becomes |
|---|---|---|
| `SearchCriteria` | `crm/models.py` | The buyer profile: price ±tolerance, beds, area target, locations, `must_haves` / `nice_to_haves` / `deal_breakers`, floor rules, `brief_text` |
| `ScoringProfile` | `matching/models.py` | Weights as **data, not code** — tunable without a deploy |
| `matching/engine.py` + `Candidate` | | Scores every offer against a profile; stores `score_breakdown` |
| Confidence model | `broker-crm/README.md` | `fit = Σ(subscore·weight for KNOWN) / Σ(weight for KNOWN)`; `confidence = Σ(KNOWN) / Σ(IN PLAY)`. **A missing value never fails a filter — it costs confidence, not score.** Portals silently drop flats with a blank field; we won't. |
| `MatchFeedback` (23 reason codes) + `CriteriaSuggestion` | `crm/models.py` | The profile *learns* from rejections and proposes its own corrections |
| `matching/preview.py` | | Live result count per keystroke, nothing persisted |
| `WhyPanel.vue`, `ScoreRing.vue`, `MatchCard.vue`, `BandPill.vue`, `CriteriaEditor.vue`, `FeaturePicker.vue`, `LocationPicker.vue` | `frontend/src/components/` | The whole explain-the-match UI, already built |

**Drop:** the broker's workflow only — `Client.stage`/`priority`/`next_followup_on`, `Interaction`,
`inbox/`, the printable shortlist, staff-only auth. A public buyer replaces the broker's client record.

**Build new:** **project clustering** · public search UI · agency directory · lat/lng + Varna
gazetteer · image crawling + hashing · anonymous/self-service accounts · deploy · git.

### Two risks in broker-crm we inherit unless we fix them
1. **It is not in git.** 5,358 offers of work, unversioned, actively edited on 2026-09-18. Vendoring
   into a new repo is partly a rescue.
2. **Geography is wrong.** 5,358 offers; Varna has 7. We inherit the engine, not the data.

---

## The data model: three levels, not one

The vendored `Offer` stays the atom — untouched, so vendor parity tests stay green. Clustering is
added **above** it in a new `projects/` app, using join tables rather than edits to vendored models.

```
Project          one building / development
  ├── ProjectAlias      "Небостъргач Варна" · "Luxury Apartments Чайка" · "Chaika Tower"
  │                     each with the agency + source_url that used it
  ├── Unit              one physical apartment: floor 7, 78 m², 2 beds, south
  │     └── Offer       one agency's listing of that unit, at its price   [VENDORED]
  └── ProjectMembership  offer ↔ project, with confidence + evidence
```

**Why join tables, not foreign keys on `Offer`:** adding a column to a vendored model breaks the
parity discipline broker-crm established. `ProjectMembership(project, offer, confidence, matched_by,
evidence)` lives entirely in our app and records *why* we believe this offer belongs to this building.

**`Project`** — `canonical_name` · `slug` · `developer` (ЕИК, FK to the Pocket Broker entity graph) ·
`address` · `lat/lng` · `neighbourhood` · `stage` (Акт 14 / 15 / 16 / завършен) · `completion_date` ·
`floors_total` · `units_total` · `construction_type` · `evidence` (jsonb) · `confirmed_by_human`

**`Unit`** — `project` (nullable; a resale flat belongs to none) · `floor` · `area_m2` · `bedrooms` ·
`exposure` · `dedup_key` · `status` (free / reserved / sold)

---

## Project identity — the hard problem

Name matching **cannot** solve this. *"Небостъргач"* vs *"Луксозни апартаменти"* scores near zero on
any string metric, and those were the same building. `bg-realestate-intel/crawlers/normalize/new_buildings.py`
clusters by fuzzy name at threshold 0.82 — **reusable as one signal, never as the decider.**

| Signal | Weight | Why it works |
|---|---|---|
| **Shared image `sha256`** | decisive | Developers hand every agency the same render pack. `OfferImage.sha256` already exists, unique-constrained. One shared render ⇒ same building. |
| **Perceptual hash (dhash)** | strong | Catches the same render re-compressed, resized, or watermarked with an agency logo — the common case |
| **Geocode < 50 m + street address** | strong | Independent of marketing name entirely |
| **Developer ЕИК** | strong | Търговски регистър via Pocket Broker's graph |
| **Акт stage + completion quarter agree** | moderate | Two "projects" at Акт 15 completing Q3 2027, 40 m apart, are one project |
| `floors_total` / `units_total` agree | moderate | |
| Fuzzy name (post-translit, stopwords stripped) | weak corroborator only | "комплекс", "жилищна сграда", "residential", "apartments" stripped first |

**Third-party anchor:** `bg-realestate-intel/crawlers/scraper_kit/sites/novitesgradi.py` already
scrapes developments with name, developer, neighbourhood, Акт stage, completion year, floors and
materials. Crawl it for Varna as a **canonical project registry** — both agencies' listings then anchor
to the same external record instead of to each other, turning a hard many-to-many problem into two
easy one-to-many ones.

**Governing rule, carried from `signals/match.py`:** *"a false flag is worse than a miss."* Auto-merge
only on a decisive signal (shared image hash, or geocode + developer agreement). Everything else is
proposed, queued and human-confirmed — `Project.confirmed_by_human`. Same flag-don't-merge philosophy
`crm/dedup.py` already uses.

**This makes image crawling load-bearing.** broker-crm's README admits "photos currently come from an
import rather than a crawl of their own." Project clustering depends on real image bytes, so image
crawling moves into Phase 3. Reuse `seaside/crawler/images.py` + `imageproc.py` (incl. the Google Drive
`thumbnail?id=…&sz=w1600` fix — `uc?export=download` returns a virus-scan interstitial, not bytes).

---

## Access policy

**`CRAWL_RESPECT_ROBOTS = False`.** Gabe's call, and the reasoning is recorded in the repo: without
the data there is no business to negotiate with. The sequence is deliberate — build the aggregator,
prove it works, then approach the agencies for a direct API feed. Chicken first.

Three engineering consequences that follow from that decision rather than argue with it:

1. **Politeness is now self-interest, not courtesy.** A banned IP yields zero data — the exact
   outcome we're avoiding. Keep per-site rate limits (1–3 s), a single worker per host, crawl
   overnight, and back off hard on the first 429/503. Slow and unnoticed beats fast and blocked.
2. **Still *record* every robots verdict — just don't obey it.** `AgencyProbe.robots_allowed` and
   `robots_disallow` already exist. That record becomes **the API-negotiation call sheet**: the
   agencies that objected loudest are the first calls to make, and knowing what they tried to
   restrict is leverage in the conversation.
3. **The line that stays:** no defeating CAPTCHAs at scale, no logins, no paywalls, no credential
   reuse. `matching/channel_b/guards.py` already records `status=captcha` and moves on — keep that.
   Public pages are a business risk; authenticated ones are a different category.

**Real exposures to price in, not to be talked out of:**
- **EU sui generis database right** (Dir. 96/9/EC, in Bulgarian law) — protects a substantial extraction
  from someone's database independently of copyright. The most likely basis for a cease-and-desist.
- **Photos and description text are copyrighted.** This is the cheapest risk to defuse: store hashes
  for clustering, display a thumbnail with attribution, and **link out to the agency for the full
  listing**. Re-hosting full galleries is what actually draws takedowns.
- **GDPR** on agent names, phones and emails — collect only what the product needs.
- Keep `docs/LEGAL.md` (seaside has a template) current; it is a diligence question an investor
  will ask, and "we know exactly what we're exposed to" is a better answer than "we assumed it was fine."

---

## Crawl rules — bought with prior mistakes

From `realEstate seaside monitoring/docs/RESEARCH.md`, `Agents/Projects/bg-realestate/research/`,
and `bg-realestate-intel` commit history. Each one a bug that already cost time:

1. **Hash contents, never bytes.** Google rebuilds xlsx on every export → on 2026-09-14, 17 of 29
   sources reported a change when 4 had been edited. Use `content_sha256` + the `VOLATILE` skip-list.
2. **Never put price in an identity key** without also keeping a price-free `weak_core`. 157 of 1,150
   seaside offers had price in their fingerprint — every price cut killed one offer and minted a fake "new" one.
3. **Cross-agency duplicates are the product. Cluster, never merge.** The price spread is the point.
4. **Validate reference numbers before using them as identity.** `ДЕПОЗИТ` and `REF -` appear in ID
   columns; trusting them silently merges unrelated apartments.
5. **Force encoding per site.** imot.bg is `windows-1251`; imoti.net is UTF-8. Never assume BG ⇒ cp1251.
6. **Look for the JSON API first.** For WordPress agencies (most of this list): `/wp-json/wp/v2/estate`
   gives ids/slugs/taxonomies — **but ACF fields (price, beds, area) are not `show_in_rest`**, so the
   rendered page must be fetched too. Paginate on `X-WP-TotalPages`. Template: `seaside/migrate/wp_fetch.py`.
7. **Verify against a live page before writing a parser.** See the Bulgarian Properties warning below.
8. **Every run gets its own output file (run-id) + stats sidecar.** Two runs on one day truncating each
   other was a recurring data-loss bug.
9. **Record blocks, never bypass them.** CAPTCHA → `status=captcha`, move on. Keep `NO_INDEX` and the
   blocked-site dict visible rather than forgotten.
10. **Rooms ≠ bedrooms.** `двустаен` / `2-комнатная` is a **one-bedroom** flat. Map `n − 1`.
11. **Rentals and parking spaces hide in sale lists** — the cheap end of any naive sort is nonsense.
12. **Don't trust an index page for coverage.** `/novo-stroitelstvo` statically renders ~5 featured
    items. Walk the sitemap; log discovered-vs-stored counts every run.
13. **Thousands separators** may be space, NBSP, thin space, dot or comma, glued to Cyrillic — and
    **Cyrillic letters are word characters**, so `\b` lookaheads fail on `000Евро`.
14. **Dump, don't copy, a live database.**

---

## Build plan

### Phase 0 — Repo, versioned from the first commit
`~/Dev/varna-market`, `git init` immediately. Postgres `varna_market` with `pg_trgm`, `unaccent`,
`btree_gin`. Django 6.1 + psycopg3 (match broker-crm; no new stack). `.env.example`,
`CRAWL_RESPECT_ROBOTS=False` with the rationale in a comment, contactable UA string.

### Phase 1 — Vendor the engine, prove parity
Copy `sourcing/` (incl. its own `vendor/`), `crm/dedup.py`, `crm/features.py`, `crm/geo.py`, and the
`matching/` engine. Record both hops in `sourcing/vendor/UPSTREAM.md` with checksums; port
`test_vendor_parity.py` so edits fail the suite unless deliberately re-recorded.
**Gate:** vendored tests green, `crawl_sites --offline` runs.

### Phase 2 — Varna agency registry + reconnaissance
Seed `Agency` rows from the trust research already done — the ~24 agencies scoring >4.0 or holding
НСНИ membership. Revolution Estate (2.95★, blacklisted for fake listings) is **excluded, with its
reason recorded** — that record is part of the pitch.

Known domains: `matex.bg` · `roneva.bg` · `titanproperties.bg` · `samhome.bg` · `demos2000.com` ·
`investtime.bg` · `adres.bg` · `home2u.bg` · `kupiv.bg` · `imoteka.bg` · `topimmo.bg` · `votchina.eu` ·
`expressimoti.bg` · `icentervarna.bg` · `ekipat.bg` · `imotipremier.com` · `yavlena.com` ·
**`bulgarianproperties.com`** · RE/MAX Active / Ideal / Dream. Needs domain recon: Темпо Естейт,
Екип SART, Имотмедия, Имоти Дар, Арена Консулт, Bulgaria Avenue, Admiral, Home Place Properties,
XNVD, Нов Дом 1.

> ⚠️ **Bulgarian Properties is the site we already got wrong — the rule-7 test case.**
> `bg-realestate-intel/crawlers/scraper_kit/sites/bulgarianproperties.py` is a deliberate
> non-implementation. Its predecessor invented a `RNT-#####` detail pattern and "Act 16 / 2025" labels
> from **404 pages read while the Read cache was serving stale content**, and `/realestates/newdev` —
> the listing URL it was built on — does not exist. It was deleted rather than shipped. Every URL
> pattern for this site gets opened in a browser and confirmed before a line is written.
>
> Offsetting asset: `/Users/gabe/Dev/realestate-mvp/test data/extractor.py` already parses a **saved BP
> Varna page** into per-project avg/min/max EUR with counts and links — a verified reading of BP's real
> structure, confirming BP publishes **project-level pages**. First-class source for Phase 5b, not just
> offer volume. BP is national, so `include`/`drop` patterns must scope it to Varna.

Output: **`docs/crawl-map.md`** — per agency: catalogue URL, sitemap, listing pattern, platform,
**robots verdict (recorded, not obeyed — this is the future API call sheet)**, encoding, estimated
stock, and whether the site exposes project pages separately from unit pages.

### Phase 3 — Site recipes, first crawl, images
Write `RECIPES` entries (~5 lines each); un-indexable agencies go in `NO_INDEX` **with the reason**.
Extend `sourcing/web/labels.py` to capture project-level fields agencies publish on unit pages:
building/complex name, Акт stage, completion date, developer, total floors. Crawl images for real.
One worker per host, 1–3 s spacing, overnight schedule, hard backoff on 429/503.
**Gate:** ≥2,000 Varna offers; price/area/location fill ≥90%; ≥1 image for ≥80% of offers; zero hosts
returning sustained 429.

### Phase 4 — Varna geography
`crm/geo.py` knows Varna only as a *resort*. City search needs **neighbourhoods**. Reuse
`bg-realestate-intel/data/raw/transport/varna_neighbourhood_coords.json` — **71 already-geocoded,
verified Varna neighbourhoods**. Build a gazetteer (Чайка, Левски, Бриз, Гръцка махала, Аспарухово,
Виница, Младост, Владислав Варненчик, Централна част …) with aliases and Latin spellings; add
`latitude`/`longitude`; geocode free-text location → neighbourhood. Load `varna_current_2026-06.jsonl`
(183 records) + 22 years of history for a €/m² benchmark under each result.

### Phase 5 — Clustering
**5a — Units.** Wire vendored `dedup.py` so one flat listed by five agencies is one `Unit`.
**5b — Projects.** Build the signal pipeline above: image sha256 → dhash → geocode+developer → stage
agreement → fuzzy name. Crawl novitesgradi.bg for Varna as the canonical anchor. Auto-merge only on
decisive signals; everything else queues for human confirmation.
**Gate:** the skyscraper case — two agencies, two unrelated marketing names, one building — resolves to
one `Project` with two `ProjectAlias` rows.

### Phase 6 — Buyer profile & matching
Re-point the vendored engine from *broker enters a client* to *buyer enters himself*.
- `BuyerProfile` replacing `Client` — email or anonymous session, no broker workflow fields
- Profile intake: budget ±tolerance, beds, area target, neighbourhoods (with `allow_adjacent` from
  `geo.py`), floor rules, **must-haves / nice-to-haves / deal-breakers**, free-text brief
- `matching/engine.py` scores the whole corpus; `Candidate` rows carry `score`, `confidence`, `band`
  (exact / unverified / near) and `score_breakdown`
- **Standing search**: re-run nightly after the crawl, email what's new or price-dropped
- `MatchFeedback` — a rejection with a reason tunes the profile; `CriteriaSuggestion` proposes edits
  ("you've rejected 4 ground-floor flats — exclude them?")
**Gate:** a profile with a deliberately blank field still returns that flat, marked *unverified*
rather than dropped.

### Phase 7 — Public API
Faceted `/api/offers/`: `deal_type`, `price_min/max`, `beds`, `area_min/max`, `floor`,
`neighbourhood[]`, `features[]`, `sort`, cursor pagination — anonymous. Results return **mixed cards**:
resale units and project clusters in one ranked list. Plus `/api/projects/<slug>/`, `/api/units/<id>/`
(every agency's price + spread), `/api/agencies/` + `/api/agencies/<slug>/`, `/api/facets/`,
`/api/profile/` + `/api/profile/matches/`.

### Phase 8 — Frontend
Vue 3 + Vite + Pinia (Gabe's stack; no Tailwind, no React). Neo-Memphis tokens from
`bg-realestate-intel/frontend/src/styles/tokens.css` so it reads as the same company as Pocket Broker.

- **Search** — filter rail + results, facet counts live per keystroke (`matching/preview.py` pattern).
  New-builds collapse into project cards by default; resale flats stay individual.
- **Unit card** — photo, price, €/m², beds, area, neighbourhood, agency badge, and the differentiator
  pill: **`Listed by 5 agencies · €18,000 spread`**
- **Project card** — `ЧАЙКА RESIDENCE · Акт 15 · Q3 2027 · 14 floors · 86 units · 2-bed from €118k ·
  4 agencies`, with alias line *"also marketed as …"*
- **Project detail** — unit table (floor / area / beds / exposure / price per agency / status),
  filterable in place; stage timeline; €/m² vs neighbourhood benchmark; **developer panel linking to
  the Pocket Broker ownership graph and court record**
- **Buyer profile** — `CriteriaEditor.vue` + `FeaturePicker.vue` + `LocationPicker.vue`, then a ranked
  match list using `MatchCard.vue` / `ScoreRing.vue` / `BandPill.vue`, and **`WhyPanel.vue` — the demo
  moment: why this flat matches you, and what we're unsure about**
- **Agency directory** — `/agencies` with offer counts, neighbourhoods covered and trust signals
  (НСНИ, rating, years); `/agencies/<slug>` with active offers, projects represented, price positioning
- **Trust strip** — "N vetted agencies · M offers · last crawled HH:MM · 0 portal listings"

### Phase 9 — The "no fakes" proof
The investor's first question is *how do you know they're real?* Make it a screen: every offer links to
the agency page it was read from with a fetch timestamp (the `evidence` blob already exists on `Offer`);
every cluster is inspectable; admission criteria and the exclusion list are public.

### Phase 10 — Deploy
VPS + nginx + gunicorn + systemd timer for the nightly crawl (Gabe's established pattern; broker-crm
has none). Cost-gate the expensive half of the pipeline on one shared verdict module so cron and any UI
button cannot drift (`seaside/crawler/verdict.py`).

---

## Verification

| Phase | Check |
|---|---|
| 1 | Vendored suite green; `test_vendor_parity` fails on an unrecorded edit |
| 2 | Every `crawl-map.md` row opened in a browser — no entry inferred from a 404 |
| 3 | Discovered-vs-stored counts logged per agency; a silent coverage collapse is visible |
| 3 | Fill rates price/area/location ≥90%; zero offers with price inside their fingerprint |
| 3 | No host returning sustained 429/503 across a full run |
| 4 | Every offer resolves to a Varna neighbourhood or is explicitly flagged unlocated |
| 5a | A known cross-agency duplicate renders as **one** card showing all agencies |
| 5b | **The skyscraper test:** two differently-named listings of one building resolve to one `Project` |
| 5b | Searching "2-bedroom" returns a tower **once**, not forty times |
| 6 | A profile with a blank field still returns that flat, marked *unverified* rather than dropped |
| 6 | Rejecting 3 ground-floor matches produces a `CriteriaSuggestion` to exclude them |
| 8 | Clicking an agency shows only that agency's active offers |
| 9 | Every displayed offer reaches its live source page in one click |
| 10 | First post-deploy crawl reporting `NEW 0 · CHANGED 0` proves history survived the move |

## Open questions

- **Resale buildings.** Project clustering targets new-builds. Five resale flats in one 1970s block
  stay individual results — nobody shops a panel block as a "project". Revisit if the data disagrees.
- **Photo handling.** Thumbnail + attribution + link-out is the low-risk default and costs nothing
  visually. Confirm before building the gallery.
- **Pocket Broker coupling.** The developer panel is a genuine fusion point: this product finds the
  building, Pocket Broker says whether the developer can be trusted. Separate brand, or one product?
