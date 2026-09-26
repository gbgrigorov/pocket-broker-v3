# Full Sofia catalog import — 2026-09-26

Completed at 10:44 UTC on the live v3 database `pocket_broker_v3_phase1`.
All **6,360 distinct listing URLs** returned by the five public Sofia catalogs
were checked and classified. No detail limit was used. Sale and rental catalogs
include every property type, not only apartments.

| Agency | Sale | Rent | Active listings | With photos |
| --- | ---: | ---: | ---: | ---: |
| Bulgarian Properties | 3,008 | 150 | 3,158 | 3,158 |
| Yavlena | 1,099 | 433 | 1,532 | 1,532 |
| Home2U | 763 | 49 | 812 | 809 |
| LUXIMMO | 1,405 | 405 | 1,810 | 1,809 |
| ARCO Real Estate | 749 | 109 | 858 | 857 |
| **Total** | **7,024** | **1,146** | **8,170** | **8,165** |

These are agency listings, not deduplicated physical homes. All are available
through the live search, buyer matching and wishlist. Unknown price, area,
quarter and household facts remain unknown; 8,081 offers have prices and 6,585
resolve to a seeded neighbourhood. Missing facts remain visibly unverified.

## Coverage and exceptions

| Source | Catalog pages | Distinct URLs checked | Final URL outcomes |
| --- | ---: | ---: | --- |
| Bulgarian Properties | 24 | 717 | 398 standalone offers; 147 developments; 106 unavailable; 66 outside Sofia |
| Yavlena | 23 sale + 9 rent | 1,571 | 1,532 offers; 18 developments; 21 unavailable |
| Home2U | 117 sale + 7 rent | 979 | 813 offer URLs reconcile to 812 records; 116 developments; 50 outside Sofia |
| LUXIMMO | 94 | 2,235 | 1,810 offers; 146 developments; 169 unavailable; 110 outside Sofia |
| ARCO | 75 sale + 11 rent | 858 | 858 offers |

BP development tables additionally identify **4,821 individual units**:
2,760 available and 2,061 unavailable. Available units have distinct AD+PL
identities and their own published prices, areas, types and floor headings.
All **300 individual units** from the user's shared BP AI finder are present
and active. Development cover photos are labelled as such in source evidence.
Other development summaries remain excluded when they do not identify a
specific unit with its own price; starting-price ranges are never made into
individual offers. The scope is Sofia, not nationwide agency inventory.

Yavlena advertises 1,126 sale cards but repeats `/bg/168899` on page 7, leaving
1,125 distinct sale URLs. Run 37 independently traversed all 32 pages and
confirmed 1,572 returned cards, including exactly that duplicate. Five numeric
references also have separate sale and rental services. Both services now keep
distinct offer IDs and prices; the five original wishlist IDs were restored
using their original URL fingerprints. Audit history is preserved and false
cross-deal previous prices are cleared.

ARCO's own pager rounds down and omits its final partial page. The displayed
result range verifies that results remain; both final pages were fetched and
18 additional offers imported. Its one broken image remains a recorded image
error, not a failed offer import. Three Home2U listings and one LUXIMMO listing
also have no usable verified photo. All detail failures were resolved.

## Run lineage and validation

Main runs remain honestly marked partial where they initially encountered
errors. Coverage is established by the original run plus its linked retries,
not by rewriting the original report:

- BP: 25 → 28 → 29 → 30.
- Yavlena: 22 → 31 → 36; independent catalog audit 37.
- Home2U: 23 → 26 → 27; metadata repairs 38 → 40.
- LUXIMMO: 24 → 32 → 35.
- ARCO: 21 → 33; final-page recovery 34; image recheck 39.

Private reports and captured original HTML remain unserved under `data/runs`
and `data/recon/sofia-retries`. Consolidated counts and coverage are in
`data/runs/sofia-full-catalog-summary-20260926.json`.

Fresh backup before writes:
`backups/before_sofia_full_20260926_082022.dump`, SHA-256
`621f706460beece4939a6079af99d78e50d749e1b8f8899577defa9af8623749`.
A complete restore into a new empty database matched all seven model counts
and full-row checksums. No schema or configuration changes were needed.
All 1,772 Varna offer rows remain byte-for-byte equivalent across every field:
SHA-256 `d55d1755519806f39778b4b6297c3723fd0b13c713532cc07856b7c580f89704`.
The older Varna application and database were not changed or restarted.

**231 tests: 228 passed, three expected skips.** Django check, migration drift,
vendor check and frontend production build passed. Only v3 was restarted.
Live browser checks passed for profile persistence, explained Sofia matches,
three desktop columns, photos, wishlist persistence, inert Bulgarian viewing
buttons and mobile layout. A two-room Sofia sale search up to €200,000 returned
1,161 candidates, including explicitly unverified facts. Public API page 61
returns 24 distinct offers after removing the obsolete 60-page ceiling.

No automatic crawl schedule or missing-offer retirement was added.
