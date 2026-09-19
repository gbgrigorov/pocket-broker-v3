# -*- coding: utf-8 -*-
"""Crawl the LIVE catalogues. No sitemaps.

Sitemaps were tried first and abandoned on evidence: titan-properties publishes
6 707 of them against 85 live Varna properties, and the first 136 entries of
home2u's sitemap in order were all dead. See market/sources.py.

Three source kinds, cheapest first:
  json  one request returns every record -- titan-properties
  wp    WordPress REST, paginated and orderable by date
  html  the agency's own catalogue, walked with its own pagination

Only Varna is kept. The city filter is applied at the source where the source
supports it, and on the extracted location where it does not.
"""
import datetime as dt
import json as jsonlib
import re
import time
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from market import images, prices, recon, sources
from sourcing.models import Agency, CrawlRun, Offer, OfferImage
from sourcing.web import extract, fetch, sites, store

# Varna and the settlements a Varna buyer actually searches. Matched against
# the location text an agency publishes, which is free-form.
VARNA = re.compile(
    r'(варна|varna|злат\w* пяс|golden sands|св\.?\s*св\.?\s*константин|'
    r'виница|vinitsa|галата|galata|аспарухово|asparuhovo|'
    r'чайка|chayka|бриз|briz|владислав варненчик|vladislav|'
    r'трошево|troshevo|аксаково|aksakovo|кабакум|kabakum|'
    r'виница|бяла|обзор|камчия|kamchia)', re.I)

# Neighbourhood names that exist in several Bulgarian cities. "Левски" and
# "Младост" are Varna quarters and also Sofia ones, so they are only evidence
# when the text does not name a different city outright.
ELSEWHERE = re.compile(
    r'(софия|sofia|пловдив|plovdiv|бургас|burgas|русе|ruse|стара загора|'
    r'велико търново|благоевград|несебър|nesebar|слънчев бряг|sunny beach|'
    r'свети влас|sveti vlas|созопол|sozopol|поморие|pomorie|банско|bansko)',
    re.I)


def is_varna(text):
    """Varna named, and no other city named. Order matters: a listing whose
    location reads "София, кв. Младост" matched the old pattern on Младост and
    put 200 Sofia flats into a Varna database."""
    if not text:
        return False
    if ELSEWHERE.search(text):
        return False
    return bool(VARNA.search(text))


