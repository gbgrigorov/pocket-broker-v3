# -*- coding: utf-8 -*-
"""The Varna crawl. Sitemap-first, main image only, everything recorded.

Why this exists beside the vendored `crawl_sites`. That command walks each
agency's *catalogue*, which is the right answer for a daily run: a catalogue
holds what is advertised today, so sold flats are never fetched at all.

This is not a daily run. It is the first pass over a market nobody has mapped,
and the question it has to answer is what is actually there -- including how
much of each agency's sitemap is stale, which is the number that decides
whether catalogue or sitemap is cheaper for that site from tomorrow on. You
cannot measure that by never looking.

So: sitemaps where they exist, catalogue where they do not, one main photo per
listing, and a JSONL trace of every URL touched -- status, timing, bytes, which
fields the extractor found and which it missed. `manage.py crawl_report` turns
that trace into docs/crawl-report-<date>.md.
"""
import datetime as dt
import json
import time
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from market import images
from sourcing.models import Agency, CrawlRun, Offer, OfferImage, OfferSource
from sourcing.web import catalog, discover, extract, fetch, sites, store

# Fields worth measuring fill rates for. A crawl that stores 6 000 offers with
# no area on 40% of them is not a successful crawl, and only counting rows
# would call it one.
TRACKED = ('price_eur', 'area_m2', 'bedrooms', 'floor', 'location',
           'property_kind', 'deal_type', 'title')


