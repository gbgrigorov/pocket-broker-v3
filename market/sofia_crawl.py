"""Bounded Sofia imports: one host at a time, public GETs, no retirement.

--limit counts detail requests per source; --max-pages applies per sale/rent
catalogue. A bounded sample is explicitly partial even if every detail succeeds.
"""
import hashlib
import json
import random
import re
import time
import uuid
from collections import deque
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from django.conf import settings
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from market.bp_crawl import save_image, save_offer
from market.models import City, SiteProbe
from market.sofia_sources import ADAPTERS, ParseError
from market.source_http import SourceBlocked, SourceClient
from sourcing.models import Agency, CrawlRun, Offer, OfferHistory
from sourcing.web.store import fingerprint


@transaction.atomic
def ensure_agency(adapter):
    """Reuse registry identities; never override an opt-out or duplicate row."""
    agency = Agency.objects.filter(slug=adapter.slug).first()
    if agency is None:
        matches = [a for a in Agency.objects.all() if (
            urlsplit(a.website).hostname in adapter.hosts[:2] or a.name.casefold() == adapter.name.casefold())]
        if len(matches) > 1:
            raise CommandError(f'{adapter.name}: ambiguous existing agency identity')
        agency = matches[0] if matches else Agency.objects.create(slug=adapter.slug,
            name=adapter.name, website=f'https://{adapter.host}/', website_source='recon',
            listing_url_patterns=['/property/' if adapter.slug == 'home2u' else '/bg/' if adapter.slug == 'yavlena' else '/luksozen-imot-' if adapter.slug == 'luximmo' else '/оферти/'])
    if agency.crawl_opt_out or agency.duplicate_of_id:
        raise CommandError(f'{adapter.name}: registry opted out or marked duplicate')
    if urlsplit(agency.website).hostname not in adapter.hosts[:2]:
        raise CommandError(f'{adapter.name}: existing registry website is inconsistent')
    return agency


@transaction.atomic
def store_offer(agency, parsed, evidence):
    record = parsed['record']
    identity = Q(ref=record['ref']) | Q(listing_url=record['listing_url'])
    repair = False
    if agency.slug == 'yavlena':
        # One property can have two distinct services: sale and rental. The
        # original URL fingerprint also preserves IDs from earlier imports
        # that mistakenly changed a rental row into its sale counterpart.
        opposite = f'https://www.yavlena.com/bg/{record["ref"]}'
        if record['deal_type'] == 'sale':
            opposite += '/rent'
        identity = (Q(fingerprint=fingerprint(record['listing_url'])) |
                    Q(listing_url=record['listing_url']) |
                    Q(ref=record['ref'], deal_type=record['deal_type'])) & ~Q(fingerprint=fingerprint(opposite))
        Agency.objects.select_for_update().get(pk=agency.pk)
        old = list(Offer.objects.select_for_update().filter(agency=agency, source='web').filter(identity)[:2])
        if len(old) == 1 and old[0].evidence.get('identity_repair'):
            evidence = {**evidence, 'identity_repair': old[0].evidence['identity_repair']}
        repair = len(old) == 1 and old[0].deal_type != record['deal_type']
        if repair:
            evidence = {**evidence, 'identity_repair': dict(
                previous_deal=old[0].deal_type, restored_deal=record['deal_type'],
                previous_price= str(old[0].price_eur),
                note='Earlier cross-deal price history is not comparable.')}
    offer, changes = save_offer(agency, parsed, evidence, identity_query=identity)
    if repair:
        offer.prev_price_eur = None
        offer.save(update_fields=['prev_price_eur'])
        OfferHistory.objects.create(offer=offer, event='changed', field='identity_repair',
            old_value=evidence['identity_repair']['previous_deal'], new_value=record['deal_type'],
            changed_on=timezone.localdate())
    return offer, changes


