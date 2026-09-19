# -*- coding: utf-8 -*-
"""Insert, diff, retire -- the three behaviours the crawler had to get right."""
import datetime as dt

from django.test import TestCase

from sourcing.ingest import sync_agency_offers
from sourcing.models import Agency, Offer, OfferHistory

DAY_ONE = dt.date(2026, 9, 1)
DAY_TWO = dt.date(2026, 9, 2)


def record(fingerprint, **overrides):
    base = {
        'fingerprint': fingerprint, 'agency_slug': 'a', 'agency_name': 'Агенция',
        'title': 'Гранд Камелия', 'location': 'Несебър', 'price_eur': 120000,
        'bedrooms': 2, 'area_m2': 60.0, 'floor': 3, 'deal_type': 'sale',
        'property_kind': 'apartment', 'status': 'active', 'view': 'море',
        'identity_strength': 'ref', 'ref': 'A-1',
    }
    base.update(overrides)
    return base


class SyncTests(TestCase):
    def setUp(self):
        self.agency = Agency.objects.create(slug='a', name='Агенция')

    def test_new_offers_are_inserted_and_logged(self):
        counts = sync_agency_offers(self.agency, [record('f1'), record('f2')], DAY_ONE)
        self.assertEqual(counts['new'], 2)
        self.assertEqual(Offer.objects.count(), 2)
        self.assertEqual(OfferHistory.objects.filter(event=OfferHistory.NEW).count(), 2)

    def test_an_unchanged_sheet_records_no_changes(self):
        sync_agency_offers(self.agency, [record('f1')], DAY_ONE)
        counts = sync_agency_offers(self.agency, [record('f1')], DAY_TWO)
        self.assertEqual(counts['changed'], 0)
        self.assertEqual(counts['unchanged'], 1)
        self.assertEqual(OfferHistory.objects.filter(event=OfferHistory.CHANGED).count(), 0)

    def test_a_price_cut_is_history_not_an_overwrite(self):
        sync_agency_offers(self.agency, [record('f1')], DAY_ONE)
        sync_agency_offers(self.agency, [record('f1', price_eur=110000)], DAY_TWO)
        offer = Offer.objects.get(fingerprint='f1')
        self.assertEqual(int(offer.price_eur), 110000)
        self.assertEqual(int(offer.prev_price_eur), 120000)
        self.assertTrue(offer.price_dropped)
        self.assertTrue(OfferHistory.objects.filter(field='price_eur',
                                                    event=OfferHistory.CHANGED).exists())

    def test_a_vanished_offer_is_retired_not_deleted(self):
        sync_agency_offers(self.agency, [record('f1'), record('f2')], DAY_ONE)
        counts = sync_agency_offers(self.agency, [record('f1')], DAY_TWO)
        self.assertEqual(counts['gone'], 1)
        self.assertFalse(Offer.objects.get(fingerprint='f2').is_active)
        self.assertEqual(Offer.objects.count(), 2)      # still auditable

    def test_a_returning_offer_becomes_active_again(self):
        sync_agency_offers(self.agency, [record('f1')], DAY_ONE)
        sync_agency_offers(self.agency, [], DAY_TWO)
        sync_agency_offers(self.agency, [record('f1')], DAY_TWO)
        self.assertTrue(Offer.objects.get(fingerprint='f1').is_active)

    def test_the_same_flat_listed_twice_in_one_sheet_is_stored_once(self):
        counts = sync_agency_offers(self.agency, [record('f1'), record('f1')], DAY_ONE)
        self.assertEqual(counts['new'], 1)


class WeakIdentityTests(TestCase):
    """A thin row carries its price in its fingerprint, so a price cut renames it.

    Without the weak_core match, the repriced row looks like a stranger and the
    original looks withdrawn -- and any candidate pointing at it dangles.
    """

    def setUp(self):
        self.agency = Agency.objects.create(slug='a', name='Агенция')

    def test_a_repriced_thin_row_keeps_its_row(self):
        thin = record('weak-120000', identity_strength='weak', ref='',
                      weak_core='a|Гранд Камелия|2|60|3')
        sync_agency_offers(self.agency, [thin], DAY_ONE)
        original_id = Offer.objects.get().pk

        repriced = record('weak-110000', identity_strength='weak', ref='',
                          weak_core='a|Гранд Камелия|2|60|3', price_eur=110000)
        counts = sync_agency_offers(self.agency, [repriced], DAY_TWO)

        self.assertEqual(counts['rekeyed'], 1)
        self.assertEqual(counts['new'], 0)
        self.assertEqual(Offer.objects.count(), 1)
        offer = Offer.objects.get()
        self.assertEqual(offer.pk, original_id)          # the stable identity holds
        self.assertEqual(offer.fingerprint, 'weak-110000')
        self.assertEqual(int(offer.prev_price_eur), 120000)

    def test_an_ambiguous_match_is_not_claimed(self):
        """Two candidates mean the sheet really does hold two similar flats."""
        core = 'a|Гранд Камелия|2|60|3'
        sync_agency_offers(self.agency, [
            record('weak-a', identity_strength='weak', ref='', weak_core=core),
            record('weak-b', identity_strength='weak', ref='', weak_core=core,
                   price_eur=125000)], DAY_ONE)
        counts = sync_agency_offers(self.agency, [
            record('weak-c', identity_strength='weak', ref='', weak_core=core,
                   price_eur=110000)], DAY_TWO)
        self.assertEqual(counts['rekeyed'], 0)
        self.assertEqual(counts['new'], 1)


class DerivedFieldTests(TestCase):
    def setUp(self):
        self.agency = Agency.objects.create(slug='a', name='Агенция')

    def test_features_are_resolved_at_ingest(self):
        sync_agency_offers(self.agency, [record('f1', view='море, басейн')], DAY_ONE)
        self.assertTrue(Offer.objects.get().features['sea_view'])

    def test_an_empty_view_column_resolves_to_nothing_not_to_false(self):
        """Absence of evidence is what creates the 'needs verification' band."""
        sync_agency_offers(self.agency,
                           [record('f1', view='', title='', notes='')], DAY_ONE)
        self.assertNotIn('sea_view', Offer.objects.get().features)

    def test_title_is_romanised_for_the_trigram_index(self):
        sync_agency_offers(self.agency, [record('f1')], DAY_ONE)
        self.assertEqual(Offer.objects.get().title_norm, 'grand kameliya')

    def test_location_is_salvaged_from_raw_text(self):
        sync_agency_offers(self.agency,
                           [record('f1', location=None, location_raw='Св. Влас')], DAY_ONE)
        offer = Offer.objects.get()
        self.assertEqual(offer.location, 'Свети Влас')
        self.assertTrue(offer.location_salvaged)

    def test_price_is_stored_as_an_exact_decimal(self):
        from decimal import Decimal
        sync_agency_offers(self.agency, [record('f1', price_eur=149999.99)], DAY_ONE)
        self.assertEqual(Offer.objects.get().price_eur, Decimal('149999.99'))