class Command(BaseCommand):
    help = 'Crawl the Varna agencies, recording everything for later optimisation.'

    def add_arguments(self, parser):
        parser.add_argument('--agency', action='append', dest='agencies')
        parser.add_argument('--limit', type=int, help='max listings per agency')
        parser.add_argument('--workers', type=int,
                            default=int(getattr(settings, 'CRAWL_WORKERS', 4)))
        parser.add_argument('--no-images', action='store_true')
        parser.add_argument('--discover-only', action='store_true')
        parser.add_argument('--refresh', action='store_true',
                            help='re-fetch listings already stored')

    def handle(self, *args, **options):
        agencies = self._agencies(options)
        if not agencies:
            self.stdout.write(self.style.WARNING('No agencies with a recipe.'))
            return

        self.run = CrawlRun.objects.create(kind='sites', run_date=dt.date.today(),
                                           status='running')
        self.trace_path = (settings.RUNS_DIR /
                           f'crawl-{dt.date.today():%Y-%m-%d}-{self.run.pk}.jsonl')
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        self.options = options
        self.started = time.monotonic()

        self.stdout.write(
            f'Crawl #{self.run.pk} · {len(agencies)} agencies · '
            f'{options["workers"]} workers, one per host, '
            f'{getattr(settings, "CRAWL_HOST_DELAY", 2.0)}s apart\n'
            f'Trace: {self.trace_path.name}\n')

        with ThreadPoolExecutor(max_workers=options['workers']) as pool:
            results = list(pool.map(self._one, agencies))

        self._finish(agencies, results)

    # ------------------------------------------------------------- per agency --

    def _agencies(self, options):
        queryset = Agency.objects.filter(duplicate_of__isnull=True, crawl_opt_out=False)
        if options['agencies']:
            queryset = queryset.filter(slug__in=options['agencies'])
        return [a for a in queryset.order_by('slug') if sites.recipe(a.slug)]

    def _discover(self, agency, spec):
        """Sitemap first; catalogue when there is no usable sitemap."""
        if spec.get('sitemaps'):
            found = discover.discover(agency.slug, spec)
            if found:
                return found, 'sitemap'
        if spec.get('catalog'):
            return catalog.discover(agency.slug, spec), 'catalog'
        return {}, 'none'

    def _one(self, agency):
        spec = sites.recipe(agency.slug)
        t0 = time.monotonic()
        found, method = self._discover(agency, spec)
        result = {'agency': agency.slug, 'method': method, 'found': len(found),
                  'new': 0, 'changed': 0, 'same': 0, 'failed': 0, 'skipped': 0,
                  'images': 0, 'image_missing': 0, 'sold': 0,
                  'fields': {f: 0 for f in TRACKED}, 'statuses': {},
                  'bytes': 0, 'seconds': 0.0}

        if self.options['discover_only']:
            result['seconds'] = round(time.monotonic() - t0, 1)
            self._say(agency, result)
            return result

        known = store.known_urls(agency)
        todo = [u for u in found if self.options['refresh'] or u not in known]
        result['skipped'] = len(found) - len(todo)
        if self.options['limit']:
            todo = todo[:self.options['limit']]

        today = dt.date.today()
        for url in todo:
            self._fetch_one(agency, spec, url, today, result)

        result['seconds'] = round(time.monotonic() - t0, 1)
        self._say(agency, result)
        return result

    def _fetch_one(self, agency, spec, url, today, result):
        t0 = time.monotonic()
        trace = {'agency': agency.slug, 'url': url, 'run': self.run.pk}
        response = fetch.get(url)
        trace['status'] = response['status']
        trace['bytes'] = len(response.get('body') or '')
        result['bytes'] += trace['bytes']
        result['statuses'][str(response['status'])] = \
            result['statuses'].get(str(response['status']), 0) + 1

        if response['status'] != 200 or not response['body']:
            result['failed'] += 1
            trace['outcome'] = 'fetch_failed'
            return self._trace(trace, t0)

        try:
            record = extract.extract(response['body'], url, spec)
        except Exception as exc:                                   # noqa: BLE001
            result['failed'] += 1
            trace['outcome'] = 'extract_error'
            trace['error'] = str(exc)[:200]
            return self._trace(trace, t0)

        if record is None:
            result['failed'] += 1
            trace['outcome'] = 'extract_none'
            return self._trace(trace, t0)

        # Which fields the extractor actually found, per URL. This is the map:
        # a site where area is missing on every page needs a recipe hint, and
        # without per-field counts that looks identical to a site with no areas.
        present = [f for f in TRACKED if record.get(f) not in (None, '', [])]
        for field in present:
            result['fields'][field] += 1
        trace['fields_found'] = present
        trace['fields_missing'] = [f for f in TRACKED if f not in present]
        if record.get('status') in ('sold', 'reserved'):
            result['sold'] += 1
        trace['listing_status'] = record.get('status') or ''

        path = fetch.save_snapshot(self.run.pk, agency.slug, url, response['body'])
        evidence = {'fetched_at': timezone.now().isoformat(), 'method': 'curl',
                    'http_status': response['status'], 'snapshot_path': path,
                    'quoted_price_text': record.get('price_raw', ''),
                    'run': self.run.pk, 'crawler': 'crawl_varna'}

        with transaction.atomic():
            outcome = store.store(agency, record, evidence, today)
        result[outcome] += 1
        trace['outcome'] = outcome

        if not self.options['no_images']:
            self._main_image(agency, url, response['body'], result, trace)

        return self._trace(trace, t0)

    def _main_image(self, agency, url, html, result, trace):
        offer = Offer.objects.filter(agency=agency,
                                     fingerprint=store.fingerprint(url)).first()
        if offer is None:
            return
        if offer.images.exists() and not self.options['refresh']:
            return
        found, why = images.fetch_main(html, url, agency.slug)
        if not found:
            result['image_missing'] += 1
            trace['image'] = f'none: {why}'
            return
        _obj, created = OfferImage.objects.get_or_create(
            offer=offer, sha256=found['sha256'],
            defaults={'local_path': found['local_path'],
                      'source_url': found['source_url'][:900], 'position': 0})
        if created:
            result['images'] += 1
        trace['image'] = found['sha256'][:16]
        trace['image_bytes'] = found['bytes']

    # ---------------------------------------------------------------- output --

    def _trace(self, trace, t0):
        trace['ms'] = int((time.monotonic() - t0) * 1000)
        with open(self.trace_path, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(trace, ensure_ascii=False) + '\n')

    def _say(self, agency, r):
        style = self.style.SUCCESS if r['new'] or r['same'] else self.style.WARNING
        self.stdout.write(style(
            f'  {agency.slug:20} {r["method"]:8} found={r["found"]:5} '
            f'new={r["new"]:5} same={r["same"]:4} failed={r["failed"]:4} '
            f'img={r["images"]:5} {r["seconds"]:6.0f}s'))

    def _finish(self, agencies, results):
        total = {k: sum(r[k] for r in results)
                 for k in ('found', 'new', 'changed', 'same', 'failed',
                           'skipped', 'images', 'image_missing', 'sold', 'bytes')}
        self.run.status = CrawlRun.OK if not total['failed'] else CrawlRun.PARTIAL
        self.run.finished_at = timezone.now()
        self.run.sources_ok = sum(1 for r in results if r['found'])
        self.run.sources_dead = sum(1 for r in results if not r['found'])
        self.run.offers_total = total['found']
        self.run.offers_new = total['new']
        self.run.offers_changed = total['changed']
        self.run.log = json.dumps(results, ensure_ascii=False, indent=1)
        self.run.save()

        elapsed = time.monotonic() - self.started
        self.stdout.write('\n' + '-' * 78)
        self.stdout.write(self.style.SUCCESS(
            f'{total["found"]:,} discovered · {total["new"]:,} new · '
            f'{total["changed"]:,} changed · {total["failed"]:,} failed · '
            f'{total["images"]:,} images · {total["sold"]:,} sold/reserved · '
            f'{total["bytes"] / 1e6:.0f} MB · {elapsed / 60:.1f} min'))
        self.stdout.write(f'Trace: {self.trace_path}')
        self.stdout.write('Next: python manage.py crawl_report')
