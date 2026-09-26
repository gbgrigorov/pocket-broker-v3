import json
from decimal import Decimal
from pathlib import Path
import tempfile
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from market import bulgarian_properties as parser
from market.bp_crawl import crawl, save_offer
from market.bp_units import floor_number, price_list_url, units
from sourcing.models import Agency, Offer

FIXTURES = Path(__file__).parent / 'fixtures' / 'bulgarian_properties'
PROVENANCE = json.loads((FIXTURES / 'unit-provenance.json').read_text())
UNIT_URL = PROVENANCE['unit.html']['source_url']
PROJECT_URL = 'https://www.bulgarianproperties.com/Apartments_(various_types)_in_Bulgaria/AD82111BG_Apartments_(various_types)_for_sale_in_Sofia.html'


def fixture(name):
    return (FIXTURES / name).read_text()


class UnitParserTests(SimpleTestCase):
    def test_unit_canonical_parent_does_not_collapse_identity_or_price(self):
        p = parser.detail(fixture('unit.html'), UNIT_URL)
        self.assertEqual(p['outcome'], 'offer')
        self.assertEqual(p['ref'], '77779PL212960')
        self.assertEqual(p['record']['listing_url'], UNIT_URL)
        self.assertEqual(p['record']['price_eur'], Decimal('185874'))
        self.assertEqual(p['record']['area_m2'], Decimal('71.49'))
        self.assertEqual((p['record']['bedrooms'], p['record']['floor']), (1, 2))

    def test_unit_requires_its_own_primary_script_id(self):
        with self.assertRaisesRegex(parser.ParseError, 'unit identity'):
            parser.detail(fixture('unit.html').replace('master_unit_ID = 212960', 'master_unit_ID = 999999'), UNIT_URL)

    def test_typo_in_marketing_reference_requires_matching_own_primary_identity(self):
        html = fixture('unit.html').replace('Sfa 77779', 'Sfa 90671')
        p = parser.detail(html, UNIT_URL)
        self.assertEqual(p['ref'], '77779PL212960')
        self.assertEqual(p['fields']['marketing reference differs from primary id'], 'Sfa 90671')
        with self.assertRaises(parser.ParseError):
            parser.detail(html.replace('master_IID = 77779', 'master_IID = 90671'), UNIT_URL)

    def test_price_list_units_keep_exact_price_area_kind_status_and_displayed_floor(self):
        rows = units(fixture('unit-price-list.html'), fixture('project.html'), PROJECT_URL)
        self.assertEqual([r['outcome'] for r in rows], ['offer', 'offer', 'unavailable', 'unavailable'])
        self.assertEqual(rows[0]['record']['price_eur'], Decimal('435414'))
        self.assertEqual(rows[1]['record']['price_eur'], Decimal('280627'))
        self.assertEqual(rows[1]['record']['area_m2'], Decimal('83.52'))
        self.assertEqual(rows[1]['record']['property_kind'], '1-bedroom apartment')
        self.assertEqual(rows[1]['record']['bedrooms'], 1)
        self.assertEqual(rows[1]['record']['floor'], 2)  # data-floor=11 is a code
        self.assertEqual(rows[1]['ref'], '82111PL225380')
        self.assertEqual(floor_number('Minus Second Floor'), -2)

    def test_inconsistent_unit_values_cannot_be_imported(self):
        with self.assertRaisesRegex(parser.ParseError, 'price disagrees'):
            units(fixture('unit-price-list.html').replace('435414.00', '1.00'), fixture('project.html'), PROJECT_URL)

    def test_unpublished_unit_area_is_unknown_instead_of_a_fake_zero(self):
        html = fixture('unit-price-list.html').replace('data-size="103.67"', 'data-size="0.00"').replace('>103.67</td>', '></td>')
        row = units(html, fixture('project.html'), PROJECT_URL)[0]
        self.assertIsNone(row['record']['area_m2'])
        self.assertEqual(row['record']['price_eur'], Decimal('435414'))

    def test_available_unit_does_not_require_one_specific_css_colour(self):
        html = fixture('unit-price-list.html').replace('stat free', 'stat available')
        self.assertEqual(units(html, fixture('project.html'), PROJECT_URL)[0]['outcome'], 'offer')

    def test_displayed_whole_euro_rounding_preserves_exact_published_cents(self):
        html = fixture('unit-price-list.html').replace('435414.00', '435413.99')
        p = units(html, fixture('project.html'), PROJECT_URL)[0]
        self.assertEqual(p['record']['price_eur'], Decimal('435413.99'))
        self.assertEqual(p['record']['price_raw'], '€ 435 414')
        self.assertTrue(p['fields']['visible_price_rounded'])
        with self.assertRaises(parser.ParseError):
            units(html.replace('435413.99', '435413.40'), fixture('project.html'), PROJECT_URL)

    def test_zero_placeholder_asking_price_remains_unknown(self):
        html = fixture('unit.html').replace('185 874', '0').replace('"price": 185874', '"price": 0')
        self.assertIsNone(parser.detail(html, UNIT_URL)['record']['price_eur'])

    def test_only_own_verified_public_price_list_endpoint(self):
        button = '<span class="pricelist" data-src="#singlePropertyPriceList" data-url="/pdetail.php?IID=82111&amp;xajax=1&amp;scmd=propprice"></span>'
        url = price_list_url(fixture('project.html') + button, PROJECT_URL)
        self.assertIn('search_status=0', url)
        self.assertIsNone(price_list_url(button.replace('IID=82111', 'IID=999'), PROJECT_URL))
        self.assertIsNone(price_list_url(button.replace('/pdetail.php', 'https://private.example/pdetail.php'), PROJECT_URL))


