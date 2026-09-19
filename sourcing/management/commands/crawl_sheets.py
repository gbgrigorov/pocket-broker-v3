# -*- coding: utf-8 -*-
"""Download every agency price sheet, parse it, and write the day's diff.

Downloading and parsing are the vendored upstream modules, used unchanged. The
only thing rebound is where they put their files, so snapshots land under this
project's data/ rather than inside the app package -- configuration from
outside, not a fork.
"""
import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from sourcing import ingest
from sourcing.models import Agency, CrawlRun, Offer, SheetSnapshot
from sourcing import vendor  # noqa: F401  (puts vendor/ on sys.path)

import fetch as fetch_mod        # noqa: E402
import normalize                 # noqa: E402

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Сваля таблиците на агенциите, разчита ги и записва промените.'

    def add_arguments(self, parser):
        parser.add_argument('--agency', action='append', dest='agencies',
                            help='Само тази агенция (slug). Може да се повтаря.')
        parser.add_argument('--limit', type=int, help='Само първите N агенции.')
        parser.add_argument('--force', action='store_true',
                            help='Разчита и таблиците без промяна.')
        parser.add_argument('--offline', action='store_true',
                            help='Без сваляне — използва последния наличен файл.')

    def handle(self, *args, **options):
        today = dt.date.today()
        # The vendored modules compute their paths at import time; point them at
        # this project's data directory and today's date for a long-lived process.
        fetch_mod.RAW = settings.RAW_DIR
        fetch_mod.TODAY = today.isoformat()
        settings.RAW_DIR.mkdir(parents=True, exist_ok=True)

        queryset = Agency.objects.filter(duplicate_of__isnull=True)
        if options['agencies']:
            queryset = queryset.filter(slug__in=options['agencies'])
        agencies = list(queryset.order_by('slug'))
        if options['limit']:
            agencies = agencies[:options['limit']]

        run = CrawlRun.objects.create(run_date=today, status=CrawlRun.RUNNING)
        self.stdout.write(f'Обхождане {today} · {len(agencies)} агенции')

        results = self._fetch_all(agencies, run, offline=options['offline'])
        totals = {'new': 0, 'changed': 0, 'unchanged': 0, 'gone': 0, 'rekeyed': 0}
        ok = dead = skipped = 0
        lines = []

        for agency, result in results:
            status = result['status']
            if status == 'skipped':
                skipped += 1
                lines.append(f"  –  {agency.slug}: {result.get('reason', '')}")
                continue
            if status in ('dead', 'error'):
                dead += 1
                lines.append(f"  ✗  {agency.slug}: {result.get('reason', '')}")
                Agency.objects.filter(pk=agency.pk).update(source_status=status)
                continue

            ok += 1
            path = result['path']
            snapshot = SheetSnapshot.objects.filter(agency=agency).order_by('-run__run_date').first()
            unchanged = snapshot is not None and snapshot.sha256 == result['sha256']

            if unchanged and not options['force']:
                # Nothing moved in the sheet, so nothing can have moved in the
                # data. Still mark the offers as seen today so retirement logic
                # downstream does not mistake them for withdrawn.
                touched = Offer.objects.filter(agency=agency, is_active=True).update(
                    last_seen=today)
                SheetSnapshot.objects.update_or_create(
                    run=run, agency=agency,
                    defaults={'sha256': result['sha256'], 'changed': False,
                              'offers_count': touched, 'file_path': str(path)})
                lines.append(f'  =  {agency.slug}: без промяна ({touched} оферти)')
                continue

            try:
                records, diagnostics = normalize.extract_offers(
                    agency.slug, {'name': agency.name}, str(path), today.isoformat())
            except Exception as exc:                       # a malformed workbook
                dead += 1
                lines.append(f'  ✗  {agency.slug}: грешка при разчитане — {exc}')
                SheetSnapshot.objects.update_or_create(
                    run=run, agency=agency,
                    defaults={'sha256': result['sha256'], 'error': str(exc),
                              'file_path': str(path)})
                continue

            counts = ingest.sync_agency_offers(agency, records, today)
            for key in totals:
                totals[key] += counts.get(key, 0)
            SheetSnapshot.objects.update_or_create(
                run=run, agency=agency,
                defaults={'sha256': result['sha256'], 'changed': True,
                          'offers_count': len(records), 'file_path': str(path)})
            flags = []
            if counts['new']:
                flags.append(f"+{counts['new']}")
            if counts['changed']:
                flags.append(f"~{counts['changed']}")
            if counts['gone']:
                flags.append(f"-{counts['gone']}")
            if counts['rekeyed']:
                flags.append(f"↻{counts['rekeyed']}")
            lines.append(f"  ✓  {agency.slug}: {len(records)} оферти "
                         f"{' '.join(flags) or '(без промени)'}"
                         + (f'  ⚠ {len(diagnostics)} бележки' if diagnostics else ''))

        run.status = CrawlRun.OK if dead == 0 else CrawlRun.PARTIAL
        run.finished_at = timezone.now()
        run.sources_ok, run.sources_dead, run.sources_skipped = ok, dead, skipped
        run.offers_total = Offer.objects.filter(is_active=True).count()
        run.offers_new, run.offers_changed, run.offers_gone = (
            totals['new'], totals['changed'], totals['gone'])
        run.log = '\n'.join(lines)
        run.save()

        for line in lines:
            self.stdout.write(line)
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f"Готово: {ok} успешни · {dead} недостъпни · {skipped} пропуснати"))
        self.stdout.write(
            f"Оферти: {totals['new']} нови · {totals['changed']} променени · "
            f"{totals['gone']} премахнати · {totals['rekeyed']} преномерирани")
        self.stdout.write(f"Активни в базата: {run.offers_total}")

    # ------------------------------------------------------------------ fetch
    def _fetch_all(self, agencies, run, offline=False):
        if offline:
            return [(a, self._latest_local(a)) for a in agencies]

        payloads = [{'slug': a.slug, 'name': a.name, 'source_kind': a.source_kind,
                     'doc_id': a.doc_id, 'gid': a.gid} for a in agencies]
        with ThreadPoolExecutor(max_workers=settings.CRAWL_WORKERS) as pool:
            fetched = list(pool.map(fetch_mod.fetch_one, payloads))
        by_slug = {r['slug']: r for r in fetched}
        out = []
        for agency in agencies:
            result = by_slug.get(agency.slug, {'status': 'error', 'reason': 'no result'})
            if result['status'] == 'ok':
                result['path'] = settings.RAW_DIR / agency.slug / f"{fetch_mod.TODAY}.xlsx"
            out.append((agency, result))
        return out

    def _latest_local(self, agency):
        """Offline mode: newest snapshot already on disk. Used by tests and demos."""
        folder = settings.RAW_DIR / agency.slug
        files = sorted(folder.glob('*.xlsx')) if folder.exists() else []
        if not files:
            return {'status': 'skipped', 'reason': 'няма локален файл'}
        newest = files[-1]
        return {'status': 'ok', 'path': newest,
                'sha256': fetch_mod.content_sha256(newest), 'slug': agency.slug}
