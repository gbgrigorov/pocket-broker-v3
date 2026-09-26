# Sofia crawl map — five verified agencies

Verified 2026-09-26. The former ten-agency work queue is reduced to **Bulgarian
Properties, Yavlena, Home2U, LUXIMMO and ARCO Real Estate**. These were selected
for usable public Sofia inventory and different market coverage; this is an
operational selection, not a claim about agency rankings.

**Full import complete:** 8,170 active Sofia listings, 7,024 sale and 1,146 rent.
Every one of 6,360 distinct public catalog URLs was checked. Detailed coverage,
development units, retry lineage and exceptions:
[completed import audit](SOFIA-FULL-CATALOG-2026-09-26.md).

## Public recipes

| Agency / registry slug | Sofia catalogues | Pagination and identity |
| --- | --- | --- |
| Bulgarian Properties / `bulgarian-properties` | `https://www.bulgarianproperties.com/Properties_in_the_town_of_Sofia/index.html` (mixed sale/rent) | Actual linked `index1.html` is page 2. Numeric AD reference for standalone listings; individual development units use AD + PL reference. Full imports expand the own public price/availability tables, never the summary range. |
| Yavlena / `yavlena` | `https://www.yavlena.com/bg/sales/sofia-sofia/d23l4396`; replace `sales` with `rentals` for rent | Public SSR includes 50 cards, exact Sofia location 4396 in district 23. Verified GET `?page=1` returns the second batch, `?page=2` the third. Primary `innerNumber`, `/bg/<id>` sale and `/bg/<id>/rent` rental. |
| Home2U / `home2u` | `https://home2u.bg/nedvizhimi-imoti-sofia/`; public AJAX filter city=5, offer_type=353 for all rentals | Form city=5 (18 is Sofia region), offer_type=352 sale / 353 rent. Public GET `/wp-admin/admin-ajax.php?action=filter_properties&city=5&offer_type=352&properties_page=2&listing_type=list&lang=bg`. Full rental pagination has no property-type restriction; explicit apartment landing-page filters are preserved only when that narrower page is used. Own sticky “Код на обявата” is identity; canonical URL reconciles older references. |
| LUXIMMO / `luximmo` | `https://www.luximmo.bg/bulgaria/oblast-sofiya/sofiya-luksozni-imoti/index.html` (all kinds, mixed sale/rent) | Follow actual `index1.html` links, 24 cards per page. A card's own URL supplies sale/rent and the detail breadcrumb verifies it. Numeric `luksozen-imot-<id>` source ID differs from the public marketing reference (SOF-…, Kbs …). |
| ARCO / `arco-real-estate` | `https://www.arcoreal.bg/оферти?t=2&c=1` sale; `t=4&c=1` rent | City parameter **c=1**, not l=1; 44 is Sofia region. Source's OffersControls uses `page=2&limit=10`, verified as a distinct second page. Numeric final URL ID agrees with own title and card ID. |

Yavlena, Home2U and ARCO use UTF-8. LUXIMMO's HTTP charset is Windows-1251;
the client preserves bytes and decodes before parsing. BP keeps its already
tested charset detection and own DOM/JSON-LD unit/project extraction.

Extraction is restricted to own result wrappers and listing fields. Menus,
broker contacts, SEO locality links and recommendations do not supply facts.
Yavlena's `property.propertyData` is separated from `similarPropertiesData`.
Home2U `/project/` cards never become a flat at the development's starting
price; own locations accept either city/quarter order but reject villages and
Bankya. LUXIMMO includes nearby villages even in its Sofia apartment catalogue:
own locality must explicitly say **ГР. СОФИЯ**. Reserved listings use the own
gallery banner. A two-floor maisonette stays a unit with unknown single floor.
ARCO reads the first own euro price, excluding BGN and price-per-m² values.

Bulgarian 2-стаен means one bedroom. Unknown floors, furnishing and pet
policies remain unknown; explicit Home2U pet restrictions and furnishing facts
reach buyer matching. Only short factual flags are kept, not full descriptions
or broker biographies.

