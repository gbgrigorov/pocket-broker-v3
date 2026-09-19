# -*- coding: utf-8 -*-
"""Guards the claim that sourcing/vendor is a faithful copy.

"Faithful copy" is only useful if it stays checkable. These tests fail the
moment a vendored file is edited without recording the change in UPSTREAM.md,
and the moment the parser stops producing what it produced upstream.
"""
import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

VENDOR = Path(settings.BASE_DIR) / 'sourcing' / 'vendor'
MANIFEST = VENDOR / 'UPSTREAM.md'


def manifest_checksums():
    rows = re.findall(r'^\| `([^`]+)` \| (\d+) \| `([0-9a-f]+)` \|$',
                      MANIFEST.read_text(encoding='utf-8'), re.M)
    return {name: (int(lines), digest) for name, lines, digest in rows}


class VendorIntegrityTests(SimpleTestCase):
    def test_manifest_lists_every_vendored_module(self):
        on_disk = {p.name for p in VENDOR.glob('*.py')} - {'__init__.py'}
        self.assertEqual(on_disk, set(manifest_checksums()))

    def test_checksums_match_the_manifest(self):
        """An edited vendored file must be declared, not smuggled in."""
        for name, (lines, digest) in manifest_checksums().items():
            path = VENDOR / name
            actual = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            self.assertEqual(actual, digest, f'{name} changed without updating UPSTREAM.md')
            self.assertEqual(len(path.read_text(encoding='utf-8').splitlines()), lines)

    def test_vendored_code_stays_free_of_django(self):
        for path in VENDOR.glob('*.py'):
            if path.name == '__init__.py':
                continue
            self.assertNotIn('django', path.read_text(encoding='utf-8').lower(),
                             f'{path.name} has been coupled to Django')


class ParserOutputTests(SimpleTestCase):
    """Parse real sheets and assert the shape of what comes back."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from sourcing import vendor
        cls.vendor = vendor
        cls.samples = sorted(Path(settings.RAW_DIR).glob('*/*.xlsx'))

    def test_fixtures_are_present(self):
        if not self.samples:
            self.skipTest('no sheet snapshots in data/raw')
        self.assertGreater(len(self.samples), 5)

    def test_parses_real_sheets_into_records(self):
        if not self.samples:
            self.skipTest('no sheet snapshots in data/raw')
        parsed = 0
        for path in self.samples[:12]:
            slug = path.parent.name
            records, _diagnostics = self.vendor.extract_offers(
                slug, {'name': slug}, str(path), '2026-09-14')
            parsed += len(records)
            for record in records:
                self.assertIn('fingerprint', record)
                self.assertEqual(record['agency_slug'], slug)
        self.assertGreater(parsed, 50)

    def test_fingerprints_are_stable_across_runs(self):
        if not self.samples:
            self.skipTest('no sheet snapshots in data/raw')
        path = self.samples[0]
        slug = path.parent.name
        first, _ = self.vendor.extract_offers(slug, {'name': slug}, str(path), '2026-09-14')
        second, _ = self.vendor.extract_offers(slug, {'name': slug}, str(path), '2026-09-14')
        self.assertEqual([r['fingerprint'] for r in first],
                         [r['fingerprint'] for r in second])

    def test_fingerprint_ignores_price_for_strong_identities(self):
        """A price cut must read as a change, never as a new listing."""
        fingerprint = self.vendor.fingerprint
        base = {'agency_slug': 'x', 'ref': 'A-12', 'title': 'Камелия',
                'bedrooms': 2, 'area_m2': 60, 'floor': 3, 'location': 'Несебър',
                'price_eur': 100000}
        cheaper = {**base, 'price_eur': 90000}
        self.assertEqual(fingerprint(base), fingerprint(cheaper))
