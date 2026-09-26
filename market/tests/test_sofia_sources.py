"""Source facts and import safety, with reduced local fixtures and no network."""
import json
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from market.models import SiteProbe
from market.sofia_crawl import crawl, ensure_agency, mark_verified_unavailable, store_offer
from market.sofia_sources import ADAPTERS, COHORT, ParseError, kind_of, public_url, next_flight, Tree
from market.source_http import SourceBlocked, decode_html
from sourcing.models import Agency, CrawlRun, Offer

FIXTURES = Path(__file__).parent / 'fixtures' / 'sofia'
CAPTURES = json.loads((FIXTURES / 'README.json').read_text())['captures']


def fixture(slug, name):
    row = next(r for r in CAPTURES if r['adapter'] == slug and r['fixture'] == name)
    return (FIXTURES / slug / name).read_text(), row['source_url']


def parsed(slug='yavlena', deal='sale'):
    html, url = fixture(slug, f'{deal}.html')
    return ADAPTERS[slug].detail(html, url, deal)


def flight_replace(html, before, after):
    return html.replace(json.dumps(before, ensure_ascii=False)[1:-1],
                        json.dumps(after, ensure_ascii=False)[1:-1])


class ParserTests(SimpleTestCase):
    def test_flight_utf8_text_records_can_end_without_newlines(self):
        decoy = '\nff:["$","fake",null,{"property":{"wrong":true}}]\n'
        texts = ['Описание на имота: ' + decoy + 'a', 'Още текст.a']
        flight = ''.join(f'{i:x}:T{len(t.encode("utf-8")):x},' + t for i, t in enumerate(texts))
        flight += 'e:["$","primary",null,{"property":{"propertyData":{"innerNumber":175638}}}]\n'
        html = '<script>self.__next_f.push(' + json.dumps([1, flight], ensure_ascii=False) + ')</script>'
        props = list(next_flight(Tree(html).root))
        self.assertEqual(props, [{'property': {'propertyData': {'innerNumber': 175638}}}])

    def test_exact_five_source_cohort(self):
        self.assertEqual(len(COHORT), 5)
        self.assertEqual(set(COHORT) - {'bulgarian-properties'}, set(ADAPTERS))

    def test_arco_pagination_keeps_last_partial_page_when_pager_omits_it(self):
        html, url = fixture('arco-real-estate', 'catalogue-sale.html')
        # Source advertises 749 results but only renders page links up to 74.
        import re
        html = re.sub(r'OffersControls.setPage\(\d+\);', '', html)
        html = html.replace('1-10', '731-740')
        page = ADAPTERS['arco-real-estate'].catalogue(html, url + '&page=74&limit=10', 'sale')
        self.assertIn('page=75', page['next_url'])
        final = ADAPTERS['arco-real-estate'].catalogue(html.replace('731-740', '741-749'),
            url + '&page=75&limit=10', 'sale')
        self.assertIsNone(final['next_url'])

    def test_lux_inactive_page_does_not_require_removed_price_panel(self):
        html, url = fixture('luximmo', 'sale.html')
        html = html.replace('id="panel_wrap"', 'id="inactive-panel"')
        html = html.replace('id="g_container"', 'id="g_container"><span class="band">НЕАКТУАЛНА ОФЕРТА</span><div')
        self.assertEqual(ADAPTERS['luximmo'].detail(html, url, 'sale')['outcome'], 'unavailable')

    def test_lux_empty_marketing_reference_still_requires_own_numeric_identity(self):
        html, url = fixture('luximmo', 'sale.html')
        import re
        html = re.sub(r'(Референтен номер.*?<div[^>]*>)\s*[^<]+', r'\1', html, flags=re.S)
        self.assertEqual(ADAPTERS['luximmo'].detail(html, url, 'sale')['outcome'], 'offer')

    def test_home_generic_heading_uses_own_property_metadata(self):
        html, url = fixture('home2u', 'missing-title.html')
        import re
        html = re.sub(r'<h1([^>]*)>.*?</h1>', r'<h1\1>За имота</h1>', html, flags=re.S)
        p = ADAPTERS['home2u'].detail(html, url, 'sale')
        self.assertEqual(p['record']['property_kind'], 'Промишлено помещение')
        self.assertEqual(p['fields']['title_source'], 'own og:title')

    def test_home_recognised_simple_title_is_not_overwritten_by_description(self):
        html, url = fixture('home2u', 'sale.html')
        import re
        html = re.sub(r'<h1([^>]*)>.*?</h1>', r'<h1\1>Парцел</h1>', html, flags=re.S)
        p = ADAPTERS['home2u'].detail(html, url, 'sale')
        self.assertEqual(p['record']['property_kind'], 'Парцел')

    def test_home_unit_number_heading_gets_type_from_own_metadata(self):
        html, url = fixture('home2u', 'missing-title.html')
        import re
        html = re.sub(r'<h1([^>]*)>.*?</h1>', r'<h1\1>АП. 11</h1>', html, flags=re.S)
        p = ADAPTERS['home2u'].detail(html, url, 'sale')
        self.assertEqual(p['record']['property_kind'], 'Промишлено помещение')

    def test_all_four_sale_and_rental_details(self):
        expected = {
            'yavlena': [('440000', '193', 2), ('650', '65', 1)],
            'home2u': [('167000', '59.61', 1), ('630', '65', 1)],
            'luximmo': [('657000', '187.74', 3), ('10000', '260', 2)],
            'arco-real-estate': [('195300', '85', 2), ('1300', '120', 3)],
        }
        for slug, values in expected.items():
            for deal, (price, area, beds) in zip(('sale', 'rent'), values):
                with self.subTest(slug=slug, deal=deal):
                    p = parsed(slug, deal)
                    self.assertEqual(p['outcome'], 'offer')
                    self.assertEqual(p['record']['price_eur'], Decimal(price))
                    self.assertEqual(p['record']['area_m2'], Decimal(area))
                    self.assertEqual(p['record']['bedrooms'], beds)
                    self.assertEqual(p['record']['deal_type'], deal)
                    self.assertTrue(p['record']['location'].startswith('София,'))
                    self.assertTrue(p['images'])

    def test_all_catalogues_and_observed_pagination(self):
        for row in CAPTURES:
            if not row['fixture'].startswith('catalogue'):
                continue
            slug, name = row['adapter'], row['fixture']
            deal = 'all' if name == 'catalogue-all.html' else 'rent' if 'rent' in name else 'sale'
            with self.subTest(slug=slug, name=name):
                html, url = fixture(slug, name)
                page = ADAPTERS[slug].catalogue(html, url, deal)
                self.assertTrue(page['rows'])
                self.assertTrue(page['next_url'])
                next_page = ADAPTERS[slug].catalogue(*fixture(slug, name), deal)
                self.assertEqual(page, next_page)
                if 'page2' in name:
                    first = ADAPTERS[slug].catalogue(*fixture(slug, f'catalogue-{deal}.html'), deal)
                    self.assertNotEqual({r['url'] for r in first['rows']}, {r['url'] for r in page['rows']})

    def test_full_home_rentals_do_not_narrow_to_apartments(self):
        from urllib.parse import parse_qs, urlsplit
        html, url = fixture('home2u', 'catalogue-rent-all.json')
        page = ADAPTERS['home2u'].catalogue(html, url, 'rent')
        self.assertEqual(ADAPTERS['home2u'].starts['rent'], url)
        self.assertNotIn('property_type[]', parse_qs(urlsplit(page['next_url']).query))
        html, url = fixture('home2u', 'catalogue-rent.html')
        narrow = ADAPTERS['home2u'].catalogue(html, url, 'rent')
        self.assertEqual(parse_qs(urlsplit(narrow['next_url']).query)['property_type[]'], ['48', '12', '11', '20'])

    def test_full_lux_city_catalogue_includes_sale_rent_and_houses(self):
        page = ADAPTERS['luximmo'].catalogue(*fixture('luximmo', 'catalogue-all.html'), 'all')
        self.assertEqual(set(row['deal'] for row in page['rows']), {'sale', 'rent'})
        self.assertTrue(any('/luksozni-imoti-kashti/' in row['url'] for row in page['rows']))
        self.assertEqual(page['total'], 2235)

    def test_no_national_catalogue_substitution(self):
        wrong = {'yavlena': 'https://www.yavlena.com/bg/sales',
                 'home2u': 'https://home2u.bg/properties/',
                 'luximmo': 'https://www.luximmo.bg/bulgaria/prodajba-varna/apartamenti/index.html',
                 'arco-real-estate': 'https://www.arcoreal.bg/%D0%BE%D1%84%D0%B5%D1%80%D1%82%D0%B8?t=2&l=1'}
        for slug, url in wrong.items():
            with self.subTest(slug=slug), self.assertRaises(ParseError):
                ADAPTERS[slug].catalogue(fixture(slug, 'catalogue-sale.html')[0], url, 'sale')

    def test_canonical_mismatch_cannot_store_related_listing(self):
        for slug in ADAPTERS:
            html, url = fixture(slug, 'sale.html')
            with self.subTest(slug=slug), self.assertRaises(ParseError):
                ADAPTERS[slug].detail(html.replace(url, 'https://unverified.example/offer'), url, 'sale')

    def test_own_locality_rejects_region_and_other_cities(self):
        replacements = {'yavlena': ('"cityName": "София"', '"cityName": "Варна"'),
            'home2u': ('Люлин 7, София', 'с.Яна, София'),
            'luximmo': ('ГР. СОФИЯ', 'С. ПАНЧАРЕВО'),
            'arco-real-estate': ('itemprop="address">София (град)', 'itemprop="address">София (област)')}
        for slug, (before, after) in replacements.items():
            html, url = fixture(slug, 'sale.html')
            if slug == 'yavlena':
                before, after = [json.dumps(s, ensure_ascii=False)[1:-1] for s in (before, after)]
            self.assertIn(before, html)
            with self.subTest(slug=slug):
                self.assertEqual(ADAPTERS[slug].detail(html.replace(before, after), url, 'sale')['outcome'], 'outside_city')

    def test_yavlena_primary_identity_price_hide_project_and_sold(self):
        html, url = fixture('yavlena', 'sale.html')
        for before, after, outcome in [('"isProject": false', '"isProject": true', 'project'),
                                       ('"isSoldOrRented": false', '"isSoldOrRented": true', 'unavailable')]:
            self.assertEqual(ADAPTERS['yavlena'].detail(flight_replace(html, before, after), url, 'sale')['outcome'], outcome)
        hidden = ADAPTERS['yavlena'].detail(flight_replace(html, '"hidePrice": false', '"hidePrice": true'), url, 'sale')
        self.assertIsNone(hidden['record']['price_eur'])
        with self.assertRaises(ParseError):
            ADAPTERS['yavlena'].detail(flight_replace(html, '"innerNumber": 175265', '"innerNumber": 999'), url, 'sale')
        with self.assertRaises(ParseError):
            ADAPTERS['yavlena'].detail(flight_replace(html, '"priceDecimal": 440000', '"priceDecimal": 123'), url, 'sale')

    def test_home_project_not_a_72809_euro_apartment(self):
        page = ADAPTERS['home2u'].catalogue(*fixture('home2u', 'catalogue-sale.html'), 'sale')
        self.assertTrue(any(r.get('project') for r in page['rows']))
        url = 'https://home2u.bg/project/sunset/'
        result = ADAPTERS['home2u'].detail(f'<link rel="canonical" href="{url}"><h1>SUNSET</h1>', url, 'sale')
        self.assertEqual(result['outcome'], 'project')

    def test_pet_and_room_facts_reach_buyer_matching(self):
        from market.buyer import pets_allowed, rooms_of
        p = parsed('home2u', 'rent')['record']
        offer = Offer(**p)
        self.assertEqual(rooms_of(offer), 2)
        self.assertFalse(pets_allowed(offer))
        self.assertTrue(offer.furnished)
        self.assertEqual(kind_of('2-стаен')[1], 2)

    def test_home_accepts_both_own_city_quarter_orders(self):
        html, url = fixture('home2u', 'sale.html')
        p = ADAPTERS['home2u'].detail(html.replace('Люлин 7, София', 'София, Люлин 7'), url, 'sale')
        self.assertEqual(p['record']['location'], 'София, Люлин 7')

    def test_home_blank_heading_uses_own_specific_metadata_not_a_generic_site_title(self):
        html, url = fixture('home2u', 'missing-title.html')
        p = ADAPTERS['home2u'].detail(html, url, 'sale')
        self.assertEqual(p['ref'], '138182')
        self.assertEqual(p['record']['property_kind'], 'Промишлено помещение')
        self.assertEqual(p['record']['price_eur'], Decimal('99990'))
        self.assertEqual(p['record']['area_m2'], Decimal('120'))
        self.assertEqual(p['fields']['title_source'], 'own og:title')
        with self.assertRaises(ParseError):
            ADAPTERS['home2u'].detail(html.replace('Пром. помещение, 120 m2, Манастирски Ливади, 99,990 €, Home2U, Хоум Ту Ю', 'Home2U'), url, 'sale')

    def test_home_gallery_missing_uses_only_its_own_page_primary_photo(self):
        html, url = fixture('home2u', 'sale.html')
        html = __import__('re').sub(r'<img[^>]+>', '', html)
        p = ADAPTERS['home2u'].detail(html, url, 'sale')
        self.assertTrue(p['images'])
        wrong = html.replace('"url": "' + url + '"', '"url": "https://home2u.bg/property/different/"')
        self.assertFalse(ADAPTERS['home2u'].detail(wrong, url, 'sale')['images'])

    def test_lux_reserved_gallery_banner_without_price_watch_button(self):
        html, url = fixture('luximmo', 'reserved.html')
        p = ADAPTERS['luximmo'].detail(html, url, 'rent')
        self.assertEqual(p['outcome'], 'unavailable')
        self.assertEqual(p['ref'], '43073')

    def test_scope_does_not_consume_recommendations_or_broker_data(self):
        for slug in ADAPTERS:
            html, url = fixture(slug, 'sale.html')
            malicious = '<aside><h1>Варна 999 стаи</h1><div class="price">1 €</div><div itemprop="address">Варна</div></aside>'
            self.assertEqual(ADAPTERS[slug].detail(html + malicious, url, 'sale')['record'], parsed(slug)['record'])

    def test_lux_multi_floor_unit_stays_a_unit_with_unknown_floor(self):
        p = parsed('luximmo')
        self.assertEqual(p['outcome'], 'offer')
        self.assertIsNone(p['record']['floor'])
        self.assertEqual(p['record']['bedrooms'], 3)
        html, url = fixture('luximmo', 'sale.html')
        p = ADAPTERS['luximmo'].detail(html.replace('657 000', 'от 657 000'), url, 'sale')
        self.assertEqual(p['outcome'], 'project')

    def test_cyrillic_legacy_encoding_and_https_boundaries(self):
        body, encoding = decode_html('София, Кръстова вада'.encode('cp1251'), 'text/html; charset=windows-1251')
        self.assertEqual(body, 'София, Кръстова вада')
        self.assertEqual(encoding, 'windows-1251')
        for url in ['http://home2u.bg/property/test/', 'https://x.example/property/test/', 'https://x:secret@home2u.bg/property/test/']:
            with self.assertRaises(ParseError):
                public_url(url, 'home2u.bg')


