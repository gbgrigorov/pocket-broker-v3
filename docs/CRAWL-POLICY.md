# Crawl policy

## Sofia expansion checkpoint — 2026-09-26

The cohort is Bulgarian Properties, Yavlena, Home2U, LUXIMMO and ARCO Real
Estate. Public catalogues, city filters, pagination, encoding and excluded
candidates are recorded in `sofia-crawl-map.md`. Every import creates a
city-scoped SiteProbe containing robots verdicts, requests and outcomes.
Existing robots configuration is unchanged. Sofia adapters use public GET
requests without authentication and stop at the first 401/403/429/503 or page
challenge. One worker per host, conservative spacing and existing
access-control boundaries remain.
Do not reuse the agency-wide retirement helper for a partial city crawl: phase 3
must establish complete valid coverage and scope retirement by agency AND city.
All five Sofia adapters disable missing-offer retirement entirely. An exact Sofia offer can be deactivated only on positive own-page or own unit-row sold/reserved evidence, with individual history. Missing, errored or blocked pages do not justify deactivation.
An interrupted or blocked source cannot justify mass inactivation. The existing
50% discovery guard alone is not enough to certify a future Sofia adapter.

What this crawler does, what it refuses to do, and why — written down because
`CRAWL_RESPECT_ROBOTS=False` is a decision someone will eventually ask about,
and "we never thought about it" is the wrong answer.

## The decision

**We do not treat robots.txt as a blocker.**

The agencies in `docs/crawl-map.md` publish their catalogues on the open web.
We have no relationship with them yet, and without their data there is no
product to bring them. The sequence is deliberate:

1. Aggregate the market and prove the thing works.
2. Go to the agencies with a working product and negotiate a direct feed.

An API arrangement is the goal, not the starting point. Chicken first.

## What that does not license

The line is **public pages vs. access controls**, and it does not move:

| | |
|---|---|
| ✅ Public catalogue and listing pages | Anyone with a browser sees these |
| ✅ Public sitemaps and `/wp-json` endpoints the site serves openly | |
| ❌ Logins, member areas, paywalls | Authentication is a boundary, not an inconvenience |
| ❌ Solving or bypassing CAPTCHAs | A CAPTCHA is an explicit refusal. Record `status=captcha`, skip the host. |
| ❌ Credential reuse of any kind | |
| ❌ Working around an IP block | If a host blocks us, it is recorded and abandoned for the run |

`matching/channel_b/guards.py` (vendored) already records CAPTCHAs rather than
defeating them. That behaviour stays.

## Rate limiting is self-interest, not courtesy

A banned IP yields zero data, which is precisely the outcome this policy exists
to avoid. So:

- **One worker per host.** Concurrency is across hosts, never within one
  (`CRAWL_WORKERS=4`, `CRAWL_HOST_DELAY=2.0`).
- **Hard backoff.** `CRAWL_BACKOFF_LIMIT=3` consecutive 429/503 responses and
  that host is dropped for the rest of the run.
- **Overnight.** The daily crawl runs when the agencies' own traffic is lowest.
- **Sitemap diffing.** After the first pass we fetch only what `<lastmod>` says
  changed — roughly a dozen requests a day per site, not a full re-walk.

Slow and unnoticed beats fast and blocked.

## robots.txt is recorded, just not obeyed

`AgencyProbe.robots_allowed` and `robots_disallow` are populated on every probe
regardless of the setting. That record has a second job: **it is the API
negotiation call sheet.** An agency that explicitly disallowed crawling is the
first call to make, and knowing what it tried to restrict is context for that
conversation rather than a surprise in it.

## Known exposures

Not reasons to stop; reasons to know what we are carrying.

- **EU sui generis database right** (Dir. 96/9/EC, in Bulgarian law). Protects a
  substantial extraction from someone's database independently of copyright.
  The most likely basis for a cease-and-desist, and the one to take seriously.
- **Copyright in photos and description text.** The cheapest exposure to defuse,
  and the default here does: we store image hashes for clustering, show a
  thumbnail with attribution, and **link out to the agency for the full
  listing**. Re-hosting entire galleries is what actually draws takedowns.
- **GDPR** on agent names, phones and emails. Collect only what the product
  needs, and nothing that identifies a private seller.
- **Agency opt-out.** `Agency.crawl_opt_out` is honoured immediately and
  permanently. An agency that asks to be removed is removed the same day.

## Review

Revisit when: the first agency makes contact, the first direct API feed lands,
or the crawl expands beyond Varna. Whoever changes `CRAWL_RESPECT_ROBOTS`
updates this file in the same commit.
