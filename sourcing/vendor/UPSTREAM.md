# Vendored crawler modules — upstream manifest

Source repo: `/Users/gabe/Dev/realEstate seaside monitoring`  (git `gbgrigorov/seaside-monitor`)
Upstream commit at copy time: `8fa489e`
Copied: 2026-09-17

These files are **byte-identical copies**. They are deliberately not
refactored, not converted to relative imports, and not made Django-aware.
`vendor/__init__.py` (ours, not copied) puts this directory on sys.path so
the upstream flat imports resolve unchanged.

`tests/test_vendor_parity.py` re-checks these checksums and re-parses real
sheets, so drift fails the test suite rather than going unnoticed.

| file | lines | sha256 (first 16) |
|---|---|---|
| `xlsx_reader.py` | 145 | `c90e9c1d2478a051` |
| `vocab.py` | 145 | `8054a2ce9ef81a67` |
| `normalize.py` | 700 | `f5b8b00f3ff4a6be` |
| `parse_registry.py` | 170 | `348f040b8fa78957` |
| `fetch.py` | 115 | `af54f816c004a66e` |
| `phones.py` | 54 | `a51e14aaf3969e37` |

`sourcing/assets/Морски фирми-1.xlsx` is a copy of the same file upstream —
the client's own 42-agency registry, sha256 `f54a11c41d5a0be2`.

## Deliberate local changes

_None yet._ Any change must be recorded here with its reason, and the
parity test's expected checksum updated in the same commit.
