# Vendoring

This project did not write its crawler. It copied one, and says so.

```
seaside-monitor          daily crawl of 42 Black Sea agency price lists
      │  hop 1  (already recorded upstream)
      ▼
broker-crm/sourcing      multi-agency aggregator for one Burgas brokerage
      │  hop 2  (recorded here)
      ▼
varna-market             public Varna market search
```

## Why copy rather than import

broker-crm is not a library, has no package boundary, and — at the time of
copying — **was not in git at all**. Depending on it would mean depending on a
directory on one laptop that changes under us. Copying makes the dependency
explicit and the divergence measurable.

## Where things live

| Path | What |
|---|---|
| `sourcing/` | Vendored from `broker-crm/sourcing`. The crawler, the `Offer` schema, ingest, extraction. |
| `sourcing/vendor/` | Hop 1, untouched: seaside's parsers, guarded by their own `UPSTREAM.md` and `sourcing/tests/test_vendor_parity.py`. |
| `crm/` | Three vendored modules — `dedup`, `features`, `geo` — kept under the package name broker-crm gave them so `from crm import features` resolves without editing a vendored line. **Not a CRM.** |
| `market/` | Ours. Clustering, buyer profiles, the vendoring machinery itself. |

Keeping vendored files at their **upstream paths** is deliberate: renaming
`crm` would have been the first divergence, and the cheapest one to avoid.

## The guard

```bash
python manage.py vendor_check              # does the copy still match the manifest?
python manage.py vendor_check --upstream   # what has broker-crm changed since?
python manage.py vendor_record             # re-record after a deliberate change
```

`docs/VENDOR-MANIFEST.md` carries a checksum per file. `market/tests/test_upstream_parity.py`
fails the build when a vendored file drifts without being declared, so a fork
has to be a decision rather than something noticed six months later.

To change a vendored file on purpose: add it to `market/upstream.py::DIVERGENCES`
with a reason, then `vendor_record`. A divergence with no reason fails its own test.

`vendor_check --upstream` answers the other direction — *what did broker-crm fix
that we should take?* — which is the only reason the origin column is worth carrying.

## What was deliberately not copied

- `crm/models.py`, `matching/`, `inbox/`, the broker Vue app — a broker's daily
  workflow. The demand-side engine (`SearchCriteria`, scoring, `MatchFeedback`)
  arrives in phase 6, re-pointed at a public buyer instead of a broker's client.
- `sourcing/assets/` and `sourcing/data/agencies.json` — **broker-crm's client's
  own partner registry**, 42 Burgas agencies. Not ours, wrong market, and
  gitignored so it cannot reach this repo's history. Pending deletion.
- `sourcing/migrations/` — regenerated against this database.

## Where the copy will diverge

Known and expected, as the phases land:

- `sourcing/web/sites.py` still holds broker-crm's 9 Burgas recipes. They are
  **inert** — the crawler iterates `Agency` rows, and this database has none of
  them. Varna recipes go in `market/` and are merged at runtime rather than
  edited in, so `sites.py` stays byte-identical.
- `sourcing/web/labels.py` will need project-level fields (Акт stage,
  completion date, developer, floor count) that a single-brokerage CRM never
  wanted. That one will be a declared divergence.
