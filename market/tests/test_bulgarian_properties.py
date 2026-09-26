"""Regression tests for the verified Bulgarian Properties adapter.

All source responses are local fixtures or explicit mutations of one.  The
transport tests mock curl, so this module never contacts the source or a DB.
"""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from market.bulgarian_properties import (
    CATALOGUE,
    ParseError,
    catalogue,
    detail,
    number,
)
from market.source_http import SourceBlocked, SourceClient, decode_html


FIXTURES = Path(__file__).parent / 'fixtures' / 'bulgarian_properties'
SALE_URL = ('https://www.bulgarianproperties.com/1-bedroom_apartments_in_Bulgaria/'
            'AD91504BG_1-bedroom_apartment_for_sale_in_Sofia.html')
RENT_URL = ('https://www.bulgarianproperties.com/1-bedroom_apartments_in_Bulgaria/'
            'AD91674BG_1-bedroom_apartment_for_rent_in_Sofia.html')
PROJECT_URL = ('https://www.bulgarianproperties.com/Apartments_(various_types)_in_Bulgaria/'
               'AD82111BG_Apartments_(various_types)_for_sale_in_Sofia.html')


def fixture(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


class CatalogueTests(SimpleTestCase):
    def test_reads_only_verified_cards_not_page_wide_ad_or_seo_links(self):
        html = fixture('catalogue.html').replace(
            '</body>',
            '<aside class="seo-recommendations">'
            '<a href="https://www.bulgarianproperties.com/Houses_in_Bulgaria/'
            'AD99999BG_House_for_sale_near_Sofia.html">Near Sofia</a>'
            '</aside></body>')

        parsed = catalogue(html)

        self.assertEqual([row['ref'] for row in parsed['rows']], ['77779', '82111'])
        self.assertNotIn('99999', {row['ref'] for row in parsed['rows']})
        self.assertEqual(parsed['rows'][0]['location'], 'Sofia , Quarter Banishora')

    def test_index1_is_human_page_two_and_advances_to_index2(self):
        url = CATALOGUE.replace('index.html', 'index1.html')

        parsed = catalogue(fixture('catalogue_page2.html'), url)

        self.assertEqual(parsed['page_index'], 1)
        self.assertEqual([row['ref'] for row in parsed['rows']], ['89685', '89431'])
        self.assertEqual(
            parsed['next_url'],
            CATALOGUE.replace('index.html', 'index2.html'),
        )

    def test_consecutive_pages_do_not_repeat_source_references(self):
        pages = [
            catalogue(fixture('catalogue.html'), CATALOGUE),
            catalogue(fixture('catalogue_page2.html'), CATALOGUE.replace('index.html', 'index1.html')),
            catalogue(fixture('catalogue_page3.html'), CATALOGUE.replace('index.html', 'index2.html')),
        ]
        refs = [[row['ref'] for row in page['rows']] for page in pages]

        self.assertEqual([page['page_index'] for page in pages], [0, 1, 2])
        self.assertEqual(len(set().union(*map(set, refs))), sum(map(len, refs)))

    def test_card_id_must_agree_with_detail_url(self):
        html = fixture('catalogue.html').replace(
            ' id="77779"', ' id="12345"', 1)
        with self.assertRaisesRegex(ParseError, 'card ID'):
            catalogue(html)

    def test_generic_or_broken_html_is_not_a_catalogue(self):
        for html in ('<html><h1>Properties in Sofia</h1></html>',
                     '<div id="propertiesItemsContentWrapper"></div>'):
            with self.subTest(html=html):
                with self.assertRaises(ParseError):
                    catalogue(html)

    def test_region_catalogue_url_is_rejected_even_with_valid_card_markup(self):
        with self.assertRaises(ParseError):
            catalogue(
                fixture('catalogue.html'),
                'https://www.bulgarianproperties.com/Sofia_property/index.html',
            )

    def test_conflicting_duplicate_source_reference_rejects_the_page(self):
        conflicting = (
            '<div class="component component-property-item" id="77779">'
            '<a class="title" href="https://www.bulgarianproperties.com/'
            'Apartments_in_Bulgaria/AD77779BG_conflicting_flat_for_sale_in_Sofia.html">'
            'Conflicting flat</a><span class="location">Sofia, Other quarter</span>'
            '</div>'
        )
        html = fixture('catalogue.html').replace(
            '<div class="button-wrapper">', conflicting + '<div class="button-wrapper">', 1)

        with self.assertRaises(ParseError):
            catalogue(html)


class NumberTests(SimpleTestCase):
    def test_thousands_and_nonbreaking_separators(self):
        for raw in ('275 000', '275\u00a0000', '275\u202f000', '275\u2009000',
                    "275'000", '275’000', '275,000'):
            with self.subTest(raw=raw):
                self.assertEqual(number(raw), Decimal('275000'))

    def test_decimal_conventions_and_invalid_values(self):
        self.assertEqual(number('1.234,56'), Decimal('1234.56'))
        self.assertEqual(number('1,234.56'), Decimal('1234.56'))
        self.assertEqual(number('78,25'), Decimal('78.25'))
        self.assertIsNone(number('price on request'))
        self.assertIsNone(number(''))

    def test_dot_separated_thousands_are_not_misread_as_a_decimal(self):
        self.assertEqual(number('185.000'), Decimal('185000'))


class DetailTests(SimpleTestCase):
    def test_sale_offer_has_stable_identity_and_unit_fields(self):
        parsed = detail(fixture('sale.html'), SALE_URL + '?campaign=ignored#gallery')
        record = parsed['record']

        self.assertEqual(parsed['outcome'], 'offer')
        self.assertEqual(parsed['ref'], '91504')
        self.assertEqual(parsed['url'], SALE_URL)
        self.assertEqual(record['listing_url'], SALE_URL)
        self.assertEqual(record['deal_type'], 'sale')
        self.assertEqual(record['price_eur'], Decimal('275000'))
        self.assertEqual(record['area_m2'], Decimal('72.00'))
        self.assertEqual(record['bedrooms'], 1)
        self.assertEqual(record['floor'], 2)
        self.assertTrue(record['dedup_key'])

    def test_rent_offer_has_monthly_price_and_unit_fields(self):
        parsed = detail(fixture('rent.html'), RENT_URL)
        record = parsed['record']

        self.assertEqual(parsed['outcome'], 'offer')
        self.assertEqual(parsed['ref'], '91674')
        self.assertEqual(record['deal_type'], 'rent')
        self.assertEqual(record['price_eur'], Decimal('700'))
        self.assertEqual(record['area_m2'], Decimal('78.00'))
        self.assertEqual(record['bedrooms'], 1)
        self.assertEqual(record['floor'], 5)

    def test_development_aggregate_offer_is_not_emitted_as_a_unit(self):
        parsed = detail(fixture('project.html'), PROJECT_URL)

        self.assertEqual(parsed, {
            'outcome': 'project',
            'ref': '82111',
            'url': PROJECT_URL,
            'location': 'Sofia, Manastirski Livadi',
            'low_price': 252160,
            'high_price': 1732762,
        })
        self.assertNotIn('record', parsed)

    def test_textual_price_ranges_remain_projects_without_aggregate_jsonld(self):
        for separator in ('—', 'to'):
            with self.subTest(separator=separator):
                html = fixture('project.html')
                html = html.replace('"@type":"AggregateOffer"', '"@type":"Offer"')
                html = html.replace('1,2,3</span>', '1</span>')
                html = html.replace(
                    '252 160 - 1 732 762', f'252 160 {separator} 1 732 762')

                parsed = detail(html, PROJECT_URL)

                self.assertEqual(parsed['outcome'], 'project')
                self.assertNotIn('record', parsed)

    def test_unknown_price_area_and_images_remain_unknown(self):
        html = fixture('sale.html')
        html = html.replace('"image":"https://static.bulgarianproperties.com/property-images/big/91504_1.jpg",', '')
        html = html.replace('"price":275000,', '')
        html = html.replace(
            '<span class="regular-price" id="newprice"><span class="price_symbol">€</span> 275 000</span>',
            '<span class="regular-price" id="newprice">Price on request</span>')
        html = html.replace(
            '<span class="value">72.00 m<sup>2</sup></span>',
            '<span class="value">Ask agency</span>', 1)

        parsed = detail(html, SALE_URL)

        self.assertIsNone(parsed['record']['price_eur'])
        self.assertIsNone(parsed['record']['area_m2'])
        self.assertEqual(parsed['images'], [])

    def test_nonbreaking_thousands_separator_is_a_total_price(self):
        html = fixture('sale.html').replace('275 000</span>', '275\u00a0000</span>')
        self.assertEqual(detail(html, SALE_URL)['record']['price_eur'], Decimal('275000'))

    def test_cyrillic_utf8_title_is_preserved_with_english_field_schema(self):
        html = fixture('sale.html').replace(
            'One-bedroom apartment in Manastirski livadi, Sofia</h1>',
            'Едностаен апартамент в Манастирски ливади, София</h1>')

        record = detail(html, SALE_URL)['record']

        self.assertEqual(record['title'], 'Едностаен апартамент в Манастирски ливади, София')
        self.assertEqual(record['deal_type'], 'sale')
        self.assertEqual(record['type_raw'], '1-bedroom apartment')

    def test_literal_newline_inside_jsonld_string_is_accepted(self):
        html = fixture('sale.html').replace(
            '"name":"One-bedroom apartment in Manastirski livadi, Sofia"',
            '"name":"One-bedroom apartment\nin Manastirski livadi, Sofia"', 1)

        parsed = detail(html, SALE_URL)

        self.assertEqual(parsed['outcome'], 'offer')
        self.assertEqual(parsed['images'], [
            'https://static.bulgarianproperties.com/property-images/big/91504_1.jpg'])

    def test_only_structured_or_open_graph_main_images_are_returned(self):
        html = fixture('sale.html').replace(
            '</head>',
            '<meta property="og:image" content="https://static.bulgarianproperties.com/'
            'property-images/big/91504_main.jpg">'
            '<meta property="og:image" content="https://tracker.example/91504.jpg">'
            '</head>')

        parsed = detail(html, SALE_URL)

        self.assertEqual(parsed['images'], [
            'https://static.bulgarianproperties.com/property-images/big/91504_1.jpg',
            'https://static.bulgarianproperties.com/property-images/big/91504_main.jpg',
        ])
        self.assertNotIn('1789137895B91504_11.jpg', ' '.join(parsed['images']))

    def test_near_or_outside_sofia_is_not_a_city_offer(self):
        for location in ('Near Sofia, Lozen', 'Plovdiv, Center'):
            with self.subTest(location=location):
                html = fixture('sale.html').replace(
                    'Sofia, Manastirski Livadi</span>', f'{location}</span>', 1)
                parsed = detail(html, SALE_URL)
                self.assertEqual(parsed['outcome'], 'outside_city')
                self.assertEqual(parsed['ref'], '91504')

    def test_near_sofia_canonical_is_outside_even_when_location_says_sofia(self):
        html = fixture('sale.html').replace('_in_Sofia.html', '_near_Sofia.html')
        url = SALE_URL.replace('_in_Sofia.html', '_near_Sofia.html')

        parsed = detail(html, url)

        self.assertEqual(parsed['outcome'], 'outside_city')
        self.assertEqual(parsed['location'], 'Sofia, Manastirski Livadi')

    def test_implausible_floor_and_bedroom_values_are_quarantined(self):
        html = fixture('sale.html')
        html = html.replace(
            '<span class="label">Bedrooms</span><span class="value">1</span>',
            '<span class="label">Bedrooms</span><span class="value">999</span>', 1)
        html = html.replace(
            '<span class="label">Floor</span><span class="value">2 of 5</span>',
            '<span class="label">Floor</span><span class="value">999 of 999</span>', 1)

        record = detail(html, SALE_URL)['record']

        self.assertIsNone(record['bedrooms'])
        self.assertIsNone(record['floor'])

    def test_reserved_or_sold_listing_is_unavailable(self):
        for marker in ('Reserved', 'Sold'):
            with self.subTest(marker=marker):
                html = fixture('sale.html').replace(
                    '<div class="labels">',
                    f'<div class="labels"><span class="label">{marker}</span>')
                parsed = detail(html, SALE_URL)
                self.assertEqual(parsed['outcome'], 'unavailable')
                self.assertIn(marker.lower(), parsed['status'])

    def test_structured_out_of_stock_is_unavailable(self):
        html = fixture('sale.html').replace('schema.org/InStock', 'schema.org/OutOfStock')
        self.assertEqual(detail(html, SALE_URL)['outcome'], 'unavailable')

    def test_canonical_identity_mismatch_is_rejected(self):
        html = fixture('sale.html').replace('AD91504BG_', 'AD99999BG_', 1)
        with self.assertRaisesRegex(ParseError, 'Canonical source identity'):
            detail(html, SALE_URL)

    def test_foreign_city_page_still_requires_matching_visible_reference(self):
        html = fixture('sale.html')
        html = html.replace(
            'Sofia, Manastirski Livadi</span>', 'Plovdiv, Center</span>', 1)
        html = html.replace('Sfa 91504', 'Sfa 99999', 1)

        with self.assertRaises(ParseError):
            detail(html, SALE_URL)

    def test_structured_identity_mismatch_is_rejected(self):
        html = fixture('sale.html').replace(
            '"url":"https://www.bulgarianproperties.com/1-bedroom_apartments_in_Bulgaria/'
            'AD91504BG_',
            '"url":"https://www.bulgarianproperties.com/1-bedroom_apartments_in_Bulgaria/'
            'AD99999BG_',
            1,
        )
        with self.assertRaisesRegex(ParseError, 'Structured offer'):
            detail(html, SALE_URL)

    def test_generic_or_incomplete_page_cannot_parse_as_a_listing(self):
        for html in ('<html><title>Property</title></html>',
                     '<link rel="canonical" href="' + SALE_URL + '">'):
            with self.subTest(html=html):
                with self.assertRaises(ParseError):
                    detail(html, SALE_URL)


class DecodeHtmlTests(SimpleTestCase):
    def test_utf8_cyrillic(self):
        body, encoding = decode_html(
            '<meta charset="utf-8"><h1>Апартамент в София</h1>'.encode('utf-8'))
        self.assertEqual(encoding, 'utf-8')
        self.assertIn('Апартамент в София', body)

    def test_windows_1251_cyrillic(self):
        raw = '<meta charset="windows-1251"><h1>Апартамент в София</h1>'.encode('cp1251')
        body, encoding = decode_html(raw)
        self.assertEqual(encoding, 'windows-1251')
        self.assertIn('Апартамент в София', body)
        self.assertNotIn('\ufffd', body)

    def test_iso_8859_1_html_label_uses_cp1252_smart_dash(self):
        raw = b'<meta charset="iso-8859-1"><title>SKY TOWERS \x96 Sofia</title>'
        body, encoding = decode_html(raw)
        self.assertEqual(encoding, 'cp1252')
        self.assertIn('SKY TOWERS – Sofia', body)
        self.assertNotIn('\ufffd', body)


class SourceClientTests(SimpleTestCase):
    HOST = 'www.bulgarianproperties.com'

    @staticmethod
    def curl_result(args, *, status=200, body=b'<meta charset="utf-8">ok', headers=b'', returncode=0):
        Path(args[args.index('-o') + 1]).write_bytes(body)
        Path(args[args.index('-D') + 1]).write_bytes(headers)
        return SimpleNamespace(stdout=str(status).encode(), stderr=b'', returncode=returncode)

    def test_rejects_non_https_credentials_ports_and_other_hosts(self):
        client = SourceClient({self.HOST})
        bad = (
            'http://www.bulgarianproperties.com/',
            'https://user@www.bulgarianproperties.com/',
            'https://www.bulgarianproperties.com:444/',
            'https://evil.example/',
        )
        for url in bad:
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    client.check_url(url)

    @mock.patch('market.source_http.fetch._wait')
    @mock.patch('market.source_http.subprocess.run')
    def test_allowed_redirect_is_followed_without_network(self, run, wait):
        calls = iter((
            (302, b'', b'HTTP/1.1 302 Found\r\nLocation: /next\r\n\r\n'),
            (200, '<h1>София</h1>'.encode('utf-8'),
             b'HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n'),
        ))

        def fake_curl(args, **_kwargs):
            status, body, headers = next(calls)
            return self.curl_result(args, status=status, body=body, headers=headers)

        run.side_effect = fake_curl
        response = SourceClient({self.HOST}).get(f'https://{self.HOST}/start')

        self.assertEqual(response['status'], 200)
        self.assertEqual(response['final_url'], f'https://{self.HOST}/next')
        self.assertIn('София', response['body'])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(wait.call_count, 2)

    @mock.patch('market.source_http.fetch._wait')
    @mock.patch('market.source_http.subprocess.run')
    def test_block_response_stops_all_later_requests(self, run, _wait):
        run.side_effect = lambda args, **_kwargs: self.curl_result(
            args, status=403, body=b'<title>Access denied</title>',
            headers=b'HTTP/1.1 403 Forbidden\r\n\r\n')
        client = SourceClient({self.HOST})

        with self.assertRaises(SourceBlocked):
            client.get(f'https://{self.HOST}/first')
        with self.assertRaises(SourceBlocked):
            client.get(f'https://{self.HOST}/second')

        run.assert_called_once()

    @mock.patch('market.source_http.fetch._wait')
    @mock.patch('market.source_http.subprocess.run')
    def test_redirect_cannot_leave_verified_host(self, run, _wait):
        run.side_effect = lambda args, **_kwargs: self.curl_result(
            args, status=302,
            headers=b'HTTP/1.1 302 Found\r\nLocation: https://evil.example/\r\n\r\n')

        with self.assertRaises(ValueError):
            SourceClient({self.HOST}).get(f'https://{self.HOST}/start')

        run.assert_called_once()

    @mock.patch('market.source_http.fetch._wait')
    @mock.patch('market.source_http.subprocess.run')
    def test_verify_human_and_cloudflare_challenges_stop_the_source(self, run, _wait):
        challenge_pages = (
            b'<html><title>Verify you are human</title></html>',
            b'<html><title>Checking your browser</title>'
            b'<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>'
            b'</html>',
        )
        for body in challenge_pages:
            with self.subTest(body=body):
                run.reset_mock()
                run.side_effect = lambda args, **_kwargs: self.curl_result(
                    args, status=200, body=body,
                    headers=b'HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n')

                with self.assertRaises(SourceBlocked):
                    SourceClient({self.HOST}).get(f'https://{self.HOST}/challenge')

                run.assert_called_once()
