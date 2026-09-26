import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from market.models import City, SiteProbe
from market.sofia_crawl import ensure_agency, store_offer
from market.sofia_sources import ADAPTERS
from market.tests.test_sofia_sources import FixtureClient, fixture, parsed
from sourcing.models import CrawlRun


class RetryTests(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        settings = override_settings(RUNS_DIR=Path(folder.name))
        settings.enable()
        self.addCleanup(settings.disable)

    def previous(self, slug='yavlena', deal='sale', *, blocked=0, image=False):
        agency = ensure_agency(ADAPTERS[slug])
        p = parsed(slug, deal)
        run = CrawlRun.objects.create(kind='sites', run_date=timezone.localdate(), status='partial')
        row = dict(ref=p['ref'], url=p['url'], deal=deal)
        outcomes = [dict(ref=p['ref'], url=p['url'], error='previous parser failure')]
        if image:
            outcomes = [dict(ref=p['ref'], url=p['url'], outcome='stored'),
                        dict(ref=p['ref'], image_error='previous photo timeout')]
        probe = SiteProbe.objects.create(city=City.objects.get(slug='sofia'),
            agency_slug=slug, agency_name=agency.name, run_id=f'test-{run.pk}', status='ok',
            strategy=dict(discovered_urls=[row]))
        run.log = json.dumps(dict(stats=dict(agency=slug, city='sofia', blocked=blocked),
                                  outcomes=outcomes, probe_id=probe.pk))
        run.save()
        return agency, p, run

    def execute(self, run, pages):
        output = io.StringIO()
        client = FixtureClient(pages)
        with mock.patch('market.management.commands.retry_sofia.SourceClient', return_value=client), \
             mock.patch('market.management.commands.retry_sofia.save_image', return_value=False):
            call_command('retry_sofia', run=run.pk, stdout=output)
        latest = CrawlRun.objects.order_by('-pk').first()
        return json.loads(latest.log), client

    def test_retry_only_recorded_failed_details_stores_verified_offer(self):
        agency, p, run = self.previous()
        report, client = self.execute(run, {p['url']: fixture('yavlena', 'sale.html')[0]})
        self.assertEqual(report['stats']['stored'], 1)
        self.assertEqual(report['stats']['retry_of'], run.pk)
        self.assertFalse(report['stats']['discovery_complete'])
        self.assertTrue(report['stats']['detail_complete'])
        offer = agency.offers.get()
        self.assertEqual(offer.ref, p['ref'])
        self.assertEqual(offer.evidence['retry_of'], run.pk)
        self.assertEqual([r['url'] for r in client.responses], [f'https://{ADAPTERS["yavlena"].host}/robots.txt', p['url']])

    def test_blocked_or_running_source_is_rejected_before_network(self):
        agency, p, run = self.previous(blocked=1)
        with mock.patch('market.management.commands.retry_sofia.SourceClient') as client:
            with self.assertRaisesRegex(CommandError, 'blocked'):
                call_command('retry_sofia', run=run.pk)
            run.status = 'running'
            run.save()
            with self.assertRaisesRegex(CommandError, 'completed'):
                call_command('retry_sofia', run=run.pk)
            client.assert_not_called()

    def test_404_catalogue_link_is_recorded_without_retiring_an_existing_offer(self):
        agency, p, run = self.previous()
        offer, _ = store_offer(agency, p, {})
        report, client = self.execute(run, {})
        self.assertEqual(report['stats']['stale_catalogue_links'], 1)
        self.assertEqual(report['stats']['errors'], 0)
        offer.refresh_from_db()
        self.assertTrue(offer.is_active)

    def test_image_retry_retains_home_rental_deal_from_discovery(self):
        agency, p, run = self.previous('home2u', 'rent', image=True)
        report, client = self.execute(run, {p['url']: fixture('home2u', 'rent.html')[0]})
        self.assertEqual(report['stats']['stored'], 1)
        self.assertEqual(agency.offers.get().deal_type, 'rent')
