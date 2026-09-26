"""Retry recorded failed public details without re-fetching an entire catalogue."""
import hashlib
import json
import uuid
from urllib.parse import urlencode
from urllib.robotparser import RobotFileParser

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from market import bulgarian_properties as bp
from market.bp_crawl import HOST_LOCK, save_image, save_offer
from market.bp_units import price_list_url, units
from market.models import City, SiteProbe
from market.sofia_crawl import ensure_agency, mark_verified_unavailable, store_offer
from market.sofia_sources import ADAPTERS, COHORT, ParseError
from market.source_http import SourceBlocked, SourceClient
from sourcing.models import Agency, CrawlRun, Offer


class Command(BaseCommand):
    help = 'Retry failed Sofia detail/image/project-unit URLs recorded in a completed, unblocked run.'

    def add_arguments(self, parser):
        parser.add_argument('--run', type=int, required=True)
        parser.add_argument('--missing-images', action='store_true',
                            help='Also retry verified stored offers that have no thumbnail')
        parser.add_argument('--capture-pages', action='store_true',
                            help='Keep original public HTML bytes privately for parser diagnosis')
        parser.add_argument('--catalogue-tail', action='store_true',
                            help='Check ARCO partial final pages omitted by its public pager')
        parser.add_argument('--incomplete-kinds', action='store_true',
                            help='Recheck Home2U stored listings with generic property headings')

    def handle(self, *args, **options):
        previous = CrawlRun.objects.filter(pk=options['run']).first()
        if not previous or previous.status == 'running' or not previous.log:
            raise CommandError('A completed Sofia run with a report is required')
        report = json.loads(previous.log)
        stats = report.get('stats', {})
        slug = stats.get('agency')
        if slug not in COHORT or stats.get('city') != 'sofia':
            raise CommandError('Only the five verified Sofia adapters support retries')
        if stats.get('blocked'):
            raise CommandError('A blocked source cannot be retried as part of the same crawl')
        old_probe = SiteProbe.objects.get(pk=report['probe_id'])
        discovered = {row['url']: row for row in old_probe.strategy.get('discovered_urls', [])}
        by_ref = {str(row['ref']): row for row in discovered.values()}
        for row in report['outcomes']:
            if row.get('url') and row.get('ref'):
                ref = str(row['ref'])
                by_ref[ref] = {**by_ref.get(ref, {}), **row}
        pending = {}
        for row in report['outcomes']:
            if not any(k in row for k in ('error', 'image_error', 'project_unit_error')):
                continue
            known = discovered.get(row.get('url')) or by_ref.get(str(row.get('ref')))
            if known and known.get('url'):
                pending[known['url']] = known
        if slug == 'yavlena':
            # Repair known property references advertised under both deals.
            # Both own URLs must be rechecked, retaining the original row IDs.
            deals = {}
            for row in discovered.values():
                deals.setdefault(str(row['ref']), set()).add(row.get('deal'))
            for row in discovered.values():
                if deals[str(row['ref'])] == {'sale', 'rent'}:
                    pending[row['url']] = row
        if options['missing_images']:
            ids = [r['offer_id'] for r in report['outcomes'] if r.get('outcome') == 'stored' and r.get('offer_id')]
            missing = set(Offer.objects.filter(pk__in=ids, agency__slug=slug, geo__city__slug='sofia',
                                               is_active=True, images__isnull=True).values_list('pk', flat=True))
            for row in report['outcomes']:
                if row.get('offer_id') in missing:
                    known = discovered.get(row.get('url')) or by_ref.get(str(row.get('ref')))
                    if known and known.get('url'):
                        pending[known['url']] = known
        if options['incomplete_kinds'] and slug == 'home2u':
            ids = [r['offer_id'] for r in report['outcomes'] if r.get('outcome') == 'stored' and r.get('offer_id')]
            for offer in Offer.objects.filter(pk__in=ids, agency__slug=slug, geo__city__slug='sofia',
                    is_active=True, property_kind__istartswith='За имота'):
                known = discovered.get(offer.listing_url)
                if known:
                    pending[known['url']] = known
        tail = stats.get('catalogues', {}) if options['catalogue_tail'] and slug == 'arco-real-estate' else {}
        if options['catalogue_tail'] and not tail:
            raise CommandError('Catalogue tails require an original ARCO catalogue report')
        if not pending and not tail:
            self.stdout.write('No recorded detail, image or project-unit URLs to retry.')
            return
        is_bp = slug == 'bulgarian-properties'
        adapter = None if is_bp else ADAPTERS[slug]
        host = bp.HOST if is_bp else adapter.host
        lock = HOST_LOCK if is_bp else int.from_bytes(hashlib.sha256(host.encode()).digest()[:7], 'big')
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_try_advisory_lock(%s)', [lock])
            if not cursor.fetchone()[0]:
                raise CommandError('The source is still crawling; wait for its current run')
        try:
            agency = Agency.objects.get(slug=slug) if is_bp else ensure_agency(adapter)
            if agency.crawl_opt_out:
                raise CommandError('Agency has opted out')
            self.retry(previous, old_probe, agency, adapter, host, pending, options['capture_pages'], tail)
        finally:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [lock])

    def retry(self, previous, old_probe, agency, adapter, host, pending, capture_pages, tail):
        is_bp = adapter is None
        client = SourceClient((bp.HOST, 'static.bulgarianproperties.com') if is_bp else adapter.hosts)
        run = CrawlRun.objects.create(kind='sites', run_date=timezone.localdate(), status='running')
        probe = SiteProbe.objects.create(city=City.objects.get(slug='sofia'), agency_slug=agency.slug,
            agency_name=agency.name, website=agency.website, run_id=uuid.uuid4().hex[:12],
            run_started=run.started_at, status='no_listings')
        stats = dict(agency=agency.slug, city='sofia', retry_of=previous.pk, discovered=len(pending),
            fetched=0, stored=0, new=0, updated=0, images=0, errors=0, image_errors=0, blocked=0,
            project=0, unavailable=0, outside_city=0, stale_catalogue_links=0,
            discovery_complete=False, detail_complete=False, retirement_enabled=False)
        outcomes, robots = [], RobotFileParser()

        def get(url):
            if settings.CRAWL_RESPECT_ROBOTS and not robots.can_fetch(settings.CRAWL_USER_AGENT_BOT, url):
                raise SourceBlocked('robots excludes public retry URL')
            response = client.get(url, binary=capture_pages)
            if capture_pages and response.get('blob'):
                folder = settings.DATA_DIR / 'recon' / 'sofia-retries' / agency.slug / str(run.pk)
                folder.mkdir(parents=True, exist_ok=True)
                key = hashlib.sha256(url.encode()).hexdigest()[:16]
                (folder / (key + '.html')).write_bytes(response['blob'])
                (folder / (key + '.json')).write_text(json.dumps(
                    {k: response[k] for k in ('url', 'status', 'encoding', 'bytes', 'error')}, ensure_ascii=False))
            if response['status'] == 404:
                return response
            if not response['ok']:
                raise ParseError(f'HTTP {response["status"]} at {url}')
            return response

        def store(parsed, response, source_url, *, project_unit=False):
            if parsed['outcome'] != 'offer':
                stats[parsed['outcome']] += 1
                outcomes.append(parsed)
                if parsed['outcome'] == 'unavailable':
                    mark_verified_unavailable(agency, parsed, dict(run=run.pk, source_url=source_url))
                return
            evidence = dict(crawler='retry_sofia', adapter=agency.slug + '-sofia-retry-v1', city='sofia',
                run=run.pk, retry_of=previous.pk, source_ref=parsed['ref'], source_url=parsed['url'],
                fetched_at=timezone.now().isoformat(), method='own-public-source-fields',
                fields=parsed['fields'], quoted_price_text=parsed['record']['price_raw'],
                body_sha256=hashlib.sha256(response['body'].encode()).hexdigest(),
                encoding=response.get('encoding', ''), image_sources=parsed['images'][:1])
            if project_unit:
                evidence.update(price_list_url=source_url, image_scope='development')
            offer, changes = (save_offer if is_bp else store_offer)(agency, parsed, evidence)
            stats['stored'] += 1
            stats['new'] += changes['new']
            stats['updated'] += changes['updated']
            outcomes.append(dict(ref=parsed['ref'], url=parsed['url'], outcome='stored', offer_id=offer.pk))
            if parsed['images']:
                try:
                    # A broken first gallery file should not hide the next
                    # verified own photograph. Keep this recovery bounded.
                    image_error = None
                    for image_url in parsed['images'][:3]:
                        try:
                            stats['images'] += int(save_image(offer, image_url, client))
                            image_error = None
                            break
                        except (ValueError, OSError) as exc:
                            image_error = exc
                    if image_error:
                        raise image_error
                except SourceBlocked:
                    raise
                except (ValueError, OSError) as exc:
                    stats['image_errors'] += 1
                    outcomes.append(dict(ref=parsed['ref'], url=parsed['url'], image_error=str(exc)[:300]))

        try:
            response = client.get(f'https://{host}/robots.txt')
            probe.robots_found = response['ok']
            if response['ok']:
                robots.parse(response['body'].splitlines())
                probe.robots_disallow = [s.split(':', 1)[1].strip() for s in response['body'].splitlines()
                                        if s.lower().startswith('disallow:')]
                probe.sitemaps = robots.site_maps() or []
                probe.robots_blocks_listings = any(not robots.can_fetch(settings.CRAWL_USER_AGENT_BOT, url) for url in pending)
            elif settings.CRAWL_RESPECT_ROBOTS:
                raise SourceBlocked('Unable to verify robots for retry')
            if tail:
                known_urls = {r['url'] for r in old_probe.strategy.get('discovered_urls', [])}
                stats['catalogue_tail'] = {}
                for deal, cat in tail.items():
                    own = {r['url'] for r in old_probe.strategy.get('discovered_urls', []) if r['deal'] == deal}
                    url = adapter.starts[deal] + '&' + urlencode(dict(page=cat['pages'] + 1, limit=10))
                    pages = 0
                    while url and pages < 10 and len(own) < cat['advertised']:
                        response = get(url)
                        page = adapter.catalogue(response['body'], url, deal)
                        if not page['rows'] or not any(r['url'] not in own for r in page['rows']):
                            raise ParseError('Catalogue tail repeated known offers')
                        for row in page['rows']:
                            own.add(row['url'])
                            if row['url'] not in known_urls:
                                pending[row['url']] = row
                        pages += 1
                        url = page['next_url']
                    stats['catalogue_tail'][deal] = dict(extra_pages=pages, unique_urls=len(own),
                        advertised=cat['advertised'], complete=len(own) == cat['advertised'] and not url)
                stats['discovered'] = len(pending)
            for url, row in pending.items():
                stats['fetched'] += 1
                try:
                    response = get(url)
                    if response['status'] == 404:
                        stats['stale_catalogue_links'] += 1
                        outcomes.append(dict(url=url, outcome='stale_catalogue_link', http_status=404))
                        continue
                    deal = row.get('deal') or ('rent' if ('/rent' in url if agency.slug == 'yavlena' else '-pod-naem-' in url) else 'sale')
                    parsed = bp.detail(response['body'], url) if is_bp else adapter.detail(response['body'], url, deal)
                    store(parsed, response, url)
                    if is_bp and parsed['outcome'] == 'project':
                        price_url = price_list_url(response['body'], url)
                        if price_url:
                            price_response = get(price_url)
                            for unit in units(price_response['body'], response['body'], url):
                                store(unit, price_response, price_url, project_unit=True)
                except SourceBlocked:
                    raise
                except (ValueError, OSError) as exc:
                    stats['errors'] += 1
                    outcomes.append(dict(url=url, ref=row.get('ref', ''), error=str(exc)[:300]))
                self.stdout.write(f'{agency.name} retry: {stats["fetched"]}/{len(pending)} details, {stats["stored"]} stored, {stats["errors"]} errors')
            stats['detail_complete'] = stats['fetched'] == len(pending) and not stats['errors']
        except SourceBlocked as exc:
            stats['blocked'] += 1
            outcomes.append(dict(error=str(exc)[:300]))
        except Exception as exc:
            stats['errors'] += 1
            outcomes.append(dict(error=f'{type(exc).__name__}: {exc}'[:300]))
        finally:
            success = stats['detail_complete'] and not stats['blocked'] and not stats['image_errors']
            run.status, run.finished_at = ('ok' if success else 'partial'), timezone.now()
            run.sources_ok, run.sources_dead = int(success), int(bool(stats['errors'] or stats['blocked']))
            run.offers_total, run.offers_new, run.offers_changed = stats['stored'], stats['new'], stats['updated']
            probe.status = 'blocked' if stats['blocked'] else 'http_error' if stats['errors'] else 'ok'
            probe.strategy = dict(retry_of=previous.pk, retirement_enabled=False, statistics=stats,
                requests=client.responses, discovered_urls=list(pending.values()), outcomes=outcomes)
            probe.note = 'Retry of recorded failed URLs only; this is not fresh full-catalogue discovery.'
            probe.save()
            run.log = json.dumps(dict(stats=stats, outcomes=outcomes, probe_id=probe.pk), ensure_ascii=False)
            run.save()
            settings.RUNS_DIR.mkdir(parents=True, exist_ok=True)
            (settings.RUNS_DIR / f'{agency.slug}-retry-{run.pk}.json').write_text(run.log)
            self.stdout.write(json.dumps(dict(run=run.pk, status=run.status, **stats), ensure_ascii=False))
        if stats['errors'] or stats['blocked'] or stats['image_errors']:
            raise CommandError(f'Retry #{run.pk} recorded failures; inspect its report')