## Images and boundaries

One attributed thumbnail is downloaded per imported offer. Verified image
hosts: `static.bulgarianproperties.com`, `images.yavlena.com`,
`home2u.skyholding.media`, `static.luximmo.org` and ARCO's own `/image` endpoint.
Each agency has its own content-hashed media folder. HTTPS host allowlists are
enforced on redirects. Robots responses/disallows are recorded in SiteProbe on
each run; the existing `CRAWL_RESPECT_ROBOTS=False` policy is unchanged.

Requests run sequentially per host under advisory locks with the existing
two-second spacing. Separate agency hosts can run concurrently. A 401/403/429/503 or page challenge stops that source.
Contact-form CAPTCHAs are never requested or submitted. No logins, credentials,
paywalls, contact forms or access-control bypasses are used.

All five disable missing-offer retirement. Each adapter can deactivate
one existing Sofia offer when its own page or exact unit price-list row positively verifies it is unavailable;
they never infer removal from absence in a limited catalogue. Stable IDs, price history, retained
good fields and manual geography survive refreshes. Catalogue count drift
leaves coverage partial while valid details can still be imported. No schema
change was required; only v3's `pocket_broker_v3_phase1` database is used.

## Excluded candidates

| Candidate | Evidence / decision |
| --- | --- |
| Imoteka | Public homepage returned HTTP 403 on 2026-09-26. Host stopped; response retained; no workaround. |
| Address | Historical blocked canonical source was not advanced. Additional `adres.bg` candidate timed out after 90 seconds; it is not verified as the registry's `address.bg` site. |
| SUPRIMMO | Registry opts out of crawling; honoured. |
| Unique Estates / Sotheby's | Removed from the initial cohort; no adapter or coverage claimed. |

Raw captures and response metadata are unserved and gitignored in
`data/recon/sofia-five/`. The 25 reduced factual fixtures with source URLs,
encoding and capture checksums are in `market/tests/fixtures/sofia/`.

## Running

```bash
# Full Sofia catalogue of all five, without a detail limit:
./.venv/bin/python manage.py crawl_live --city sofia --max-pages 1000
# Validation sample; detail limit per source, pages per catalogue.
./.venv/bin/python manage.py crawl_live --city sofia --limit 20 --max-pages 2 --sample-seed 26
# A subset or catalogue-only run:
./.venv/bin/python manage.py crawl_live --city sofia --agency home2u --discover-only --max-pages 2
```

Omit `--agency` for exactly five sources, or repeat it for a subset. New-source
samples interleave sale and rent; `--sample-seed` shuffles each reproducibly.
`--no-images` skips thumbnails. Full BP runs also expand public development-unit tables. A failed unblocked detail/image/unit expansion can be retried with `manage.py retry_sofia --run <id>` after the source finishes; retry reports are subsets and retain the original run link. Blocked runs cannot be retried in the same campaign. Reports separate advertised, discovered,
fetched, stored, new, updated, skipped and errors. A limited successful import
is explicitly `partial`, never presented as full inventory coverage.

## Backup and validation

Before imports:
`backups/before_sofia_five_20260926_072951.dump`, SHA-256
`832d1d006c4d03fefd7ca6482aa283f449e9a9b3b8f1be733ad19792bbce6c84`.
Archive decode and restore into a new empty database were verified; all seven
recorded model counts matched. Restored full-row checksums are alongside the
backup. The temporary verification database was removed.

**199 Django tests passed**, with three expected skips. The 27 new tests cover
four-source sale/rent parsing, pagination, city/identity boundaries, projects
and unavailable offers, pet/room semantics, stable IDs, repricing, missing
fields, manual geography, blocks, no missing-offer retirement and single-offer
deactivation only with positive own-page evidence. Check, migration drift,
vendor check and frontend production build also passed.

## Initial live results — 2026-09-26

Latest validation sample per source (20 detail pages, two catalogue pages per
deal; Bulgarian Properties has one mixed catalogue):

