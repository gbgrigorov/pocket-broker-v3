"""Database integration tests for the bounded Bulgarian Properties crawl.

Every HTTP body comes from the sanitized local fixtures.  Catalogue discovery
is reduced to the fixture's two representative rows so a test run never treats
the deliberately abbreviated fixture as an incomplete 717-row crawl.
"""
import json
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from market import bulgarian_properties as parser
from market.bp_crawl import SLUG, crawl, save_offer
from market.models import City, Neighbourhood, SiteProbe
from market.source_http import SourceBlocked
from sourcing.models import Agency, CrawlRun, Offer, OfferHistory
from sourcing.web.store import fingerprint


FIXTURES = Path(__file__).parent / 'fixtures' / 'bulgarian_properties'
SALE_URL = ('https://www.bulgarianproperties.com/1-bedroom_apartments_in_Bulgaria/'
            'AD91504BG_1-bedroom_apartment_for_sale_in_Sofia.html')
RENT_URL = ('https://www.bulgarianproperties.com/1-bedroom_apartments_in_Bulgaria/'
            'AD91674BG_1-bedroom_apartment_for_rent_in_Sofia.html')
PROJECT_URL = ('https://www.bulgarianproperties.com/Apartments_(various_types)_in_Bulgaria/'
               'AD82111BG_Apartments_(various_types)_for_sale_in_Sofia.html')


