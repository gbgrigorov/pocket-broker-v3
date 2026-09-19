# -*- coding: utf-8 -*-
"""Tests for reconnaissance parsing. No network: every input is a literal.

The listing detector earns its own tests because getting it wrong is expensive
in both directions. Too loose and we build a parser against a news feed, which
is how a previous scraper in this family died. Too strict and we drop real
agencies -- the first version vetoed on `<article>` and threw away four.
"""
from django.test import SimpleTestCase, TestCase

from market import recon


class RobotsTests(SimpleTestCase):
    def test_reads_disallow_and_sitemap_lines(self):
        disallow, sitemaps = recon.parse_robots(
            'User-agent: *\n'
            'Disallow: /admin/\n'
            'Disallow: /property/search\n'
            'Sitemap: https://x.bg/sitemap.xml\n')
        self.assertEqual(disallow, ['/admin/', '/property/search'])
        self.assertEqual(sitemaps, ['https://x.bg/sitemap.xml'])

    def test_commented_rules_are_not_rules(self):
        """matex.bg ships its only Disallow commented out."""
        disallow, _ = recon.parse_robots('User-agent: *\n#Disallow: /advanced_search.php\n')
        self.assertEqual(disallow, [])

    def test_bare_disallow_means_allow_everything(self):
        disallow, _ = recon.parse_robots('User-agent: *\nDisallow:\n')
        self.assertEqual(disallow, [])


class UrlShapeTests(SimpleTestCase):
    def test_collapses_slugs_and_ids_into_one_shape(self):
        shapes = recon.url_shapes([
            'https://x.bg/property/tristaen-apartament-varna',
            'https://x.bg/property/dvustaen-apartament-chayka',
            'https://x.bg/property/699',
            'https://x.bg/contacts',
        ])
        top = dict((sh, n) for sh, n, _ in shapes)
        self.assertEqual(top['/property/*'], 3)
        self.assertEqual(top['/contacts'], 1)

    def test_keeps_samples_so_a_shape_can_be_verified(self):
        shapes = recon.url_shapes(['https://x.bg/imot/abc-def-ghi-jkl'])
        _shape, _count, samples = shapes[0]
        self.assertEqual(samples, ['https://x.bg/imot/abc-def-ghi-jkl'])


class ListingDetectorTests(SimpleTestCase):
    LISTING = ('<h1>Тристаен апартамент</h1>'
               '<span class="price">125 000 €</span>'
               '<li>Площ: 92 кв.м</li>')

    def test_priced_and_measured_is_a_listing(self):
        verdict, _why = recon.looks_like_listing(self.LISTING)
        self.assertTrue(verdict)

    def test_wordpress_article_wrapper_does_not_veto(self):
        """The bug that rejected roneva, home2u, ekip-sart and demos-2000."""
        verdict, _why = recon.looks_like_listing('<article>' + self.LISTING + '</article>')
        self.assertTrue(verdict)

    def test_schema_news_article_is_vetoed(self):
        body = ('<script type="application/ld+json">{"@type": "NewsArticle"}</script>'
                '<p>Цените във Варна растат: 1 500 €/кв.м за двустаен</p>')
        verdict, _why = recon.looks_like_listing(body)
        self.assertFalse(verdict)

    def test_a_page_with_only_a_price_is_not_enough(self):
        verdict, _why = recon.looks_like_listing('<p>Комисиона 2 000 €</p>')
        self.assertFalse(verdict)


