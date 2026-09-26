# Buyer workflow — 2026-09-26

Implemented and published at `https://pb3.avaflow.xyz` using the existing Vue app
and Django offer data. No migrations, crawler runs, or supply-data changes were
needed. The older `varna.avaflow.xyz` service was not restarted or modified.

## User journey

1. **Потребител** (`/user`): choose city, buy/rent, apartment/house, total rooms,
   price range (monthly for rent), minimum area and multiple neighbourhoods.
   Enter optional household/family status, children and pets. Select required
   lift, parking, garden, furnishing or readiness (Act 16).
2. Save the profile and open **Оферти за теб** (`/for-you`). Matches use current
   active agency listings, ordered by the share of requirements confirmed by
   published data. Each card explains the matching criteria and missing facts.
3. Add an offer to **Желани имоти** (`/wishlist`). Favourite controls also appear
   on ordinary search results and offer detail pages. The wishlist reloads live
   prices and availability; inactive/deleted entries remain visible and removable.

## Persistence and privacy

Profiles and wishlist entries persist in localStorage on this browser/device,
including across reloads and later visits. Another tab on the same origin stays
in sync through storage events. Storage failures show an error and do not claim
that saving succeeded. A profile can be deleted in the user tab. Clearing browser
storage clears both the profile and wishlist. The wishlist is limited to 200
entries and stores stable offer IDs and a fallback title, not copied inventories.

This is an anonymous workflow; there is no login or cross-device synchronization.
Family status and children stay on the device and help users choose explicit
property requirements. They are not sent to the matching API, used to guess
landlord policies, or shared with agencies. Pet permission is checked for rentals
only when the buyer has pets. No leads, notifications or agency messages are sent.

## Matching rules

- City and sale/rent scope are mandatory. Known violations of property type,
  room count, price, minimum area, selected neighbourhoods or required features
  remove an offer from the recommendations.
- Bulgarian room counts include the living room: two rooms means one bedroom
  plus a living room. Explicit property type is used first; bedrooms + 1 is the
  fallback when total rooms are unavailable.
- Missing facts remain eligible and are explicitly labelled **За проверка**.
  Confidence is the weighted fraction of requirements with affirmative evidence,
  not a probability that a buyer will like a home. Fully documented results rank
  ahead of incomplete results; recency and offer ID break ties consistently.
- Multiple selected neighbourhoods are alternatives within the chosen city.
  Unknown neighbourhoods remain eligible and are marked for confirmation.
- Explicit pet bans exclude rentals for pet-owning buyers. No pet statement means
  unconfirmed. Buying a property does not imply landlord permission is required.
- Negative feature statements, including no lift, no parking and no garden, do
  not become positive matches. Before/expected Act 16 does not count as ready.
- Matching runs on request, with 24 results per page. It does not imply new
  inventory has been crawled or that nightly alerts are scheduled.

Sofia currently has no active offers. Profiles for Sofia can be saved, with an
honest empty state until active supply is available. Varna supplies real matches.

## API and checks

`GET /api/buyer/options/` supplies feature labels and a CSRF token.
`POST /api/buyer/matches/` accepts `{ "profile": {...}, "page": 1 }`.
`POST /api/buyer/wishlist/` accepts `{ "ids": [123] }` and returns active results
and unavailable IDs. These endpoints are read-only, validate inputs, require
CSRF protection for POST, and disable response caching. No model/session rows
are written by this workflow.

Validation: 172 Django tests passed, with 3 existing skips. This includes 11 new
tests covering room semantics, city/deal boundaries, price/area/multiple quarters,
missing facts and ranking, negative features and future readiness, pets, invalid
inputs, pagination, unchanged supply, live wishlist data and CSRF protection.
System checks, migration drift detection, vendoring checks and production build
passed. Browser smoke checks cover profile reload, household fields, city changes,
Varna results, favourites on matching/search/detail screens, wishlist reload and
removal, unavailable entries, 390px layout, storage errors and runtime errors.

Browser check (requires an installed Playwright module and Chromium):

```bash
PLAYWRIGHT_MODULE=/path/to/playwright \
BUYER_SMOKE_URL=https://pb3.avaflow.xyz \
node frontend/tests/buyer-smoke.cjs
```

Publishing used `collectstatic`, rsync to `/var/www/pb3/static/`, and
`pm2 restart pb3`. Existing generated assets were retained for browsers holding
an older bundle. No pull, dependency installation or database migration was
performed during this release.
