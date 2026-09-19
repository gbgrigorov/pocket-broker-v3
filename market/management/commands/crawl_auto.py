# -*- coding: utf-8 -*-
"""Crawl every agency the probe understood, without a hand-written recipe each.

Seven agencies were enough to write recipes for by hand. Forty-five are not,
and the market has more than forty-five. So the recipe is derived instead:
SiteProbe already records a listing URL shape that was verified against a live
page, and that is enough to build a spec the vendored catalogue walker accepts.

Catalogues, never sitemaps. A sitemap is an archive -- titan-properties
publishes 6 707 of them against 85 live Varna properties, and the head of
home2u's is entirely dead stock. The catalogue is what the agency is
advertising today, and it maintains itself.

Candidate catalogue URLs are derived from the listing shape (/property/* is
almost always reachable from /property/), tried in order, and the first that
actually returns listings wins. Nothing is assumed: an agency whose catalogue
cannot be found is recorded as such rather than guessed at.
"""
import datetime as dt
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from market import images, prices, recon
from market.models import SiteProbe
from sourcing.models import Agency, CrawlRun, Offer, OfferImage
from sourcing.web import catalog, extract, fetch, store

VARNA = None      # bound lazily from crawl_live, so the rule lives in one place


class Command(BaseCommand):
    help = 'Crawl all probed agencies using specs derived from their probes.'

    def add_arguments(self, parser):
        parser.add_argument('--agency', action='append', dest='agencies')
        parser.add_argument('--limit', type=int, help='max listings per agency')
        parser.add_argument('--workers', type=int,
                            default=int(getattr(settings, 'CRAWL_WORKERS', 4)))
        parser.add_argument('--no-images', action='store_true')
        parser.add_argument('--plan', action='store_true',
                            help='show the derived specs and stop')

    def handle(self, *args, **options):
        global VARNA
        import importlib
        VARNA = importlib.import_module('market.management.commands.crawl_live')

        probes = SiteProbe.latest()
        queryset = Agency.objects.exclude(website='').filter(crawl_opt_out=False)
        if options['agencies']:
            queryset = queryset.filter(slug__in=set(options['agencies']))

        # Agencies with a hand-written source in market/sources.py are crawled
        # by crawl_live, which knows their private APIs and city filters. A
        # derived spec would be a worse version of the same thing.
        from market import sources
        handwritten = set(sources.SOURCES)

        plan = []
        for agency in queryset.order_by('slug'):
            if agency.slug in handwritten and not options['agencies']:
                continue
            probe = probes.get(agency.slug)
            if not probe or not probe.listing_pattern:
                continue
            plan.append((agency, self._spec(agency, probe)))

        if not plan:
            self.stdout.write(self.style.WARNING(
                'No agency has a verified listing pattern. Run probe_agencies first.'))
            return

        if options['plan']:
            for agency, spec in plan:
                self.stdout.write(f'  {agency.slug:28} {spec["include"][0]:26} '
                                  f'{spec["catalog"][0][:52]}')
            self.stdout.write(f'\n{len(plan)} agencies ready to crawl')
            return

        self.run = CrawlRun.objects.create(kind='sites', run_date=dt.date.today(),
                                           status='running')
        self.trace = settings.RUNS_DIR / f'auto-{dt.date.today():%Y-%m-%d}-{self.run.pk}.jsonl'
        self.trace.parent.mkdir(parents=True, exist_ok=True)
        self.options = options
        started = time.monotonic()
        self.stdout.write(f'Auto crawl #{self.run.pk} · {len(plan)} agencies · Varna only\n')

        with ThreadPoolExecutor(max_workers=options['workers']) as pool:
            results = list(pool.map(lambda p: self._safe(*p), plan))
        self._finish(results, started)

    # ------------------------------------------------------------ spec ----

    @staticmethod
    def _spec(agency, probe):
        """A crawler spec from what the probe actually saw.

        `/property/*` becomes: listings match `/property/<something>`, and the
        catalogue is most likely `/property/`. Both are checked against live
        responses before anything is stored.
        """
        shape = probe.listing_pattern.rstrip('/*').rstrip('/')
        base = f'{urlsplit(probe.final_url or agency.website).scheme}://' \
               f'{urlsplit(probe.final_url or agency.website).netloc}'
        candidates = [urljoin(base, shape + '/')]
        for extra in (probe.catalogue_patterns or []):
            candidates.append(urljoin(base, extra.rstrip('*').rstrip('/') + '/'))
        candidates.append(probe.final_url or agency.website)
        # Language duplicates are dropped -- one flat under /bg/, /en/ and /ru/
        # is the duplication this product exists to remove -- but never the
        # prefix the listing shape itself sits under, which would drop every
        # listing on sites whose canonical path is /en/.
        drops = [f'{shape}/page/']
        for lang in ('/en/', '/ru/', '/de/'):
            if not shape.startswith(lang.rstrip('/')):
                drops.append(lang)
        return {
            'catalog': candidates,
            # A slug must follow the prefix: the bare index page is in the
            # catalogue too and is not a listing.
            'include': [f're:{re.escape(shape)}/[^/]+'],
            'drop': drops,
        }

    # ------------------------------------------------------------- crawl ----

    def _safe(self, agency, spec):
        """One agency failing is a bad recipe, not a reason to lose the crawl."""
        try:
            return self._one(agency, spec)
        except Exception as exc:                                    # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'  {agency.slug:28} crashed: {type(exc).__name__}: {exc}'))
            return {'agency': agency.slug, 'seen': 0, 'varna': 0, 'new': 0,
                    'changed': 0, 'same': 0, 'sold': 0, 'retired': 0,
                    'failed': 1, 'images': 0, 'seconds': 0.0, 'catalog': '',
                    'error': f'{type(exc).__name__}: {exc}'[:200]}

    def _one(self, agency, spec):
        # store.store() returns new / changed / same / sold / retired. Counting
        # only the first three crashed the whole run on the first sold listing
        # it met, and took fourteen agencies down with it.
        r = {'agency': agency.slug, 'seen': 0, 'varna': 0, 'new': 0, 'changed': 0,
             'same': 0, 'sold': 0, 'retired': 0, 'failed': 0, 'images': 0,
             'seconds': 0.0, 'catalog': ''}
        t0 = time.monotonic()
        today = dt.date.today()

        found = {}
        for entry in spec['catalog']:
            trial = dict(spec, catalog=[entry])
            try:
                found = catalog.discover(agency.slug, trial)
            except Exception:                                       # noqa: BLE001
                found = {}
            if len(found) >= 5:
                r['catalog'] = entry
                break
        if not found:
            r['seconds'] = round(time.monotonic() - t0, 1)
            self._say(agency, r, 'no catalogue found')
            return r

        r['seen'] = len(found)
        todo = list(found)[:self.options['limit']] if self.options['limit'] else list(found)
        for url in todo:
            self._fetch(agency, spec, url, today, r)

        r['seconds'] = round(time.monotonic() - t0, 1)
        self._say(agency, r)
        return r

    def _fetch(self, agency, spec, url, today, r):
        res = fetch.get(url)
        if res['status'] != 200 or not res['body']:
            r['failed'] += 1
            return
        try:
            record = extract.extract(res['body'], url, spec)
        except Exception:                                           # noqa: BLE001
            r['failed'] += 1
            return
        if record is None:
            r['failed'] += 1
            return

        haystack = ' '.join(str(record.get(f) or '') for f in
                            ('location', 'title', 'description')) + ' ' + url
        if not VARNA.is_varna(haystack):
            return
        r['varna'] += 1

        line = prices.price_line(record.get('price_raw', ''))
        if line:
            value = prices.value_of(line)
            if value and (not record.get('price_eur') or value < record['price_eur']):
                record['price_eur'] = value
        record['price_eur'], per_m2 = prices.normalise(
            record.get('price_eur'), record.get('area_m2'), record.get('price_raw', ''))
        if per_m2:
            record['price_per_m2'] = per_m2

        path = fetch.save_snapshot(self.run.pk, agency.slug, url, res['body'])
        evidence = {'fetched_at': timezone.now().isoformat(), 'method': 'curl',
                    'http_status': res['status'], 'snapshot_path': path,
                    'quoted_price_text': record.get('price_raw', ''),
                    'run': self.run.pk, 'crawler': 'crawl_auto'}
        with transaction.atomic():
            outcome = store.store(agency, record, evidence, today)
        r[outcome] = r.get(outcome, 0) + 1
        with open(self.trace, 'a', encoding='utf-8') as handle:
            handle.write(json.dumps({'agency': agency.slug, 'url': url,
                                     'outcome': outcome, 'run': self.run.pk},
                                    ensure_ascii=False) + '\n')

        if not self.options['no_images']:
            offer = Offer.objects.filter(agency=agency,
                                         fingerprint=store.fingerprint(url)).first()
            if offer and not offer.images.exists():
                found_img, _why = images.fetch_main(res['body'], url, agency.slug)
                if found_img:
                    _o, created = OfferImage.objects.get_or_create(
                        offer=offer, sha256=found_img['sha256'],
                        defaults={'local_path': found_img['local_path'],
                                  'source_url': found_img['source_url'][:900],
                                  'position': 0})
                    r['images'] += created

    def _say(self, agency, r, note=''):
        style = self.style.SUCCESS if r['varna'] else self.style.WARNING
        self.stdout.write(style(
            f'  {agency.slug:28} seen={r["seen"]:5} varna={r["varna"]:5} '
            f'new={r["new"]:5} same={r["same"]:4} failed={r["failed"]:4} '
            f'img={r["images"]:5} {r["seconds"]:6.0f}s {note}'))

    def _finish(self, results, started):
        tot = {k: sum(x.get(k, 0) for x in results)
               for k in ('seen', 'varna', 'new', 'changed', 'same', 'failed', 'images')}
        self.run.status = CrawlRun.OK
        self.run.finished_at = timezone.now()
        self.run.offers_total = tot['varna']
        self.run.offers_new = tot['new']
        self.run.log = json.dumps(results, ensure_ascii=False, indent=1)
        self.run.save()
        self.stdout.write('\n' + '-' * 78)
        self.stdout.write(self.style.SUCCESS(
            f'{tot["seen"]:,} discovered · {tot["varna"]:,} in Varna · {tot["new"]:,} new · '
            f'{tot["same"]:,} unchanged · {tot["failed"]:,} failed · {tot["images"]:,} images '
            f'· {(time.monotonic() - started) / 60:.1f} min'))
