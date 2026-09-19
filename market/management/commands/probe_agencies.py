# -*- coding: utf-8 -*-
"""Reconnaissance over the admitted agencies. Writes SiteProbe rows.

Reads nothing but live responses. Every recipe written in phase 3 is written
from this output, never from an assumption about how a site is laid out.

    python manage.py probe_agencies                 # all with a known website
    python manage.py probe_agencies --agency matex  # one
    python manage.py probe_agencies --deep          # also count WP listing types
"""
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand

from market import agencies_varna, recon
from market.models import SiteProbe

# Path fragments that mean "this is one property", across the platforms
# Bulgarian agencies actually use. Matched against real sitemap URLs, and only
# used to rank shapes that are already present -- never to invent a URL.
LISTING_HINTS = (
    'property', 'properties', 'estate', 'imot', 'imoti', 'nedvizhim',
    'listing', 'obekt', 'obiava', 'ad', 'apartament', 'offer', 'oferta',
)
PROJECT_HINTS = ('complex', 'kompleks', 'project', 'proekt', 'development',
                 'novo-stroitelstvo', 'sgrada', 'building')


class Command(BaseCommand):
    help = 'Probe admitted agency websites and record what is really there.'

    def add_arguments(self, parser):
        parser.add_argument('--agency', action='append', dest='agencies')
        parser.add_argument('--only-new', action='store_true',
                            help='skip agencies that already have a probe')
        parser.add_argument('--deep', action='store_true',
                            help='also query WordPress REST for listing counts')
        parser.add_argument('--workers', type=int,
                            default=int(getattr(settings, 'CRAWL_WORKERS', 4)))

    def handle(self, *args, **options):
        # The Agency table is the registry now. It started as the hand-written
        # trust list in market/agencies_varna.py and was widened by
        # `harvest_agencies` once the admission rule changed from "vetted only"
        # to "admit broadly, rank by trust" -- the hand-written list was
        # holding 6% of the market.
        from sourcing.models import Agency
        queryset = Agency.objects.exclude(website='').filter(crawl_opt_out=False)
        if options['agencies']:
            queryset = queryset.filter(slug__in=set(options['agencies']))
        rows = [{'slug': a.slug, 'name': a.name, 'website': a.website}
                for a in queryset.order_by('slug')]
        if options['only_new']:
            done = set(SiteProbe.objects.values_list('agency_slug', flat=True))
            rows = [r for r in rows if r['slug'] not in done]
        if not rows:
            self.stdout.write(self.style.WARNING('Nothing to probe.'))
            return

        from django.utils import timezone
        self.run_id = uuid.uuid4().hex[:12]
        self.run_started = timezone.now()

        self.stdout.write(f'Run {self.run_id} — probing {len(rows)} agencies '
                          f'({options["workers"]} workers, one per host, '
                          f'{getattr(settings, "CRAWL_HOST_DELAY", 2.0)}s apart)\n')

        # Saved one at a time, as each finishes. An earlier version collected
        # every probe and bulk_created at the end, so a run killed at minute
        # nine wrote nothing at all -- which is exactly what happened, and cost
        # a full sweep of politely rate-limited crawling.
        with ThreadPoolExecutor(max_workers=options['workers']) as pool:
            probes = list(pool.map(
                lambda r: self._probe_and_save(r, options['deep']), rows))

        self._report(probes)

    def _probe_and_save(self, row, deep):
        probe = self._probe(row, deep)
        probe.save()
        return probe

    # ------------------------------------------------------------------ one --

    def _probe(self, row, deep):
        probe = SiteProbe(agency_slug=row['slug'], agency_name=row['name'],
                          website=row['website'],
                          run_id=self.run_id, run_started=self.run_started)
        home = recon.get(row['website'])
        probe.http_status = home['status'] or None
        probe.final_url = (home.get('final_url') or '')[:400]
        probe.server = home.get('headers', {}).get('server', '')[:120]

        if not home['ok']:
            probe.status = self._classify_failure(home)
            probe.note = (home.get('error') or f'HTTP {home["status"]}')[:500]
            self.stdout.write(self.style.ERROR(
                f'  {probe.status:12} {row["slug"]:22} {probe.note[:60]}'))
            return probe

        body = home['body']
        if self._looks_like_challenge(body):
            probe.status = 'captcha'
            probe.note = 'Challenge/CAPTCHA page returned. Recorded, not bypassed.'
            self.stdout.write(self.style.WARNING(f'  captcha      {row["slug"]}'))
            return probe

        probe.platform = ', '.join(recon.detect_platform(body))[:120]
        enc = recon.detect_encoding(body, home['headers'])
        probe.meta_charset = (enc['meta_charset'] or '')[:32]
        probe.header_charset = (enc['header_charset'] or '')[:32]

        base = home['final_url'] or row['website']
        self._robots(probe, base)
        self._sitemaps(probe, base)
        if deep and 'WordPress' in probe.platform or (deep and 'Houzez' in probe.platform):
            self._wordpress(probe, base)

        # Many BG agency sites publish no sitemap at all. That is not a reason
        # to drop an agency -- walk a bounded number of its own pages instead.
        if not probe.listing_pattern:
            self._harvest(probe, base)

        if probe.status == 'ok' and not probe.listing_pattern:
            probe.status = 'no_listings'

        style = self.style.SUCCESS if probe.crawlable else self.style.WARNING
        self.stdout.write(style(
            f'  {probe.status:12} {row["slug"]:22} '
            f'{probe.platform or "custom":14} '
            f'{(probe.listing_pattern or "-"):26} '
            f'{probe.listing_count if probe.listing_count is not None else "?":>7} urls'))
        return probe

    # ------------------------------------------------------------- helpers --

    @staticmethod
    def _looks_like_challenge(body):
        markers = ('cf-browser-verification', 'cf_chl_', 'Just a moment...',
                   'g-recaptcha', 'hcaptcha', 'Checking your browser')
        head = body[:20000]
        return any(m.lower() in head.lower() for m in markers)

    @staticmethod
    def _classify_failure(res):
        if res['status'] in (401, 403, 429, 503):
            return 'blocked'
        if res['status'] == 0:
            return 'unreachable'
        return 'http_error'

    def _robots(self, probe, base):
        res = recon.get(urljoin(base, '/robots.txt'))
        if not res['ok'] or 'html' in res.get('content_type', ''):
            return
        probe.robots_found = True
        disallow, sitemaps = recon.parse_robots(res['body'])
        probe.robots_disallow = disallow[:60]
        probe.sitemaps = sitemaps[:20]
        probe.robots_blocks_listings = any(
            any(h in rule.lower() for h in LISTING_HINTS) for rule in disallow)

    def _sitemaps(self, probe, base):
        candidates = list(probe.sitemaps) or [urljoin(base, p) for p in recon.SITEMAP_GUESSES]
        seen, urls, used = set(), [], []

        queue = [c for c in candidates if c]
        while queue and len(urls) < 60000:
            sm = queue.pop(0)
            if sm in seen:
                continue
            seen.add(sm)
            res = recon.get(sm)
            if not res['ok'] or '<' not in res['body']:
                continue
            used.append(sm)
            locs = recon.sitemap_urls(res['body'])
            if recon.is_index(res['body']):
                # Walk child sitemaps, preferring the ones that name listings.
                children = sorted(locs, key=lambda u: 0 if any(
                    h in u.lower() for h in LISTING_HINTS) else 1)
                queue.extend(children[:12])
            else:
                urls.extend(locs)
            if len(used) > 14:
                break

        probe.sitemaps = used[:20]
        probe.sitemap_url_count = len(urls) or None
        if not urls:
            return

        shapes = recon.url_shapes(urls)
        probe.url_shapes = [{'shape': sh, 'count': n, 'samples': ex}
                            for sh, n, ex in shapes]
        self._pick_pattern(probe, shapes)
        probe.has_project_pages = any(
            any(h in sh.lower() for h in PROJECT_HINTS) for sh, _n, _e in shapes)

    def _harvest(self, probe, base):
        """Fallback discovery: crawl a couple of dozen pages and shape the links."""
        urls, fetched = recon.harvest(base, LISTING_HINTS)
        if not urls:
            return
        shapes = recon.url_shapes(urls, limit=16)
        probe.url_shapes = [{'shape': sh, 'count': n, 'samples': ex}
                            for sh, n, ex in shapes]
        self._pick_pattern(probe, shapes, floor=True, pages=fetched)
        if probe.has_project_pages is None:
            probe.has_project_pages = any(
                any(h in sh.lower() for h in PROJECT_HINTS) for sh, _n, _e in shapes)

    def _pick_pattern(self, probe, shapes, floor=False, pages=0):
        """Choose a listing pattern -- and prove it before accepting it.

        The shape with the most URLs and a listing-ish name is only a
        hypothesis. A previous scraper in this family was built on
        /realestates/newdev, which 404s, and another parsed a news feed. So a
        candidate is accepted only after a real page behind it comes back
        looking like a property: priced AND measured, without news markers.
        """
        candidates = [(sh, n, ex) for sh, n, ex in shapes
                      if any(h in sh.lower() for h in LISTING_HINTS) and ex]
        # Search forms, news feeds and account pages name themselves. Drop them
        # before spending a request on them.
        candidates = [c for c in candidates
                      if not any(bad in c[0].lower() for bad in
                                 ('search', 'news', 'blog', 'article', 'novini',
                                  'statii', 'login', 'register', 'compare',
                                  'dobavi', 'add', 'valuation', 'ocenka'))]
        candidates.sort(key=lambda c: (-c[1], c[0]))

        for shape, count, samples in candidates[:5]:
            kinds = []
            # Every sample gets a vote. An earlier version stopped at the first
            # non-detail sample, so one unlucky URL -- a sold-out page, a
            # redirect to an index -- disqualified a shape that was right, and
            # roneva's 779 listings came and went between runs depending on
            # which page the harvest happened to reach first.
            for sample in sorted(samples)[:3]:
                res = recon.get(sample)
                if not res['ok'] or 'html' not in res.get('content_type', ''):
                    kinds.append(('unreachable', sample, f'HTTP {res["status"]}'))
                    continue
                kind, why = recon.page_kind(res['body'], shape=shape,
                                            base=res['final_url'] or sample)
                kinds.append((kind, sample, why))
                if kind == 'detail':
                    break

            verdict = next((k for k in kinds if k[0] == 'detail'), None)
            if verdict:
                probe.listing_pattern = shape
                probe.listing_count = count
                suffix = f' (link harvest, {pages} pages; count is a floor)' if floor else ''
                probe.note = (probe.note + f' verified detail page {verdict[1]} '
                              f'-- {verdict[2]}.' + suffix).strip()[:2000]
                return
            if any(k[0] == 'catalogue' for k in kinds):
                if shape not in (probe.catalogue_patterns or []):
                    probe.catalogue_patterns = (probe.catalogue_patterns or []) + [shape]
            probe.note = (probe.note + f' {shape}: '
                          + ', '.join(f'{k}' for k, _u, _w in kinds) + '.').strip()[:2000]

        if candidates and not probe.listing_pattern:
            probe.status = 'no_listings'

    def _wordpress(self, probe, base):
        types = recon.wp_types(base)
        if not types:
            return
        probe.wp_types = types
        best = None
        for slug, rest_base in types.items():
            if not any(h in slug.lower() for h in LISTING_HINTS):
                continue
            total = recon.wp_count(base, rest_base)
            if total and (best is None or total > best[1]):
                best = (rest_base, total)
        if best and (probe.listing_count or 0) < best[1]:
            probe.listing_count = best[1]
            probe.note = (probe.note + f' wp rest type: {best[0]} ({best[1]})').strip()

    # -------------------------------------------------------------- report --

    def _report(self, probes):
        by_status = {}
        for p in probes:
            by_status.setdefault(p.status, []).append(p)
        self.stdout.write('\n' + '-' * 72)
        for status in ('ok', 'no_listings', 'blocked', 'captcha', 'http_error', 'unreachable'):
            group = by_status.get(status, [])
            if group:
                self.stdout.write(f'{status:14} {len(group):3}  '
                                  + ', '.join(p.agency_slug for p in group))
        crawlable = [p for p in probes if p.crawlable]
        stock = sum(p.listing_count or 0 for p in crawlable)
        self.stdout.write(
            f'\ncrawlable: {len(crawlable)}/{len(probes)} agencies, '
            f'~{stock:,} listing URLs discovered')
