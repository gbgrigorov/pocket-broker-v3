# -*- coding: utf-8 -*-
"""Sweep every crawlable agency website and store what it advertises.

The first run reads everything. Every run after it reads one sitemap per site
and then only the pages it has never seen -- the listing URL in the database is
what makes that possible.

    manage.py crawl_sites                    # new listings only
    manage.py crawl_sites --refresh          # re-read stored listings too
    manage.py crawl_sites --agency leo-castle --limit 20
"""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from sourcing.models import Agency, CrawlRun, Offer, OfferHistory, OfferSource
from sourcing.web import catalog, extract, fetch, sites, store


class Command(BaseCommand):
    help = 'Обхожда каталозите на агенциите и записва това, което предлагат днес.'

    def add_arguments(self, parser):
        parser.add_argument('--agency', action='append', dest='agencies',
                            help='Само тази агенция (slug). Може да се повтаря.')
        parser.add_argument('--limit', type=int,
                            help='Най-много N нови обяви на агенция.')
        parser.add_argument('--refresh', action='store_true',
                            help='Чете наново и вече записаните обяви.')
        parser.add_argument('--discover-only', action='store_true',
                            help='Само преброява обявите, без да ги тегли.')
        parser.add_argument('--workers', type=int, default=5,
                            help='Колко сайта едновременно (по един заявка/сек на сайт).')
        parser.add_argument('--reextract', action='store_true',
                            help='Разчита наново запазените страници, без нито една заявка.')
        parser.add_argument('--verify', action='store_true',
                            help='Проверява дали записаните обяви още стоят на сайта.')

    def handle(self, *args, **options):
        today = dt.date.today()
        if options['reextract']:
            return self._reextract(options)
        if options['verify']:
            return self._verify(options)

        queryset = Agency.objects.filter(duplicate_of__isnull=True, crawl_opt_out=False)
        if options['agencies']:
            queryset = queryset.filter(slug__in=options['agencies'])

        plan = [(a, sites.recipe(a.slug)) for a in queryset.order_by('slug')]
        crawlable = [(a, spec) for a, spec in plan if spec]
        notes = {**sites.BLOCKED, **sites.NO_INDEX}
        blocked = [(a, notes[a.slug]) for a, spec in plan
                   if not spec and a.slug in notes]

        if not crawlable:
            self.stdout.write(self.style.WARNING('Няма агенции с описан сайт.'))
            return

        run = CrawlRun.objects.create(run_date=today, kind=CrawlRun.SITES,
                                      status=CrawlRun.RUNNING)
        self.stdout.write(f'Обхождане на сайтове {today} · {len(crawlable)} агенции '
                          f'· обхождане №{run.pk}')

        lines, totals = [], {'new': 0, 'changed': 0, 'same': 0, 'skipped': 0,
                             'failed': 0, 'found': 0, 'sold': 0, 'retired': 0}
        ok = dead = 0

        with ThreadPoolExecutor(max_workers=max(1, options['workers'])) as pool:
            futures = {pool.submit(self._one, agency, spec, run, today, options): agency
                       for agency, spec in crawlable}
            for future in as_completed(futures):
                agency = futures[future]
                try:
                    result = future.result()
                except Exception as exc:                      # noqa: BLE001
                    dead += 1
                    lines.append(f'  ✗  {agency.slug}: {exc}')
                    self.stdout.write(self.style.ERROR(f'  ✗  {agency.slug}: {exc}'))
                    continue
                ok += 1
                for key in totals:
                    totals[key] += result.get(key, 0)
                line = (f'  ✓  {agency.slug}: {result["found"]} обяви в sitemap · '
                        f'{result["new"]} нови · {result["changed"]} променени · '
                        f'{result["same"]} без промяна · {result["skipped"]} пропуснати'
                        + (f' · {result["sold"]} продадени' if result['sold'] else '')
                        + (f' · {result["retired"]} свалени' if result.get('retired') else '')
                        + (f' · {result["failed"]} неуспешни' if result['failed'] else ''))
                if result.get('warning'):
                    lines.append(f'  !  {agency.slug}: {result["warning"]}')
                    self.stdout.write(self.style.WARNING(f'  !  {agency.slug}: {result["warning"]}'))
                lines.append(line)
                self.stdout.write(line)

        for agency, reason in blocked:
            lines.append(f'  –  {agency.slug}: {reason}')
            self.stdout.write(self.style.WARNING(f'  –  {agency.slug}: {reason}'))

        run.status = CrawlRun.OK if dead == 0 else CrawlRun.PARTIAL
        run.finished_at = timezone.now()
        run.sources_ok, run.sources_dead, run.sources_skipped = ok, dead, len(blocked)
        run.offers_total = totals['found']
        run.offers_new, run.offers_changed = totals['new'], totals['changed']
        run.log = '\n'.join(lines)
        run.save()

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Общо: {totals["found"]} обяви открити · {totals["new"]} нови · '
            f'{totals["changed"]} променени · {totals["skipped"]} вече в базата · '
            f'{totals["failed"]} неуспешни'))

    def _one(self, agency, spec, run, today, options):
        found = catalog.discover(agency.slug, spec)
        result = {'found': len(found), 'new': 0, 'changed': 0, 'same': 0,
                  'skipped': 0, 'failed': 0, 'sold': 0, 'retired': 0}
        if options['discover_only']:
            result['skipped'] = len(found)
            return result

        known = store.known_urls(agency)
        todo = [u for u in found if options['refresh'] or u not in known]
        result['skipped'] = len(found) - len(todo)
        if options['limit']:
            todo = todo[:options['limit']]

        for url in todo:
            response = fetch.get(url)
            if response['status'] != 200 or not response['body']:
                result['failed'] += 1
                continue
            try:
                record = extract.extract(response['body'], url, spec)
            except Exception:                                  # noqa: BLE001
                result['failed'] += 1
                continue
            if record is None:
                result['failed'] += 1
                continue

            path = fetch.save_snapshot(run.pk, agency.slug, url, response['body'])
            evidence = {'fetched_at': timezone.now().isoformat(), 'method': 'curl',
                        'http_status': response['status'], 'snapshot_path': path,
                        'quoted_price_text': record.get('price_raw', ''),
                        'run': run.pk, 'crawler': 'crawl_sites'}
            with transaction.atomic():
                outcome = store.store(agency, record, evidence, today)
            result[outcome] += 1

        # Anything we hold that the agency no longer advertises has gone. The
        # guard matters: a catalogue that failed to load looks identical to an
        # agency that sold everything, and acting on that would empty the stock.
        if not options['limit'] and not options['discover_only']:
            held = Offer.objects.filter(agency=agency, source=OfferSource.WEB,
                                        is_active=True).count()
            if held and len(found) >= held * 0.5:
                result['retired'] = store.retire_missing(agency, set(found), today)
            elif held:
                result['retired'] = 0
                result['warning'] = (f'каталогът върна {len(found)} обяви срещу '
                                     f'{held} записани — нищо не е свалено')

        return result

    # -- modes the stored URL makes possible --------------------------------

    def _agencies(self, options):
        queryset = Agency.objects.filter(duplicate_of__isnull=True)
        if options['agencies']:
            queryset = queryset.filter(slug__in=options['agencies'])
        return queryset.order_by('slug')

    def _reextract(self, options):
        """Read the saved pages again with today's extractor. No network at all.

        Every improvement to extraction would otherwise mean re-fetching several
        thousand pages from other people's servers. The snapshots exist so that
        it costs nothing but CPU.
        """
        today = dt.date.today()
        offers = (Offer.objects.filter(source=OfferSource.WEB,
                                       agency__in=self._agencies(options))
                  .exclude(listing_url='').select_related('agency').order_by('id'))
        counts = {'new': 0, 'changed': 0, 'same': 0, 'failed': 0}

        for offer in offers.iterator(chunk_size=200):
            path = (offer.evidence or {}).get('snapshot_path')
            if not path:
                counts['failed'] += 1
                continue
            try:
                html = fetch.read_snapshot(path)
                record = extract.extract(html, offer.listing_url,
                                         sites.recipe(offer.agency.slug) or {})
            except Exception:                                   # noqa: BLE001
                counts['failed'] += 1
                continue
            if record is None:
                counts['failed'] += 1
                continue
            with transaction.atomic():
                counts[store.store(offer.agency, record, offer.evidence, today)] += 1

        self.stdout.write(self.style.SUCCESS(
            f'Преразчитане: {counts["changed"]} обновени · {counts["same"]} без промяна '
            f'· {counts["failed"]} неуспешни'))

    def _verify(self, options):
        """Ask each stored listing URL whether it is still there."""
        today = dt.date.today()
        offers = (Offer.objects.filter(source=OfferSource.WEB, is_active=True,
                                       agency__in=self._agencies(options))
                  .exclude(listing_url='').select_related('agency').order_by('id'))
        if options['limit']:
            offers = offers[:options['limit']]

        alive = gone = unknown = 0
        for offer in offers:
            response = fetch.get(offer.listing_url, timeout=20)
            if response['status'] in (404, 410):
                # Withdrawn, not deleted: a client was shown this flat last week
                # and the record of that has to keep resolving.
                Offer.objects.filter(pk=offer.pk).update(
                    is_active=False, last_changed=today, status='withdrawn')
                OfferHistory.objects.create(offer=offer, event=OfferHistory.REMOVED,
                                            field='', old_value='', new_value='',
                                            changed_on=today)
                gone += 1
            elif response['status'] == 200:
                Offer.objects.filter(pk=offer.pk).update(last_seen=today)
                alive += 1
            else:
                unknown += 1

        self.stdout.write(self.style.SUCCESS(
            f'Проверка: {alive} още стоят · {gone} свалени · {unknown} без ясен отговор'))