class PageKindTests(SimpleTestCase):
    """Detail vs catalogue. A recipe needs both, in different slots."""

    CARD = '<div class="card"><span>{} €</span><span>{} кв.м</span></div>'

    def test_one_priced_measured_property_is_a_detail_page(self):
        kind, _why = recon.page_kind(
            '<h1>Тристаен</h1><span>125 000 €</span><li>92 кв.м</li>')
        self.assertEqual(kind, 'detail')

    def test_twenty_linked_cards_is_a_catalogue(self):
        body = ''.join(
            f'<a href="/property/flat-number-{i}">' + self.CARD.format(100000 + i * 1000, 60 + i)
            for i in range(20))
        kind, _why = recon.page_kind(body, shape='/property/*', base='https://x.bg/')
        self.assertEqual(kind, 'catalogue')

    def test_detail_page_with_a_similar_properties_carousel_stays_detail(self):
        """The regression that rejected titan-properties and roneva.

        Their detail pages carry a handful of similar flats at the bottom, so
        counting prices called them catalogues. Counting sibling links does not.
        """
        body = ('<h1>Тристаен</h1><span>125 000 €</span><li>92 кв.м</li>'
                + ''.join(f'<a href="/property/similar-flat-{i}">'
                          + self.CARD.format(130000, 80) for i in range(5)))
        kind, _why = recon.page_kind(body, shape='/property/*', base='https://x.bg/')
        self.assertEqual(kind, 'detail')

    def test_catalogue_does_not_pass_as_a_listing(self):
        """/tip/apartament and /selski-imoti were accepted before this split."""
        body = ''.join(
            f'<a href="/property/flat-{i}-in-varna">' + self.CARD.format(100000 + i * 1000, 60 + i)
            for i in range(12))
        verdict, _why = recon.looks_like_listing(
            body, shape='/property/*', base='https://x.bg/')
        self.assertFalse(verdict)

    def test_a_page_about_nothing_priced_is_other(self):
        kind, _why = recon.page_kind('<h1>За нас</h1><p>Основана 2006.</p>')
        self.assertEqual(kind, 'other')

    def test_news_stays_vetoed_regardless_of_counts(self):
        body = ('<script type="application/ld+json">{"@type":"NewsArticle"}</script>'
                + ''.join(self.CARD.format(100000, 70) for _ in range(9)))
        kind, _why = recon.page_kind(body)
        self.assertEqual(kind, 'other')

    def test_shape_of_matches_url_shapes(self):
        self.assertEqual(recon.shape_of('https://x.bg/property/tristaen-apartament-varna'),
                         '/property/*')
        self.assertEqual(recon.shape_of('https://x.bg/property/699'), '/property/*')

    def test_recognises_area_written_several_ways(self):
        for area in ('92 кв.м', '92 m2', '92 m²', '92 кв. м', '92 sq m'):
            with self.subTest(area=area):
                self.assertTrue(recon.AREA_RE.search(f'Площ: {area}'), area)

    def test_recognises_price_in_both_currencies(self):
        for price in ('125 000 €', '€125,000', '244 478 лв.', 'EUR 125000', '125000 BGN'):
            with self.subTest(price=price):
                self.assertTrue(recon.PRICE_RE.search(price), price)


class LinkHarvestTests(SimpleTestCase):
    BODY = ('<a href="/property/one">1</a>'
            '<a href="https://other.bg/property/x">off-host</a>'
            '<a href="/style.css">css</a>'
            '<a href="mailto:a@b.bg">mail</a>'
            '<a href="/property/two#gallery">2</a>')

    def test_keeps_only_same_host_document_links(self):
        found = recon.links_on(self.BODY, 'https://x.bg/')
        self.assertEqual(found, {'https://x.bg/property/one', 'https://x.bg/property/two'})

    def test_platform_detection_prefers_the_theme_over_wordpress(self):
        self.assertEqual(recon.detect_platform('<link href="/wp-content/themes/houzez/a.css">'),
                         ['Houzez'])


class ProbeRunOrderingTests(TestCase):
    """A superseded sweep that finishes late must not win.

    This happened: three sweeps overlapped, the oldest one finished last, and
    because rows were selected by timestamp it silently reinstated results a
    bug fix had already removed. Two agencies went back to reporting no
    listings with nothing appearing to fail.
    """

    def test_latest_follows_run_start_not_row_timestamp(self):
        from django.utils import timezone
        from datetime import timedelta
        from market.models import SiteProbe

        now = timezone.now()
        stale_start = now - timedelta(minutes=30)
        good_start = now - timedelta(minutes=10)

        # The good run started later but its rows landed first.
        SiteProbe.objects.create(
            agency_slug='roneva', agency_name='Ронева', run_id='good',
            run_started=good_start, status='ok', listing_pattern='/property/*',
            listing_count=779)
        # The stale run started earlier and its rows landed last.
        stale = SiteProbe.objects.create(
            agency_slug='roneva', agency_name='Ронева', run_id='stale',
            run_started=stale_start, status='no_listings')
        SiteProbe.objects.filter(pk=stale.pk).update(probed_at=now + timedelta(minutes=5))

        chosen = SiteProbe.latest()['roneva']
        self.assertEqual(chosen.run_id, 'good')
        self.assertEqual(chosen.listing_pattern, '/property/*')

    def test_an_agency_missing_from_the_newest_run_keeps_its_last_known_state(self):
        from django.utils import timezone
        from datetime import timedelta
        from market.models import SiteProbe

        now = timezone.now()
        SiteProbe.objects.create(
            agency_slug='matex', agency_name='Матекс', run_id='old',
            run_started=now - timedelta(minutes=30), status='ok',
            listing_pattern='/bg/imot/*', listing_count=40)
        SiteProbe.objects.create(
            agency_slug='roneva', agency_name='Ронева', run_id='new',
            run_started=now, status='ok')

        latest = SiteProbe.latest()
        self.assertEqual(latest['matex'].listing_pattern, '/bg/imot/*')
        self.assertIn('roneva', latest)
