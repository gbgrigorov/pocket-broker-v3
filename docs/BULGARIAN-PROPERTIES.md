# Bulgarian Properties: saved Sofia reconnaissance

This note records what is present in the saved responses under
`data/recon/bulgarian-properties/`. It is source reconnaissance, not a
production-ready recipe or a claim about complete stock. The responses were
captured on 25 September 2026. No additional requests were made while writing
this note.

The caution in `PLAN.md` applies especially to this source. An earlier scraper
invented a detail URL shape from stale 404 content and used the nonexistent
`/realestates/newdev` page. Everything below is tied to a saved HTTP response
and its markup.

## Responses actually verified

| Saved response | HTTP | What the response demonstrates |
| --- | ---: | --- |
| `Properties_in_the_town_of_Sofia/index.html` | 200 | Sofia **city** mixed sale/rent catalogue, page 1 |
| `Properties_in_the_town_of_Sofia/index1.html` | 200 | Same catalogue, page 2 |
| `Properties_in_the_town_of_Sofia/index2.html` | 200 | Same catalogue, page 3 |
| `Sofia_property/index.html` | 200 | Sofia **region** mixed catalogue; its H1 is “Property in Sofia region for sale and rent” |
| `sofia-properties.html` | 200 | “Sofia apartments” catalogue/SEO route; it includes the same kind of region stock, including `near_Sofia` cards |
| `properties-for-rent-in-Sofia.html` | 200 | Sofia rental catalogue; all 30 saved result cards say “For rent” and show monthly prices |
| `AD91504BG_1-bedroom_apartment_for_sale_in_Sofia.html` | 200 | Individual resale offer, €275,000 in the saved response |
| `AD91674BG_1-bedroom_apartment_for_rent_in_Sofia.html` | 200 | Individual rental offer, €700 in the saved response |
| `AD82111BG_Apartments_(various_types)_for_sale_in_Sofia.html` | 200 | Multi-unit development/project offer, SKY TOWERS |
| `/robots.txt` | 200 | Robots rules and an advertised sitemap URL |
| Advertised `http://www.bulgarianproperties.com/sitemap.xml` | 404 after redirect to HTTPS | The advertised sitemap is not usable in this capture |
| `/` | 200 | Site home page only; it is not catalogue evidence |

The status and URL pairs above come from the adjacent JSON sidecars, while the
structural findings come from the corresponding HTML files. A 200 response is
only evidence that the captured page existed; it does not establish current
availability or full coverage.

## Catalogue scope

`/Properties_in_the_town_of_Sofia/` is the strongest saved city-scoped source.
Each of its first three saved pages has 30 result-card containers. Across those
90 card slots, no card detail URL contains `_near_Sofia`. By contrast,
`/Sofia_property/index.html` and `/sofia-properties.html` each contain three
result cards whose detail URLs contain `_near_Sofia`, including AD82112BG,
AD90912BG and AD90197BG. These are region/near-city pages and must not be used
as the Sofia-city catalogue without an explicit exclusion.

For a Sofia city crawl:

- start from `https://www.bulgarianproperties.com/Properties_in_the_town_of_Sofia/index.html`;
- accept only links found inside a result-card container;
- explicitly reject detail paths containing `_near_Sofia` even when another
  signal calls the locality Sofia;
- retain the card/detail locality and coordinates for later geographic
  validation rather than treating the catalogue path as final proof.

That last check matters because the first saved city page has one card whose
JSON-LD `addressLocality` is `Ivanyane`, while the other 29 say `Sofia`. Page 3
similarly contains one `Bistrica` locality. The detail filenames for those
cards still use `_in_Sofia`. The city catalogue is a useful source boundary,
but the site's own locality labels need normalisation against Pocket Broker's
geography.

The rental route is a genuine catalogue, not an SEO list: the saved page has
30 `component-property-item` cards, 30 card-level JSON-LD blocks, “For rent” on
all 30 cards, and prices such as `€350/month`. The mixed city page is also real
inventory: its saved first page contains 23 sale cards and 7 rent cards. Those
figures describe only the captured page and must not be presented as source
stock counts.

## Pagination is zero-offset in the filename

The page-number mapping is exact and differs from the old Varna assumption in
`market/sources.py`:

| Human page | URL suffix |
| ---: | --- |
| 1 | `index.html` |
| 2 | `index1.html` |
| 3 | `index2.html` |
| N | `index{N-1}.html` |

The evidence is both the active pagination markup and the contents: page 1
links label `index1.html` as “2”; page 2 marks “2” active and links
`index2.html` as “3”; page 3 marks “3” active. The three saved pages have
disjoint card identifiers. Therefore a formatter that substitutes `1` for the
first page will skip the real first page, and one that treats `index1.html` as
page 1 will silently shift the crawl.

Do not copy this suffix rule blindly to the other routes. The saved
`sofia-properties.html` page advertises `sofia-properties1.html` as its next
page, and the rental page advertises `properties-for-rent-in-Sofia1.html`.

## Discover only result cards

A catalogue result is delimited by:

```html
<div class="component component-property-item "
     data-preference-prop-id="77779" id="77779">
```

Within that container, the primary image/title links point to the detail page,
the standard label gives `For sale` or `For rent`, and the HTML carries price,
area, property type, location and agent data. A sibling
`<script data-id="77779" type="application/ld+json">` supplies structured
residence data such as name, area range, room values, address, coordinates and
detail URL. It does not consistently carry the card price.