class FixtureClient:
    def __init__(self, pages, fail=None):
        self.pages, self.fail, self.responses, self.blocked = pages, fail, [], False

    def get(self, url, **kwargs):
        self.responses.append({'url': url})
        if url == self.fail:
            self.blocked = True
            raise SourceBlocked('fixture block')
        body = 'User-agent: *\nDisallow:' if url.endswith('/robots.txt') else self.pages.get(url, '')
        return dict(ok=bool(body), status=200 if body else 404, body=body, encoding='utf-8')


class ImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agency = Agency.objects.create(slug='yavlena', name='Явлена', website='https://www.yavlena.com/')

    def test_registry_reuse_creation_and_opt_out(self):
        self.assertEqual(ensure_agency(ADAPTERS['yavlena']).pk, self.agency.pk)
        self.assertEqual(ensure_agency(ADAPTERS['luximmo']).slug, 'luximmo')
        self.agency.crawl_opt_out = True
        self.agency.save()
        with self.assertRaises(CommandError):
            ensure_agency(ADAPTERS['yavlena'])

    def test_source_identity_and_price_history_preserve_wishlist_id(self):
        offer, _ = store_offer(self.agency, parsed(), {'adapter': 'test'})
        p = parsed()
        p['record']['price_eur'] = Decimal('450000')
        p['record']['price_raw'] = '€450 000'
        again, changes = store_offer(self.agency, p, {'adapter': 'test2'})
        self.assertEqual(again.pk, offer.pk)
        self.assertEqual(Offer.objects.count(), 1)
        self.assertEqual(changes['price_changes'], 1)
        self.assertEqual(again.prev_price_eur, Decimal('440000'))
        self.assertTrue(again.history.filter(event='changed', field='price_eur').exists())

    def dual_deal(self, deal):
        p = parsed()
        p['record']['deal_type'] = deal
        p['record']['listing_url'] = p['url'] + ('/rent' if deal == 'rent' else '')
        p['url'] = p['record']['listing_url']
        p['record']['price_eur'] = Decimal('650') if deal == 'rent' else Decimal('440000')
        return p

    def test_same_yavlena_reference_sale_and_rental_keep_distinct_ids_and_prices(self):
        sale, _ = store_offer(self.agency, self.dual_deal('sale'), {})
        rent, _ = store_offer(self.agency, self.dual_deal('rent'), {})
        self.assertNotEqual(sale.pk, rent.pk)
        for deal, original in [('sale', sale), ('rent', rent)]:
            again, _ = store_offer(self.agency, self.dual_deal(deal), {})
            self.assertEqual(again.pk, original.pk)
            self.assertEqual(again.price_eur, original.price_eur)
        self.assertEqual(Offer.objects.count(), 2)
        unavailable = dict(outcome='unavailable', ref=sale.ref, url=sale.listing_url, location=sale.location)
        self.assertEqual(mark_verified_unavailable(self.agency, unavailable, {}), 1)
        rent.refresh_from_db()
        self.assertTrue(rent.is_active)

    def test_cross_deal_repair_restores_original_wishlist_id_and_resets_false_previous_price(self):
        for original_deal, wrong_deal in [('rent', 'sale'), ('sale', 'rent')]:
            with self.subTest(original_deal=original_deal):
                Offer.objects.all().delete()
                original, _ = store_offer(self.agency, self.dual_deal(original_deal), {})
                wrong = self.dual_deal(wrong_deal)['record']
                Offer.objects.filter(pk=original.pk).update(deal_type=wrong_deal,
                    listing_url=wrong['listing_url'], price_eur=wrong['price_eur'], prev_price_eur=original.price_eur)
                # Opposite deal may be retried first: it must create a new row.
                other, _ = store_offer(self.agency, self.dual_deal(wrong_deal), {})
                restored, _ = store_offer(self.agency, self.dual_deal(original_deal), {})
                self.assertNotEqual(other.pk, original.pk)
                self.assertEqual(restored.pk, original.pk)
                self.assertEqual(restored.deal_type, original_deal)
                self.assertIsNone(restored.prev_price_eur)
                self.assertIn('identity_repair', restored.evidence)
                self.assertTrue(restored.history.filter(field='identity_repair').exists())

    def test_imported_four_room_flat_reaches_public_apartment_search(self):
        agency = ensure_agency(ADAPTERS['luximmo'])
        offer, _ = store_offer(agency, parsed('luximmo'), {})
        response = self.client.get('/api/offers/', {'city': 'sofia', 'kind': 'apartment'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(offer.pk, [row['id'] for row in response.json()['results']])

    def test_canonical_url_reconciles_inherited_non_numeric_reference(self):
        offer, _ = store_offer(self.agency, parsed(), {})
        Offer.objects.filter(pk=offer.pk).update(ref='old-175265', is_active=False)
        again, changes = store_offer(self.agency, parsed(), {})
        self.assertEqual(again.pk, offer.pk)
        self.assertTrue(again.is_active)
        self.assertEqual(changes['returned'], 1)

    def test_missing_fields_and_manual_geography_preserved(self):
        offer, _ = store_offer(self.agency, parsed(), {})
        geo = offer.geo
        geo.matched_by = 'manual'
        geo.neighbourhood = None
        geo.save()
        p = parsed()
        p['record']['price_eur'] = p['record']['area_m2'] = None
        p['record']['price_raw'] = ''
        again, _ = store_offer(self.agency, p, {})
        self.assertEqual(again.price_eur, Decimal('440000'))
        self.assertEqual(again.area_m2, Decimal('193'))
        self.assertEqual(again.geo.matched_by, 'manual')
        self.assertIsNone(again.geo.neighbourhood)

    def test_ambiguous_existing_identity_rejected_without_merge(self):
        offer, _ = store_offer(self.agency, parsed(), {})
        p = parsed()
        p['record']['ref'] = '999'
        p['record']['listing_url'] += '/different'
        second, _ = store_offer(self.agency, p, {})
        Offer.objects.filter(pk=second.pk).update(ref=offer.ref)
        with self.assertRaises(ParseError):
            store_offer(self.agency, parsed(), {})
        self.assertEqual(Offer.objects.count(), 2)

    def test_positive_unavailable_evidence_removes_only_that_sofia_offer(self):
        offer, _ = store_offer(self.agency, parsed(), {})
        unavailable = dict(outcome='unavailable', ref=offer.ref, url=offer.listing_url, location=offer.location)
        self.assertEqual(mark_verified_unavailable(self.agency, unavailable, {'run': 5}), 1)
        offer.refresh_from_db()
        self.assertFalse(offer.is_active)
        self.assertEqual(offer.status, 'unavailable')
        self.assertEqual(offer.evidence['availability_evidence'], {'run': 5})
        self.assertEqual(offer.history.filter(event='removed').count(), 1)
        self.assertEqual(mark_verified_unavailable(self.agency, unavailable, {'run': 6}), 0)
        self.assertEqual(offer.history.filter(event='removed').count(), 1)

    def test_unavailable_cannot_retire_varna_or_a_missing_offer(self):
        p = parsed()
        p['record']['location'] = 'Варна, Бриз'
        offer, _ = store_offer(self.agency, p, {})
        unavailable = dict(outcome='unavailable', ref=offer.ref, url=offer.listing_url, location='София, Редута')
        self.assertEqual(mark_verified_unavailable(self.agency, unavailable, {}), 0)
        with self.assertRaises(ParseError):
            mark_verified_unavailable(self.agency, {**unavailable, 'outcome': 'outside_city'}, {})
        offer.refresh_from_db()
        self.assertTrue(offer.is_active)

    def run_fixture(self, *, limit=1, block=False, discover_only=False):
        adapter = ADAPTERS['yavlena']
        sale, rent = parsed(), parsed('yavlena', 'rent')
        pages = {adapter.starts['sale']: 'sale-catalogue', adapter.starts['rent']: 'rent-catalogue',
                 sale['url']: fixture('yavlena', 'sale.html')[0], rent['url']: fixture('yavlena', 'rent.html')[0]}
        def catalog(body, url, deal):
            p = sale if deal == 'sale' else rent
            return dict(rows=[dict(ref=p['ref'], url=p['url'], deal=deal)], total=1, next_url=None)
        client = FixtureClient(pages, sale['url'] if block else None)
        with tempfile.TemporaryDirectory() as folder, override_settings(RUNS_DIR=Path(folder)), mock.patch.object(adapter, 'catalogue', side_effect=catalog):
            run, stats = crawl('yavlena', limit=limit, no_images=True,
                               discover_only=discover_only, client=client, emit=lambda s: None)
            self.assertTrue((Path(folder) / f'yavlena-sofia-{run.pk}.json').exists())
        return run, stats, client

    def test_bounded_import_is_partial_and_never_retires_existing_rows(self):
        other = parsed()
        other['record']['ref'] = '123'
        other['record']['listing_url'] = 'https://www.yavlena.com/bg/123'
        other['record']['location'] = 'Варна, Бриз'
        previous, _ = store_offer(self.agency, other, {})
        previous.refresh_from_db()
        before = {f.name: getattr(previous, f.name) for f in previous._meta.fields}
        run, stats, client = self.run_fixture(limit=1)
        previous.refresh_from_db()
        self.assertEqual({f.name: getattr(previous, f.name) for f in previous._meta.fields}, before)
        self.assertEqual(run.status, 'partial')
        self.assertEqual((stats['discovered'], stats['fetched'], stats['stored']), (2, 1, 1))
        self.assertEqual(stats['marked_inactive'], 0)
        probe = SiteProbe.objects.get()
        self.assertEqual(probe.city.slug, 'sofia')
        self.assertFalse(probe.strategy['retirement_enabled'])

    def test_full_fixture_import_includes_both_deals(self):
        run, stats, client = self.run_fixture(limit=2)
        self.assertEqual(run.status, 'ok')
        self.assertEqual(stats['stored'], 2)
        self.assertEqual(set(Offer.objects.values_list('deal_type', flat=True)), {'sale', 'rent'})

    def test_block_is_recorded_and_stops_further_detail_requests(self):
        run, stats, client = self.run_fixture(limit=2, block=True)
        self.assertEqual(stats['blocked'], 1)
        self.assertEqual(run.status, 'partial')
        self.assertEqual(SiteProbe.objects.get().status, 'blocked')
        self.assertFalse(Offer.objects.exists())
        self.assertEqual(len(client.responses), 4)  # robots, two catalogues, one blocked detail

    def test_discovery_only_never_writes_offers(self):
        run, stats, client = self.run_fixture(discover_only=True)
        self.assertEqual(run.status, 'ok')
        self.assertEqual(stats['fetched'], 0)
        self.assertFalse(Offer.objects.exists())

    def test_default_command_runs_exactly_five_and_rejects_unknown_before_io(self):
        run = mock.Mock(pk=5)
        stats = dict(errors=0, blocked=0, image_errors=0)
        with mock.patch('market.bp_crawl.crawl', return_value=(run, stats)) as bp, mock.patch('market.sofia_crawl.crawl', return_value=(run, stats)) as others:
            call_command('crawl_live', city='sofia', limit=2, max_pages=1, no_images=True)
            self.assertEqual(bp.call_count, 1)
            self.assertEqual([c.args[0] for c in others.call_args_list], list(COHORT[1:]))
            with self.assertRaises(CommandError):
                call_command('crawl_live', city='sofia', agencies=['imoteka'])
            self.assertEqual(others.call_count, 4)