class UnitIdentityTests(TestCase):
    def test_positive_unit_availability_only_retires_verified_unit(self):
        from market.sofia_crawl import mark_verified_unavailable
        agency = Agency.objects.create(slug='bulgarian-properties', name='Bulgarian Properties', website='https://www.bulgarianproperties.com/')
        rows = units(fixture('unit-price-list.html'), fixture('project.html'), PROJECT_URL)[:2]
        first, _ = save_offer(agency, rows[0], {})
        second, _ = save_offer(agency, rows[1], {})
        unavailable = dict(outcome='unavailable', ref=first.ref, url=first.listing_url, location=first.location)
        self.assertEqual(mark_verified_unavailable(agency, unavailable, dict(source_url='public-price-list')), 1)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)
        self.assertEqual(first.history.filter(event='removed').count(), 1)
        with self.assertRaises(parser.ParseError):
            mark_verified_unavailable(agency, {**unavailable, 'location': 'Near Sofia, Lozen'}, {})

    def test_units_in_one_development_have_distinct_stable_offer_ids(self):
        agency = Agency.objects.create(slug='bulgarian-properties', name='Bulgarian Properties', website='https://www.bulgarianproperties.com/')
        rows = units(fixture('unit-price-list.html'), fixture('project.html'), PROJECT_URL)[:2]
        first, _ = save_offer(agency, rows[0], {})
        second, _ = save_offer(agency, rows[1], {})
        again, _ = save_offer(agency, rows[0], {})
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(first.pk, again.pk)
        self.assertEqual(Offer.objects.count(), 2)

    def test_full_crawl_expands_project_into_available_units(self):
        from market.tests.test_bp_crawl import FixtureClient
        Agency.objects.create(slug='bulgarian-properties', name='Bulgarian Properties', website='https://www.bulgarianproperties.com/')
        button = '<span class="pricelist" data-src="#singlePropertyPriceList" data-url="/pdetail.php?IID=82111&amp;xajax=1&amp;scmd=propprice"></span>'
        project = fixture('project.html') + button
        catalogue = dict(rows=[dict(ref='82111', url=PROJECT_URL)], total=1, next_url=None)
        client = FixtureClient({parser.CATALOGUE: 'catalogue', PROJECT_URL: project,
                                price_list_url(project, PROJECT_URL): fixture('unit-price-list.html')})
        with tempfile.TemporaryDirectory() as folder, override_settings(RUNS_DIR=Path(folder)), mock.patch('market.bp_crawl.parser.catalogue', return_value=catalogue):
            run, stats = crawl(client=client, no_images=True, emit=lambda s: None)
        self.assertEqual(run.status, 'ok')
        self.assertEqual(stats['project'], 1)
        self.assertEqual(stats['units_discovered'], 4)
        self.assertEqual(stats['units_stored'], 2)
        self.assertEqual(stats['units_unavailable'], 2)
        self.assertEqual(stats['stored'], 2)
        self.assertEqual(Offer.objects.count(), 2)