@transaction.atomic
def mark_verified_unavailable(agency, parsed, evidence):
    """Positive own-page evidence only; never absence from a partial catalogue."""
    if parsed.get('outcome') != 'unavailable' or not re.match(r'^(?:София|Sofia)(?:\s*,|\s*$)', parsed.get('location', ''), re.I):
        raise ParseError('Expected positively verified unavailable Sofia listing')
    Agency.objects.select_for_update().get(pk=agency.pk)
    identity = Q(ref=parsed['ref']) | Q(listing_url=parsed['url'])
    if agency.slug == 'yavlena':
        # Sold sale service must not deactivate its still available rental.
        identity = Q(listing_url=parsed['url'])
    matches = list(Offer.objects.select_for_update().filter(agency=agency, source='web',
        geo__city__slug='sofia', is_active=True).filter(identity)[:2])
    if len(matches) > 1:
        raise ParseError('Ambiguous unavailable listing identity')
    if not matches:
        return 0
    offer = matches[0]
    offer.is_active = False
    offer.status = 'unavailable'
    offer.last_seen = offer.last_changed = timezone.localdate()
    offer.evidence = {**offer.evidence, 'availability_evidence': evidence}
    offer.save(update_fields=['is_active', 'status', 'last_seen', 'last_changed', 'evidence', 'updated_at'])
    OfferHistory.objects.create(offer=offer, event='removed', field='is_active',
        old_value='True', new_value='False', changed_on=timezone.localdate())
    return 1


def crawl(slug, *, limit=None, max_pages=100, discover_only=False, no_images=False,
          sample_seed=None, emit=print, client=None):
    if slug not in ADAPTERS:
        raise CommandError(f'Unknown Sofia adapter: {slug}')
    if (limit is not None and limit <= 0) or max_pages <= 0:
        raise CommandError('limit and max-pages must be positive')
    adapter = ADAPTERS[slug]
    city = City.objects.filter(slug='sofia').first()
    if city is None:
        raise CommandError('Seeded Sofia city is required')
    lock = int.from_bytes(hashlib.sha256(adapter.host.encode()).digest()[:7], 'big')
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [lock])
        if not cursor.fetchone()[0]:
            raise CommandError(f'{adapter.name}: host crawl already running')
    try:
        agency = ensure_agency(adapter)
        return _crawl(adapter, agency, city, limit, max_pages, discover_only,
                      no_images, sample_seed, emit, client)
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', [lock])