def fixture(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


def agency_factory(**values):
    defaults = {'slug': SLUG, 'name': 'Bulgarian Properties',
                'website': 'https://www.bulgarianproperties.com/'}
    defaults.update(values)
    return Agency.objects.create(**defaults)


class FixtureClient:
    """Small SourceClient-compatible transport with no external I/O."""

    def __init__(self, pages=None, fail_url=None, blocked=False):
        self.pages = pages or {}
        self.fail_url = fail_url
        self.blocked = blocked
        self.responses = []

    def get(self, url, **kwargs):
        if url == self.fail_url:
            if self.blocked:
                raise SourceBlocked(f'blocked fixture URL: {url}')
            response = {'url': url, 'status': 500, 'ok': False, 'body': '',
                        'encoding': 'utf-8'}
        elif url.endswith('/robots.txt'):
            response = {'url': url, 'status': 200, 'ok': True,
                        'body': 'User-agent: *\nDisallow:', 'encoding': 'utf-8'}
        elif url in self.pages:
            response = {'url': url, 'status': 200, 'ok': True,
                        'body': self.pages[url], 'encoding': 'cp1252'}
        else:
            response = {'url': url, 'status': 404, 'ok': False, 'body': '',
                        'encoding': 'utf-8'}
        self.responses.append({'url': url, 'status': response['status'],
                               'encoding': response['encoding'], 'bytes': len(response['body']),
                               'error': ''})
        return response


class SaveOfferTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agency = agency_factory()
        cls.sofia = City.objects.get(slug='sofia')

    def parsed_sale(self):
        return parser.detail(fixture('sale.html'), SALE_URL)

    def save(self, parsed=None, **evidence):
        return save_offer(self.agency, parsed or self.parsed_sale(),
                          {'test': True, **evidence})

    def test_stable_identity_repricing_and_field_history(self):
        offer, created = self.save()
        original_id = offer.pk
        repriced = self.parsed_sale()
        repriced['record']['price_eur'] = Decimal('265000')
        repriced['record']['price_raw'] = '€ 265 000'

        offer, changed = self.save(repriced)
        offer.refresh_from_db()

        self.assertEqual(offer.pk, original_id)
        self.assertEqual(Offer.objects.count(), 1)
        self.assertEqual(created, {'new': 1, 'updated': 0, 'price_changes': 0, 'returned': 0})
        self.assertEqual(changed, {'new': 0, 'updated': 1, 'price_changes': 1, 'returned': 0})
        self.assertEqual(offer.price_eur, Decimal('265000'))
        self.assertEqual(offer.prev_price_eur, Decimal('275000'))
        history = offer.history.get(event='changed', field='price_eur')
        self.assertEqual((history.old_value, history.new_value), ('275000.00', '265000'))

    def test_changed_category_url_with_same_ad_reference_retains_row_id(self):
        offer, _ = self.save()
        original_id = offer.pk
        changed_url = SALE_URL.replace('/1-bedroom_apartments_in_Bulgaria/',
                                       '/Apartments_in_Bulgaria/')
        parsed = self.parsed_sale()
        parsed['url'] = changed_url
        parsed['record']['listing_url'] = changed_url

        offer, changes = self.save(parsed)
        offer.refresh_from_db()

        self.assertEqual(offer.pk, original_id)
        self.assertEqual(offer.listing_url, changed_url)
        self.assertEqual(offer.source_url, changed_url)
        self.assertEqual(Offer.objects.count(), 1)
        self.assertEqual(changes['updated'], 0)

    def test_missing_price_and_area_preserve_last_good_values(self):
        offer, _ = self.save()
        incomplete = self.parsed_sale()
        incomplete['record']['price_eur'] = None
        incomplete['record']['price_raw'] = 'Price on request'
        incomplete['record']['area_m2'] = None

        offer, changes = self.save(incomplete)
        offer.refresh_from_db()

        self.assertEqual(offer.price_eur, Decimal('275000'))
        self.assertEqual(offer.price_raw, '€ 275 000')
        self.assertEqual(offer.area_m2, Decimal('72'))
        self.assertEqual(changes['updated'], 0)
        self.assertCountEqual(offer.evidence['missing_fields'], ['price_eur', 'area_m2'])
        self.assertFalse(offer.history.filter(event='changed').exists())

    def test_zero_previous_price_is_written_verbatim_to_history(self):
        parsed = self.parsed_sale()
        parsed['record']['price_eur'] = Decimal('0')
        parsed['record']['price_raw'] = '€ 0'
        offer, _ = self.save(parsed)
        parsed['record']['price_eur'] = Decimal('1000')
        parsed['record']['price_raw'] = '€ 1 000'

        offer, _ = self.save(parsed)
        change = offer.history.get(event='changed', field='price_eur')

        self.assertEqual(change.old_value, '0.00')
        self.assertEqual(change.new_value, '1000')
        self.assertEqual(offer.prev_price_eur, Decimal('0'))

    def test_inactive_offer_return_is_recorded_and_reactivated(self):
        offer, _ = self.save()
        Offer.objects.filter(pk=offer.pk).update(is_active=False)

        offer, changes = self.save()
        offer.refresh_from_db()

        self.assertTrue(offer.is_active)
        self.assertEqual(changes['returned'], 1)
        self.assertTrue(offer.history.filter(event='returned').exists())

    def test_ambiguous_legacy_rows_fail_without_mutating_either(self):
        first, _ = self.save()
        second = Offer.objects.create(
            agency=self.agency, source='web', fingerprint='web-ambiguous-row',
            ref='legacy Sfa 91504', listing_url='https://example.invalid/legacy',
            first_seen=first.first_seen, last_seen=first.last_seen,
            title='Legacy duplicate', location='Sofia')

        with self.assertRaisesRegex(parser.ParseError, 'Ambiguous'):
            self.save()

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.times_seen, 1)
        self.assertEqual(second.times_seen, 1)

    def test_manual_geography_survives_offer_update(self):
        offer, _ = self.save()
        manual = Neighbourhood.objects.get(city=self.sofia, slug='lozenets')
        geo = offer.geo
        geo.neighbourhood = manual
        geo.matched_by = 'manual'
        geo.save()
        updated = self.parsed_sale()
        updated['record']['location'] = 'Sofia, Nadezhda 1'
        updated['record']['location_raw'] = 'Sofia, Nadezhda 1'

        offer, _ = self.save(updated)
        offer.geo.refresh_from_db()

        self.assertEqual(offer.geo.city, self.sofia)
        self.assertEqual(offer.geo.neighbourhood, manual)
        self.assertEqual(offer.geo.matched_by, 'manual')


class CrawlIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agency = agency_factory()
        cls.sofia = City.objects.get(slug='sofia')
        cls.varna = City.objects.get(slug='varna')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.runs = Path(self.temp.name)

    def rows(self, *pairs):
        return [{'ref': ref, 'url': url, 'location': 'Sofia', 'inactive': False}
                for ref, url in pairs]

    def catalogue_result(self, rows, total=None):
        return {'rows': rows, 'total': len(rows) if total is None else total,
                'next_url': None, 'page_index': 0, 'page_links': {}}

    def run_crawl(self, client, catalogue_result, **options):
        with override_settings(RUNS_DIR=self.runs), \
                mock.patch('market.bp_crawl.parser.catalogue', return_value=catalogue_result):
            return crawl(client=client, no_images=True, emit=lambda _line: None, **options)

    def existing_offer(self, ref='80000'):
        url = (f'https://www.bulgarianproperties.com/1-bedroom_apartments_in_Bulgaria/'
               f'AD{ref}BG_existing_offer.html')
        return Offer.objects.create(
            agency=self.agency, source='web', fingerprint=fingerprint(url), ref=ref,
            listing_url=url, source_url=url, first_seen=date.today(), last_seen=date.today(),
            title='Existing', location='Sofia',
            identity_strength='source-ref', evidence={'test': True})

    def test_success_persists_run_probe_stats_and_city_scope(self):
        varna_probe = SiteProbe.objects.create(
            city=self.varna, agency_slug=SLUG, agency_name=self.agency.name,
            run_id='varna-scope', status='ok', listing_pattern=r'/AD\d+BG_')
        rows = self.rows(('91504', SALE_URL), ('91674', RENT_URL))
        client = FixtureClient({parser.CATALOGUE: fixture('catalogue.html'),
                                SALE_URL: fixture('sale.html'), RENT_URL: fixture('rent.html')})

        run, stats = self.run_crawl(client, self.catalogue_result(rows))
        run.refresh_from_db()
        probe = SiteProbe.objects.get(agency_slug=SLUG, city=self.sofia)

        self.assertEqual((run.status, run.sources_ok, run.offers_total, run.offers_new),
                         ('ok', 1, 2, 2))
        self.assertEqual((stats['discovered'], stats['fetched'], stats['stored']), (2, 2, 2))
        self.assertTrue(stats['discovery_complete'])
        self.assertTrue(stats['detail_complete'])
        self.assertEqual(probe.city, self.sofia)
        self.assertEqual(probe.status, 'ok')
        self.assertEqual(probe.strategy['statistics']['stored'], 2)
        self.assertEqual(SiteProbe.latest('sofia')[SLUG], probe)
        self.assertEqual(SiteProbe.latest('varna')[SLUG], varna_probe)
        payload = json.loads((self.runs / f'bp-sofia-{run.pk}.json').read_text())
        self.assertEqual(payload['stats']['stored'], 2)

    def test_projects_and_outside_city_pages_are_counted_but_not_stored(self):
        outside = fixture('sale.html').replace(
            'Sofia, Manastirski Livadi</span>', 'Plovdiv, Center</span>', 1)
        rows = self.rows(('82111', PROJECT_URL), ('91504', SALE_URL))
        client = FixtureClient({parser.CATALOGUE: fixture('catalogue.html'),
                                PROJECT_URL: fixture('project.html'), SALE_URL: outside})

        run, stats = self.run_crawl(client, self.catalogue_result(rows))

        self.assertEqual(run.status, 'ok')
        self.assertEqual((stats['project'], stats['outside_city'], stats['stored']), (1, 1, 0))
        self.assertFalse(Offer.objects.exists())

    def test_block_or_failure_never_retires_existing_active_offer(self):
        existing = self.existing_offer()
        rows = self.rows(('91504', SALE_URL))
        page = self.catalogue_result(rows)
        for blocked in (False, True):
            with self.subTest(blocked=blocked):
                client = FixtureClient({parser.CATALOGUE: fixture('catalogue.html')},
                                       fail_url=SALE_URL, blocked=blocked)
                run, stats = self.run_crawl(client, page)
                existing.refresh_from_db()
                self.assertTrue(existing.is_active)
                self.assertEqual(Offer.objects.filter(pk=existing.pk).count(), 1)
                self.assertEqual(run.status, 'partial')
                self.assertEqual(stats['blocked'] if blocked else stats['errors'], 1)
                self.assertEqual(stats['marked_inactive'], 0)

    def test_limit_is_explicitly_partial_after_complete_discovery(self):
        rows = self.rows(('91504', SALE_URL), ('91674', RENT_URL))
        client = FixtureClient({parser.CATALOGUE: fixture('catalogue.html'),
                                SALE_URL: fixture('sale.html'), RENT_URL: fixture('rent.html')})

        run, stats = self.run_crawl(client, self.catalogue_result(rows), limit=1)

        self.assertEqual(run.status, 'partial')
        self.assertTrue(stats['discovery_complete'])
        self.assertFalse(stats['detail_complete'])
        self.assertEqual((stats['discovered'], stats['fetched'], stats['stored']), (2, 1, 1))

    def test_discovery_only_writes_evidence_but_no_offers(self):
        existing = self.existing_offer()
        rows = self.rows(('91504', SALE_URL), ('91674', RENT_URL))
        client = FixtureClient({parser.CATALOGUE: fixture('catalogue.html')})

        run, stats = self.run_crawl(client, self.catalogue_result(rows), discover_only=True)
        existing.refresh_from_db()

        self.assertEqual(run.status, 'ok')
        self.assertEqual(stats['fetched'], 0)
        self.assertEqual(stats['stored'], 0)
        self.assertEqual(list(Offer.objects.values_list('pk', flat=True)), [existing.pk])
        self.assertTrue(existing.is_active)
        self.assertEqual(SiteProbe.objects.get(agency_slug=SLUG).strategy['statistics']['discovered'], 2)