Do not harvest every anchor matching `AD\d+BG_` from the document. On the saved
city page 1 there are 66 distinct matching detail anchors but only 30 result
cards. The other 36 occur in recommendation, promotional or SEO sections. In
particular, the city page contains recommended villas and houses “near Sofia”
outside the result list even though none of its 30 actual cards has a
`_near_Sofia` URL. The rental page similarly has 77 distinct matching anchors
for 30 actual cards. A page-wide regex would mix unrelated recommendations
into the catalogue and distort sale/rent and city coverage.

The stable detail-path identifier observed throughout the saved evidence is
`AD<digits>BG_`, for example `AD91504BG_`, `AD91674BG_` and `AD82111BG_`.
The same digits appear as `data-preference-prop-id`, element `id`, the
card JSON-LD `data-id`, detail-page `content_refno`, and analytics
`listing_id`. Use the numeric portion as a source reference only after the URL
matches `AD\d+BG_`; do not revive the invented `RNT-#####` pattern.

## Detail pages and projects

All three saved detail pages describe the page as a schema.org `Product`, but
their nested offer types distinguish a single offer from a development:

- AD91504BG is a `Product` with one `Offer`: EUR 275000, `InStock`.
- AD91674BG is a `Product` with one `Offer`: EUR 700, `InStock`.
- AD82111BG is a `Product` with an `AggregateOffer`: EUR 252160 to 1732762,
  `InStock`. Its analytics data also names `development: 'SKY TOWERS'` and
  `development_id: '2158'`.

The saved AggregateOffer has no `offerCount`. It is evidence of a project or
multi-unit price range, not a unit count and not a set of individually
identified units. Preserve it as project-level evidence and do not manufacture
unit offers from the low/high bounds. Conversely, the single `Offer` examples
provide a concrete asking price, but `availability: InStock` is the site's
claim at capture time, not a durable live-status guarantee.

Card JSON-LD uses real-estate types such as `SingleFamilyResidence`, while
detail JSON-LD uses `Product`. An extractor should tolerate that difference
and use the surrounding page context rather than requiring one schema type.

## Encoding is unresolved in the current capture

The HTML declares `iso-8859-1` in a meta tag, the HTTP sidecars record an empty
charset (`text/html; charset=`), and several inline AJAX declarations mention
`windows-1251`. The saved English pages contain many U+FFFD replacement
characters where punctuation and some text should be; for example SKY TOWERS
uses `�` in place of a dash, and agent-office text is visibly damaged.

This capture cannot settle the source encoding because `market.recon.get()`
runs `curl` with `text=True, errors='replace'`. Python therefore decodes curl's
bytes using the process locale before `detect_encoding()` examines the body.
Any non-UTF-8 byte has already been irreversibly replaced. The present files
are suitable for ASCII markup/URL reconnaissance, but encoding conclusions are
provisional and their damaged prose must not become a parser fixture for text
quality.

The implementing agent should preserve response bytes, inspect HTTP/meta
declarations, test plausible single-byte decoders against known punctuation
and Cyrillic, and only then store decoded text. The saved replacement
characters cannot be repaired reliably after the fact.

## Robots and sitemap evidence

The saved `robots.txt` contains many disallows, including `/*search`,
`/*Print_offer`, `/*index0.html`, numerous query/filter parameters, wish-list
and sharing actions, and document/media extensions. It advertises:

```text
Sitemap: http://www.bulgarianproperties.com/sitemap.xml
```

The saved request to that URL redirects to HTTPS and ends with HTTP 404. Do not
infer a sitemap inventory from the declaration, and do not substitute a
guessed sitemap path without separately recorded evidence. Under
`CRAWL-POLICY.md`, these robots rules are recorded rather than treated as the
crawl switch; the public-page/access-control boundary, one-worker pacing and
backoff rules still apply.

## Implementation implications still requiring fixture work

This reconnaissance supports a future adapter, but it does not certify one.
Fixture tests should prove the page-offset mapping, card-bounded discovery,
city exclusion of `_near_Sofia`, sale/rent classification, `Offer` versus
`AggregateOffer`, and byte-safe decoding. Coverage and retirement must remain
city-scoped. A partial page sequence, block, parse failure or region crawl is
not evidence that missing Sofia offers should be retired.


## Individual development units — verified 2026-09-26

The initial project exclusion was incomplete for full inventory. The public
AI search supplied by the user lists compound `AD77779PL212960BG` URLs; a
unit page has its own single price, area, bedrooms and floor, while its
canonical link points at `AD77779BG`. Its primary JavaScript variables
`master_IID=77779` and `master_unit_ID=212960` verify the unit identity. The
parser retains the requested compound URL and reference `77779PL212960`.

The project's own price-list button links a public GET
`/pdetail.php?IID=<AD>&xajax=1&scmd=propprice`. Its ordinary Show button
adds `searching=1&search_form=1&no_css_js=1&search_type=0&search_status=0`
and empty area/price filters. This returns the full unit table, including
AVAILABLE, RESERVED and SOLD rows. Only AVAILABLE/free rows are imported;
unit IDs, visible prices and areas are checked against that same row's
data attributes. Displayed floor headings supply the floor; `data-floor`
is an internal code and cannot be used as a numeric floor.

Full imports expand these tables; limited validation samples still leave
project summaries excluded. No units are invented from AggregateOffer bounds.
Development images are labelled as such in evidence and safely shared across
unit thumbnail records. Reduced fixtures and provenance are in
`market/tests/fixtures/bulgarian_properties/unit*`.