def _crawl(adapter, agency, city, limit, max_pages, discover_only, no_images, sample_seed, emit, client):
    started = time.monotonic()
    client = client or SourceClient(adapter.hosts)
    run = CrawlRun.objects.create(kind='sites', run_date=timezone.localdate(), status='running')
    probe = SiteProbe.objects.create(city=city, agency_slug=agency.slug, agency_name=agency.name,
        website=f'https://{adapter.host}/', run_id=uuid.uuid4().hex[:12], run_started=run.started_at,
        status='no_listings', final_url=next(iter(adapter.starts.values())))
    stats = dict(agency=agency.slug, city='sofia', discovered=0, fetched=0, stored=0,
        new=0, updated=0, price_changes=0, returned=0, marked_inactive=0, errors=0,
        blocked=0, images=0, image_errors=0, project=0, outside_city=0, unavailable=0,
        verified_unavailable_disabled=0, missing_offers_marked_inactive=0,
        pages=0, discovery_complete=False, detail_complete=False, discover_only=discover_only,
        limit=limit, max_pages=max_pages, sample_seed=sample_seed, catalogues={})
    outcomes, discovered, stored = [], {}, []
    robots = RobotFileParser()
    respect = getattr(settings, 'CRAWL_RESPECT_ROBOTS', False)

    def get(url, **kwargs):
        if respect and not robots.can_fetch(settings.CRAWL_USER_AGENT_BOT, url):
            raise SourceBlocked(f'robots policy excludes {url}')
        response = client.get(url, **kwargs)
        if not response['ok']:
            raise ParseError(f'HTTP {response["status"]} at {url}')
        return response

    try:
        response = client.get(f'https://{adapter.host}/robots.txt')
        probe.robots_found = response['ok']
        if response['ok']:
            robots.parse(response['body'].splitlines())
            probe.robots_disallow = [s.split(':', 1)[1].strip() for s in response['body'].splitlines() if s.lower().startswith('disallow:')]
            probe.sitemaps = robots.site_maps() or []
            probe.robots_blocks_listings = any(not robots.can_fetch(settings.CRAWL_USER_AGENT_BOT, u) for u in adapter.starts.values())
        elif respect:
            raise SourceBlocked('Unable to verify robots policy')
        for deal, first_url in adapter.starts.items():
            url, visited, own = first_url, set(), set()
            cat = stats['catalogues'][deal] = dict(pages=0, discovered=0, returned_cards=0, duplicate_urls=0, advertised=None,
                advertised_last=None, count_changed=False, complete=False)
            while url and cat['pages'] < max_pages:
                if url in visited:
                    raise ParseError('Repeated catalogue pagination URL')
                visited.add(url)
                response = get(url)
                page = adapter.catalogue(response['body'], url, deal)
                probe.meta_charset, probe.http_status = response.get('encoding', ''), response['status']
                if cat['pages'] == 0:
                    cat['advertised'] = page['total']
                elif cat['advertised'] != page['total']:
                    cat['count_changed'] = True
                cat['advertised_last'] = page['total']
                new_rows = [r for r in page['rows'] if r['url'] not in own]
                if page['rows'] and not new_rows:
                    raise ParseError('Pagination repeated the previous listings')
                for row in page['rows']:
                    cat['returned_cards'] += 1
                    if row['url'] in own:
                        cat['duplicate_urls'] += 1
                        outcomes.append(dict(url=row['url'], catalogue=deal, outcome='duplicate_card', page=cat['pages'] + 1))
                    own.add(row['url'])
                    discovered[row['url']] = row
                cat['discovered'] = len(own)
                cat['pages'] += 1
                stats['pages'] += 1
                stats['discovered'] = len(discovered)
                emit(f'{adapter.name} Sofia {deal}: page {cat["pages"]}, {cat["discovered"]} URLs')
                url = page['next_url']
            cat['complete'] = not url and not cat['count_changed'] and (cat['advertised'] is None or
                len(own) == cat['advertised'] or cat['returned_cards'] == cat['advertised'])
            if not url and not cat['complete']:
                outcomes.append(dict(catalogue=deal, warning='Count drift or pagination/count mismatch; coverage remains partial'))
        stats['discovery_complete'] = all(c['complete'] for c in stats['catalogues'].values())
        probe.status = 'ok'
        if not discover_only:
            groups = [deque(r for r in discovered.values() if r['deal'] == deal) for deal in ('sale', 'rent')]
            if sample_seed is not None:
                for i, group in enumerate(groups):
                    shuffled = list(group)
                    random.Random(sample_seed + i).shuffle(shuffled)
                    groups[i] = deque(shuffled)
            selected = []
            while any(groups) and (limit is None or len(selected) < limit):
                for group in groups:
                    if group and (limit is None or len(selected) < limit):
                        selected.append(group.popleft())
            for row in selected:
                stats['fetched'] += 1
                try:
                    response = get(row['url'])
                    parsed = adapter.detail(response['body'], row['url'], row['deal'])
                    evidence = dict(crawler='crawl_live', adapter=f'{adapter.slug}-sofia-v1', city='sofia',
                        run=run.pk, source_ref=parsed['ref'], source_url=parsed['url'],
                        fetched_at=timezone.now().isoformat(), method='own-dom-and-public-structured-data',
                        body_sha256=hashlib.sha256(response['body'].encode()).hexdigest(),
                        encoding=response.get('encoding', ''))
                    if parsed['outcome'] != 'offer':
                        stats[parsed['outcome']] += 1
                        if parsed['outcome'] == 'unavailable':
                            disabled = mark_verified_unavailable(agency, parsed, evidence)
                            stats['verified_unavailable_disabled'] += disabled
                            stats['marked_inactive'] += disabled
                        outcomes.append(parsed)
                        continue
                    if adapter.slug != 'home2u' and parsed['ref'] != row['ref']:
                        raise ParseError('Detail changed the discovered source identity')
                    evidence.update(quoted_price_text=parsed['record']['price_raw'],
                                    fields=parsed['fields'], image_sources=parsed['images'][:1])
                    offer, changes = store_offer(agency, parsed, evidence)
                    stored.append(offer.pk)
                    stats['stored'] += 1
                    for key, count in changes.items():
                        stats[key] += count
                    outcomes.append(dict(ref=parsed['ref'], url=parsed['url'], outcome='stored', offer_id=offer.pk, **changes))
                    if not no_images and parsed['images']:
                        try:
                            stats['images'] += int(save_image(offer, parsed['images'][0], client))
                        except SourceBlocked:
                            raise
                        except (ValueError, OSError) as exc:
                            stats['image_errors'] += 1
                            outcomes.append(dict(ref=parsed['ref'], image_error=str(exc)[:300]))
                except SourceBlocked:
                    raise
                except (ValueError, OSError) as exc:
                    stats['errors'] += 1
                    outcomes.append(dict(url=row['url'], error=str(exc)[:300]))
                emit(f'{adapter.name} Sofia: fetched {stats["fetched"]}, stored {stats["stored"]}, errors {stats["errors"]}')
            stats['detail_complete'] = stats['discovery_complete'] and stats['fetched'] == len(discovered) and not stats['errors']
    except SourceBlocked as exc:
        stats['blocked'] += 1
        probe.status = 'blocked'
        outcomes.append(dict(error=str(exc)[:300]))
    except Exception as exc:
        stats['errors'] += 1
        probe.status = 'http_error'
        outcomes.append(dict(error=f'{type(exc).__name__}: {exc}'[:300]))
    finally:
        stats['seconds'] = round(time.monotonic() - started, 2)
        qs = Offer.objects.filter(pk__in=stored)
        def pct(count):
            return round(count * 100 / len(stored), 1) if stored else None
        stats['quality'] = dict(sample_size=len(stored),
            price_fill_pct=pct(qs.filter(price_eur__isnull=False).count()),
            area_fill_pct=pct(qs.filter(area_m2__isnull=False).count()),
            neighbourhood_resolved_pct=pct(qs.filter(geo__neighbourhood__isnull=False).count()),
            image_fill_pct=pct(qs.filter(images__isnull=False).distinct().count()))
        probe.strategy = dict(adapter=f'{adapter.slug}-sofia-v1', catalogues=adapter.starts,
            identity='agency + own source reference (canonical URL reconciliation)', retirement_enabled=False,
            statistics=stats, requests=client.responses, discovered_urls=list(discovered.values()), outcomes=outcomes)
        probe.note = 'Sofia-only bounded catalogue crawl; sale/rent sample interleaved; no missing-offer retirement.'
        probe.save()
        complete = stats['discovery_complete'] if discover_only else stats['detail_complete']
        success = complete and not stats['errors'] and not stats['blocked'] and not stats['image_errors']
        run.status = 'ok' if success else ('partial' if stats['discovered'] else 'failed')
        run.finished_at = timezone.now()
        run.sources_ok, run.sources_dead = int(success), int(bool(stats['blocked'] or stats['errors']))
        run.offers_total, run.offers_new, run.offers_changed = stats['stored'], stats['new'], stats['updated']
        run.log = json.dumps(dict(stats=stats, outcomes=outcomes, probe_id=probe.pk), ensure_ascii=False)
        run.save()
        settings.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        (settings.RUNS_DIR / f'{adapter.slug}-sofia-{run.pk}.json').write_text(run.log, encoding='utf-8')
        emit(json.dumps(dict(run=run.pk, status=run.status, **stats), ensure_ascii=False))
    return run, stats