| Source | Run | URLs discovered | Detail pages checked | Active offers retained | Sale / rent |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bulgarian Properties | 12 | 60 | 20 | 14 | 8 / 6 |
| Yavlena | 13 | 200 | 20 | 20 | 10 / 10 |
| Home2U | 17 | 32 | 20 | 16 | 7 / 9 |
| LUXIMMO | 19 | 96 | 20 | 17 | 8 / 9 |
| ARCO Real Estate | 16 | 40 | 20 | 20 | 10 / 10 |
| Total | | **428** | **100** | **87** | **43 / 44** |

These are samples, **not full backfills**. Every run is explicitly partial.
All four new sources finished their final sample with zero parsing, image or
block errors. BP rejected AD91649 because its own reference says Sfa 90671;
that conflicting identity remains excluded. Other exclusions: four BP projects,
one BP reserved offer; two Home2U projects and two outside-city properties;
three LUXIMMO reserved offers. Source IDs 46304 and 45721 had been imported
before the reserved gallery variant was recognised and were deactivated with
source-page evidence and history events. No missing offer was retired.

The database contains 89 newly created records from the operation, of which
87 remain active and two are now explicitly unavailable. Rechecks updated the
same IDs rather than duplicating listings. Prices and photos are present on all
87 active records, area on 86, and a seeded neighbourhood resolves for 64.
The remaining 23 quarters stay visibly unresolved; no geography is guessed.

Live API `/api/stats/?city=sofia` reports 87 offers, five agencies, 87 photos,
43 sales and 44 rentals. Browser validation of two-room Sofia sales with a
€200,000 ceiling returned 15 matching candidates (unknown facts remain marked
for checking). Desktop rendered three cards across; photos returned HTTP 200;
wishlist add/reload, inert individual/global viewing buttons and mobile layout
passed without runtime errors. The existing general buyer smoke also passed.

All **1,772 existing Varna Offer rows** remained identical across every field:
before/after SHA-256
`d55d1755519806f39778b4b6297c3723fd0b13c713532cc07856b7c580f89704`.
No old Varna process or database was changed. The v3 process alone was restarted
after validation to load apartment search support for the new Bulgarian kinds.
Run JSON and detailed source outcomes remain in unserved `data/runs/` and the
corresponding city-scoped SiteProbe records. Imoteka's block and the unverified
Address candidate's timeout also have excluded-candidate probe records.

No automated schedule was added. Further imports use the documented command;
full coverage must be measured separately rather than inferred from these samples.

## Full backfill initiated — 2026-09-26

Fresh backup: `backups/before_sofia_full_20260926_082022.dump`, SHA-256
`621f706460beece4939a6079af99d78e50d749e1b8f8899577defa9af8623749`.
Restored into a new empty database; all seven model counts **and full-row MD5
checksums** matched the original. The temporary verification database was
removed. Baseline: 2,661 offers, 141 agencies, 2,518 images, 103 offer-history
rows; 1,772 Varna offer rows retain the SHA-256 recorded above.

The user's BP AI search example contains 300 individual unit URLs across 13
developments, not 300 standalone AD listings. All 300 have now been imported
with distinct AD+PL references. Each available unit comes from its own public
price-list row: type, area, price, availability and displayed floor heading.
`data-floor` is an internal enum (e.g. 11 = Second Floor), so it is not stored
as the floor number. Development cover photos are explicitly tagged in
evidence and one downloaded file is shared by that development's units.
Canonical unit pages point at the parent development; the primary own
`master_IID` and `master_unit_ID` independently establish unit identity.
A typo in the visible marketing reference is retained as evidence only when
canonical AD identity and the own primary page ID agree.

The full catalogues have no detail limit and use a 1,000-page ceiling beyond
the agencies' observed page counts. Home2U rentals and LUXIMMO now include all
property types. The earlier 87-offer table remains a historical validation
sample, not the current stock. All five runs and their targeted recovery passes
have finished; final coverage and exclusions are in the completed import audit.