class Command(BaseCommand):
    help = 'Crawl live agency catalogues (no sitemaps). Varna only.'

    def add_arguments(self, parser):
        parser.add_argument('--agency', action='append', dest='agencies')
        parser.add_argument('--limit', type=int)
        parser.add_argument('--workers', type=int,
                            default=int(getattr(settings, 'CRAWL_WORKERS', 4)))
        parser.add_argument('--no-images', action='store_true')
        parser.add_argument('--newest-only', action='store_true',
                            help='only sources that can be asked for newest first')

    def handle(self, *args, **options):
        wanted = options['agencies'] or list(sources.SOURCES)
        if options['newest_only']:
            wanted = [s for s in wanted if sources.SOURCES.get(s, {}).get('newest_first')]
        plan = [(s, sources.SOURCES[s]) for s in wanted if s in sources.SOURCES]
        if not plan:
            self.stdout.write(self.style.WARNING('No live sources selected.'))
            return

        self.run = CrawlRun.objects.create(kind='sites', run_date=dt.date.today(),
                                           status='running')
        self.trace = settings.RUNS_DIR / f'live-{dt.date.today():%Y-%m-%d}-{self.run.pk}.jsonl'
        self.trace.parent.mkdir(parents=True, exist_ok=True)
        self.options = options
        started = time.monotonic()

        self.stdout.write(f'Live crawl #{self.run.pk} · {len(plan)} sources · Varna only\n')
        with ThreadPoolExecutor(max_workers=options['workers']) as pool:
            results = list(pool.map(lambda p: self._source(*p), plan))
        self._finish(results, started)

    # ----------------------------------------------------------- dispatch --

    def _source(self, slug, cfg):
        agency = Agency.objects.filter(slug=slug).first()
        r = {'agency': slug, 'kind': cfg['kind'], 'seen': 0, 'varna': 0,
             'new': 0, 'changed': 0, 'same': 0, 'failed': 0, 'images': 0,
             'seconds': 0.0, 'newest_first': bool(cfg.get('newest_first'))}
        if agency is None:
            r['failed'] = 1
            return r
        t0 = time.monotonic()
        try:
            handler = getattr(self, f'_kind_{cfg["kind"]}')
            handler(agency, cfg, r)
        except Exception as exc:                                    # noqa: BLE001
            r['error'] = str(exc)[:200]
        r['seconds'] = round(time.monotonic() - t0, 1)
        self._say(r)
        return r

    # --------------------------------------------------------------- json --

    def _kind_json(self, agency, cfg, r):
        """titan-properties: one request per deal type, everything structured."""
        today = dt.date.today()
        for deal_id, deal in cfg['deals'].items():
            res = recon.get(cfg['url'].format(deal=deal_id))
            if not res['ok']:
                r['failed'] += 1
                continue
            try:
                records = jsonlib.loads(res['body'])
            except ValueError:
                r['failed'] += 1
                continue
            r['seen'] += len(records)
            for item in records:
                if item.get(cfg['city_field']) != cfg['city_value']:
                    continue
                r['varna'] += 1
                self._store_json(agency, cfg, item, deal, today, r)
                if self.options['limit'] and r['varna'] >= self.options['limit']:
                    return

    def _store_json(self, agency, cfg, item, deal, today, r):
        url = cfg['detail_url'].format(slug=item.get('slug') or '', id=item.get('id'))
        price = _num(item.get('prise'))
        area = _num(item.get('kvadraturarzp'))
        record = {
            'listing_url': url,
            'title': (item.get('name') or '')[:400],
            'price_eur': price,
            'price_raw': str(item.get('prise') or ''),
            'area_m2': area,
            'floor': _num(item.get('floor')),
            'location': ' '.join(filter(None, [item.get('city_name'),
                                               item.get('district_name')]))[:200],
            'property_kind': item.get('property_kind_name') or '',
            'deal_type': deal,
            'ref': str(item.get('id') or ''),
            'status': 'active',
        }
        evidence = {'fetched_at': timezone.now().isoformat(), 'method': 'json-api',
                    'source_url': cfg['url'].split('?')[0], 'run': self.run.pk,
                    'quoted_price_text': record['price_raw'],
                    'api_date': str(item.get(cfg.get('date_field')) or ''),
                    'crawler': 'crawl_live'}
        with transaction.atomic():
            outcome = store.store(agency, record, evidence, today)
        r[outcome] += 1
        self._trace({'agency': agency.slug, 'url': url, 'outcome': outcome,
                     'kind': 'json', 'price': price, 'area': area})

        pic = item.get(cfg.get('image_field')) or item.get('pic')
        if pic and not self.options['no_images']:
            self._image_from_url(agency, url, str(pic), r, cfg.get('image_base', ''))

    def _image_from_url(self, agency, listing_url, pic, r, base=''):
        if not pic.startswith('http'):
            if not base:
                return
            pic = base.rstrip('/') + '/' + pic.lstrip('/')
        offer = Offer.objects.filter(agency=agency,
                                     fingerprint=store.fingerprint(listing_url)).first()
        if offer is None or offer.images.exists():
            return
        blob = images.fetch_bytes(pic)
        if not blob or len(blob) < images.MIN_BYTES or not images.looks_like_image(blob):
            return
        import hashlib
        digest = hashlib.sha256(blob).hexdigest()
        folder = images.store_dir(agency.slug)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{digest[:24]}{images.extension_for(blob, pic)}'
        if not path.exists():
            path.write_bytes(blob)
        _obj, created = OfferImage.objects.get_or_create(
            offer=offer, sha256=digest,
            defaults={'local_path': str(path.relative_to(settings.DATA_DIR)),
                      'source_url': pic[:900], 'position': 0})
        r['images'] += created

    # ----------------------------------------------------------------- wp --

    def _kind_wp(self, agency, cfg, r):
        """WordPress REST, newest first, paginated by X-WP-TotalPages."""
        today = dt.date.today()
        page, pages = 1, 1
        while page <= pages:
            url = (f'{cfg["base"]}/wp-json/wp/v2/{cfg["rest_base"]}'
                   f'?per_page=100&page={page}&orderby=date&order=desc')
            res = recon.get(url)
            if not res['ok']:
                r['failed'] += 1
                break
            pages = int(res['headers'].get('x-wp-totalpages') or 1)
            try:
                items = jsonlib.loads(res['body'])
            except ValueError:
                r['failed'] += 1
                break
            if not isinstance(items, list) or not items:
                break
            r['seen'] += len(items)
            for item in items:
                link = item.get('link') or ''
                # The item's own words only -- a dump of the whole record
                # includes the site's city menu, which matches everything.
                own = ' '.join(str(item.get(f, '') or '')[:400] for f in
                               ('link', 'slug')) + ' ' + \
                      str((item.get('title') or {}).get('rendered', ''))
                if ELSEWHERE.search(own):
                    continue
                self._fetch_detail(agency, link, today, r, city_check=True)
                if self.options['limit'] and r['varna'] >= self.options['limit']:
                    return
            page += 1

    # --------------------------------------------------------------- html --

    def _kind_html(self, agency, cfg, r):
        """Walk the agency's own catalogue with its own pagination."""
        today = dt.date.today()
        # Some agencies split one city across several catalogues -- Bulgarian
        # Properties has a Varna one and a Varna-city one, with different depths.
        catalogs = [cfg['catalog']] + list(cfg.get('extra_catalogs') or [])
        pattern = re.compile(cfg['include_re']) if cfg.get('include_re') else None
        seen = set()

        for base in catalogs:
            barren = 0
            for n in range(1, cfg['max_page'] + 1):
                page_url = base + cfg['page_param'].format(n=n) if n > 1 else base
                res = recon.get(page_url)
                if not res['ok']:
                    break
                found = recon.links_on(res['body'], res['final_url'] or page_url)
                links = {l for l in found
                         if (pattern.search(l) if pattern else cfg['include'] in l)
                         and not re.search(r'/page/\d|[?&]p=\d', l)}
                fresh = links - seen
                if not fresh:
                    barren += 1
                    if barren >= 2:
                        break
                    continue
                barren = 0
                seen |= fresh
                r['seen'] += len(fresh)
                for link in sorted(fresh):
                    self._fetch_detail(agency, link, today, r, city_check=True)
                    if self.options['limit'] and r['varna'] >= self.options['limit']:
                        return

    # ------------------------------------------------------------- shared --

    def _fetch_detail(self, agency, url, today, r, city_check=False):
        if not url:
            return
        res = fetch.get(url)
        if res['status'] != 200 or not res['body']:
            r['failed'] += 1
            return
        spec = sites.recipe(agency.slug) or {}
        try:
            record = extract.extract(res['body'], url, spec)
        except Exception:                                           # noqa: BLE001
            r['failed'] += 1
            return
        if record is None:
            r['failed'] += 1
            return
        haystack = ' '.join(str(record.get(f) or '')
                            for f in ('location', 'title', 'description'))
        if city_check and not is_varna(haystack + ' ' + url):
            self._trace({'agency': agency.slug, 'url': url, 'outcome': 'not_varna'})
            return
        r['varna'] += 1
        path = fetch.save_snapshot(self.run.pk, agency.slug, url, res['body'])
        evidence = {'fetched_at': timezone.now().isoformat(), 'method': 'curl',
                    'http_status': res['status'], 'snapshot_path': path,
                    'quoted_price_text': record.get('price_raw', ''),
                    'run': self.run.pk, 'crawler': 'crawl_live'}
        # Two price defects, both only visible in price_raw.
        # 1. A price split across lines: the complex name above the figure was
        #    read as its leading digits ("Възраждане 4" -> 4 185 000 €).
        line = prices.price_line(record.get('price_raw', ''))
        if line:
            value = prices.value_of(line)
            if value and (not record.get('price_eur') or value < record['price_eur']):
                record['price_eur'] = value
        # 2. New-build agencies quote €/m²; stored raw that reads as a €1 019 house.
        record['price_eur'], per_m2 = prices.normalise(
            record.get('price_eur'), record.get('area_m2'), record.get('price_raw', ''))
        if per_m2:
            record['price_per_m2'] = per_m2

        with transaction.atomic():
            outcome = store.store(agency, record, evidence, today)
        r[outcome] += 1
        self._trace({'agency': agency.slug, 'url': url, 'outcome': outcome,
                     'price': record.get('price_eur'), 'area': record.get('area_m2'),
                     'per_m2_quote': bool(per_m2 and prices.is_per_m2(record.get('price_raw','')))})
        if not self.options['no_images']:
            offer = Offer.objects.filter(agency=agency,
                                         fingerprint=store.fingerprint(url)).first()
            if offer and not offer.images.exists():
                found, _why = images.fetch_main(res['body'], url, agency.slug)
                if found:
                    _o, created = OfferImage.objects.get_or_create(
                        offer=offer, sha256=found['sha256'],
                        defaults={'local_path': found['local_path'],
                                  'source_url': found['source_url'][:900], 'position': 0})
                    r['images'] += created

    def _trace(self, row):
        row['run'] = self.run.pk
        with open(self.trace, 'a', encoding='utf-8') as handle:
            handle.write(jsonlib.dumps(row, ensure_ascii=False) + '\n')

    def _say(self, r):
        style = self.style.SUCCESS if r['varna'] else self.style.WARNING
        self.stdout.write(style(
            f'  {r["agency"]:20} {r["kind"]:5} seen={r["seen"]:6} varna={r["varna"]:5} '
            f'new={r["new"]:5} same={r["same"]:4} failed={r["failed"]:4} '
            f'img={r["images"]:5} {r["seconds"]:6.0f}s'
            + ('  ↻newest-first' if r['newest_first'] else '')))

    def _finish(self, results, started):
        tot = {k: sum(x.get(k, 0) for x in results)
               for k in ('seen', 'varna', 'new', 'changed', 'same', 'failed', 'images')}
        self.run.status = CrawlRun.OK if not tot['failed'] else CrawlRun.PARTIAL
        self.run.finished_at = timezone.now()
        self.run.offers_total = tot['varna']
        self.run.offers_new = tot['new']
        self.run.offers_changed = tot['changed']
        self.run.log = jsonlib.dumps(results, ensure_ascii=False, indent=1)
        self.run.save()
        self.stdout.write('\n' + '-' * 76)
        self.stdout.write(self.style.SUCCESS(
            f'{tot["seen"]:,} records seen · {tot["varna"]:,} in Varna · '
            f'{tot["new"]:,} new · {tot["same"]:,} unchanged · {tot["failed"]:,} failed · '
            f'{tot["images"]:,} images · {(time.monotonic() - started) / 60:.1f} min'))


def _num(value):
    try:
        out = float(str(value).replace(' ', '').replace(',', '.'))
        return out or None
    except (TypeError, ValueError):
        return None
