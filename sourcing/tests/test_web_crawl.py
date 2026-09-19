# -*- coding: utf-8 -*-
"""The website crawler, tested on the markup shapes that actually broke it.

Every case here is a defect the first crawl produced against a live site, kept
as a page fragment so it cannot come back: a filter menu read as an asking
price, a body class that discarded four entire sites, a rate per square metre
promoted to a total, a sold flat offered as live stock.
"""
import datetime as dt

from django.test import SimpleTestCase, TestCase

from sourcing.models import Agency, Offer, OfferSource, SourceKind
from sourcing.web import catalog, discover, dom, extract, labels, sites, store

MENU = """
<html><body class="header-transparent home-page">
  <div class="site-nav"><ul>
    <li>Студии До 55 000€</li><li>2-х комнатные До 70 000€</li>
  </ul></div>
  <h1>ID 162 Роял Сан</h1>
  <div class="entry">
    Город: Солнечный берег<br>
    Цена за м2: 909 €<br>
    Площадь: 33 кв. м.<br>
    Этаж: 5<br>
    Комнат: 1<br>
    Санузлов: 1<br>
    До моря: 250 м<br>
    Описание: Уютная студия в комплексе с бассейном и охраной,
    в двух шагах от пляжа. Мебель включена в стоимость.
  </div>
</body></html>
"""

SOLD_PAGE = """
<html><body>
  <h1>Апартамент в комплексе Санни Вью Централ, Слънчев бряг</h1>
  <div>€69,500 Продано</div>
  <div>Площ: 57 кв.м<br>Етаж: 4<br>Спални: 1<br>
       Гледка: море<br>Мебели: има<br>
       Описание: Просторен апартамент в затворен комплекс с басейн,
       на пет минути пеша от плажа. Таксата за поддръжка е ниска.</div>
</body></html>
"""

RENTAL = """
<html><body>
  <h1>СТУДИО В КОМПЛЕКС КАСКАДАС, Слънчев бряг</h1>
  <div>Цена: При поискване<br>Вид сделка: Под наем<br>
       Площ: 50.00 кв.м<br>Етаж: Партер<br>
       Общо етажи: 5<br>Гледка от имота: море<br>
       Описание: Студио на партерен етаж в комплекс с басейн и спа,
       на 500 метра от морето. Подходящо за целогодишно живеене.</div>
</body></html>
"""


class NumberTests(SimpleTestCase):
    def test_reads_a_number_out_of_a_labelled_value(self):
        # Stripping every non-digit turned "33 кв. м." into "33.." and lost it.
        self.assertEqual(extract.number('33 кв. м.'), 33.0)
        self.assertEqual(extract.number('50.00 кв.м'), 50.0)
        self.assertEqual(extract.number('88 900,00 €'), 88900.0)
        self.assertEqual(extract.number('1 306'), 1306.0)

    def test_text_without_digits_is_not_a_number(self):
        self.assertIsNone(extract.number('При поискване'))
        self.assertIsNone(extract.number('Партер'))


class ContentWindowTests(SimpleTestCase):
    def test_a_wordpress_body_class_does_not_discard_the_page(self):
        # `<body class="header-transparent">` matched the chrome pattern and
        # dropped four whole sites to zero characters of text.
        page = dom.read(MENU)
        self.assertIn('Роял Сан', page['text'])

    def test_window_starts_at_the_heading(self):
        page = dom.read(MENU)
        self.assertTrue(page['content'].startswith('ID 162 Роял Сан'))
        self.assertNotIn('55 000', page['content'])


class LabelTests(SimpleTestCase):
    def test_price_per_square_metre_never_lands_in_the_price_slot(self):
        found = labels.pairs('Цена за м2: 909 €\nПлощадь: 33 кв. м.')
        self.assertEqual(found['price_per_m2'], '909 €')
        self.assertNotIn('price', found)

    def test_ground_floor_is_a_floor(self):
        self.assertEqual(labels.floor_value('Партер', extract.number), 0)


class ExtractTests(SimpleTestCase):
    def test_a_filter_menu_is_not_an_asking_price(self):
        record = extract.extract(MENU, 'https://example.com/flat/162/')
        self.assertNotEqual(record['price_eur'], 55000)

    def test_price_is_derived_from_a_rate_and_marked_as_derived(self):
        record = extract.extract(MENU, 'https://example.com/flat/162/')
        self.assertEqual(record['price_eur'], 909 * 33)
        self.assertTrue(record['data_flags']['price_derived'])
        self.assertIn('×', record['price_raw'])

    def test_rooms_convert_to_bedrooms(self):
        record = extract.extract(MENU, 'https://example.com/flat/162/')
        self.assertEqual(record['bedrooms'], 0)          # "Комнат: 1" is a studio

    def test_a_sold_listing_is_recognised(self):
        record = extract.extract(SOLD_PAGE, 'https://example.com/p/1/')
        self.assertEqual(record['status'], 'sold')

    def test_a_rental_is_not_stored_as_a_sale(self):
        record = extract.extract(RENTAL, 'https://example.com/estate/9/')
        self.assertEqual(record['deal_type'], 'rent')
        self.assertIsNone(record['price_eur'])           # "При поискване"
        self.assertEqual(record['floor'], 0)

    def test_a_page_stating_nothing_measurable_is_not_a_listing(self):
        # Sitemaps list town pages beside real listings; storing one would put
        # an empty row in front of a client.
        page = '<html><body><h1>Брястовец</h1><p>' + 'Общи сведения. ' * 30 + '</p></body></html>'
        self.assertIsNone(extract.extract(page, 'https://example.com/s-bryastovets-t114'))


