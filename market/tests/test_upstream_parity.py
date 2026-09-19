# -*- coding: utf-8 -*-
"""Hop 2 of the vendoring chain, guarded the way hop 1 already is.

sourcing/tests/test_vendor_parity.py protects the seaside -> broker-crm copy
and arrived here untouched. These tests protect the broker-crm -> varna-market
copy, so a fork of the crawler has to be a recorded decision rather than a
file that quietly stopped matching.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from market import upstream


class ManifestTests(SimpleTestCase):
    def test_manifest_exists(self):
        self.assertTrue(
            upstream.MANIFEST.exists(),
            'docs/VENDOR-MANIFEST.md is missing -- run `manage.py vendor_record`')

    def test_manifest_covers_every_vendored_file(self):
        recorded = set(upstream.manifest_rows())
        on_disk = set(upstream.local_files())
        self.assertEqual(
            on_disk - recorded, set(),
            'vendored files are not in the manifest -- run `manage.py vendor_record`')

    def test_no_file_drifted_from_its_recorded_checksum(self):
        drifted, missing, _unrecorded = upstream.compare()
        self.assertEqual(drifted, [], 'edited without declaring a divergence')
        self.assertEqual(missing, [], 'recorded but no longer on disk')

    def test_every_divergence_carries_a_reason(self):
        for path, reason in upstream.DIVERGENCES.items():
            self.assertTrue(reason and reason.strip(),
                            f'{path} is declared diverged with no reason given')
            self.assertTrue((Path(settings.BASE_DIR) / path).exists(),
                            f'{path} is declared diverged but does not exist')


class ProvenanceTests(SimpleTestCase):
    def test_every_vendored_file_names_where_it_came_from(self):
        for path, (_lines, _digest, origin) in upstream.manifest_rows().items():
            self.assertTrue(origin, f'{path} has no upstream origin recorded')

    def test_client_data_never_enters_the_manifest(self):
        """broker-crm's client's own partner registry is not ours to carry."""
        for path in upstream.manifest_rows():
            self.assertNotIn('assets/', path)
            self.assertNotIn('agencies.json', path)