class CatalogTests(SimpleTestCase):
    def test_a_base_tag_is_honoured(self):
        # One agency declares <base href="https://site.bg/"> and links relatively.
        # Resolving against the current URL instead doubled every path.
        page = ('<html><head><base href="https://www.bratanov.bg/"></head><body>'
                '<a href="bg/estate/view/1949">flat</a></body></html>')
        base = catalog.BASE.search(page)
        self.assertEqual(base.group(1), 'https://www.bratanov.bg/')

    def test_a_later_catalogue_page_is_recognised(self):
        base = 'https://bolgarskiydom.com/vtorichnaya-nedvizhimost/'
        self.assertTrue(catalog._is_page_of(base + '?page=2', base))
        self.assertFalse(catalog._is_page_of('https://bolgarskiydom.com/news/?page=2', base))


class DiscoverTests(SimpleTestCase):
    def test_a_doubled_base_url_is_repaired(self):
        self.assertEqual(
            discover.clean('https://site.bghttps://site.bg/flat-t114'),
            'https://site.bg/flat-t114')

    def test_language_duplicates_are_dropped(self):
        spec = sites.RECIPES['grand-estates-group']
        self.assertTrue(sites.is_listing('https://grandgroupbg.com/property/x', spec))
        self.assertFalse(sites.is_listing('https://grandgroupbg.com/en/property/x', spec))


class StoreTests(TestCase):
    def setUp(self):
        self.agency = Agency.objects.create(slug='a', name='А', source_kind=SourceKind.NONE)
        self.today = dt.date(2026, 9, 18)

    def _record(self, **over):
        base = {'title': 'Роял Сан', 'title_norm': 'royal san', 'location': 'Слънчев бряг',
                'location_raw': 'Слънчев бряг', 'location_salvaged': False,
                'price_eur': 50000, 'price_raw': '50 000 €', 'bedrooms': 1,
                'area_m2': 60, 'floor': 3, 'property_kind': 'apartment',
                'deal_type': 'sale', 'view': '', 'status': 'active', 'furnished': None,
                'maintenance_raw': '', 'notes': '', 'ref': '', 'data_flags': {},
                'features': {}, 'dedup_key': '',
                'listing_url': 'https://a.example/p/1'}
        base.update(over)
        return base

    def test_the_url_is_the_identity_and_a_second_pass_skips_it(self):
        store.store(self.agency, self._record(), {}, self.today)
        self.assertEqual(store.known_urls(self.agency),
                         {'https://a.example/p/1': store.fingerprint('https://a.example/p/1')})

    def test_re_reading_the_same_url_updates_rather_than_duplicates(self):
        store.store(self.agency, self._record(), {}, self.today)
        outcome = store.store(self.agency, self._record(price_eur=47000), {}, self.today)
        self.assertEqual(outcome, 'changed')
        self.assertEqual(Offer.objects.filter(source=OfferSource.WEB).count(), 1)
        offer = Offer.objects.get()
        self.assertEqual(offer.prev_price_eur, 50000)
        self.assertTrue(offer.history.filter(field='price_eur').exists())

    def test_an_unchanged_listing_writes_no_history(self):
        store.store(self.agency, self._record(), {}, self.today)
        self.assertEqual(store.store(self.agency, self._record(), {}, self.today), 'same')
        self.assertFalse(Offer.objects.get().history.exists())

    def test_a_sold_listing_is_never_stored(self):
        # The catalogue should not contain sold flats at all; when a stale badge
        # slips through, it is dropped rather than kept as an unusable row.
        self.assertEqual(store.store(self.agency, self._record(status='sold'), {}, self.today),
                         'sold')
        self.assertEqual(Offer.objects.count(), 0)

    def test_a_listing_that_sells_stops_being_live_stock(self):
        store.store(self.agency, self._record(), {}, self.today)
        store.store(self.agency, self._record(status='sold'), {}, self.today)
        offer = Offer.objects.get()
        self.assertFalse(offer.is_active)
        self.assertEqual(offer.status, 'sold')

    def test_a_withdrawn_listing_is_retired_not_deleted(self):
        store.store(self.agency, self._record(), {}, self.today)
        gone = store.retire_missing(self.agency, set(), self.today)
        self.assertEqual(gone, 1)
        self.assertEqual(Offer.objects.count(), 1)
        self.assertFalse(Offer.objects.get().is_active)
