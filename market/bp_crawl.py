"""Bounded, sequential Sofia crawl using verified Bulgarian Properties pages.

No missing-offer retirement: a discovery count is not proof of unit coverage.
Numeric AD reference is source identity; prices and URL category names are not.
"""
import hashlib
import json
import random
import time
import uuid
from decimal import Decimal
from urllib.robotparser import RobotFileParser

from django.conf import settings
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from market import bulgarian_properties as parser, images
from market.models import City, SiteProbe
from market.source_http import SourceBlocked, SourceClient
from sourcing.models import Agency, CrawlRun, Offer, OfferHistory, OfferImage
from sourcing.web.store import TRACKED, _differs, fingerprint

SLUG = 'bulgarian-properties'
# Session lock prevents two instances of this adapter hitting the host together.
HOST_LOCK = 724003991


@transaction.atomic
def save_offer(agency, parsed, evidence, *, identity_query=None):
    """Preserve old identities and good fields, with complete price history."""
    # Serialize source identity lookup even when another caller stores directly.
    Agency.objects.select_for_update().get(pk=agency.pk)
    record = dict(parsed['record'])
    if record.get('price_eur') is not None and record.get('area_m2'):
        per_m2 = record['price_eur'] / record['area_m2']
        if per_m2 <= Decimal('99999999.99'):
            record['price_per_m2'] = per_m2
    ref = record['ref']
    identity_query = identity_query if identity_query is not None else (
        Q(ref=ref) | Q(ref__iregex=rf'(^|[^0-9]){ref}$') |
        Q(listing_url__contains=f'/AD{ref}BG_'))
    matches = list(Offer.objects.select_for_update().filter(agency=agency, source='web').filter(identity_query)[:2])
    if len(matches) > 1:
        raise parser.ParseError(f'Ambiguous existing source reference {ref}')
    today = timezone.localdate()
    if not matches:
        offer = Offer.objects.create(agency=agency, source='web',
            fingerprint=fingerprint(record['listing_url']), source_url=record['listing_url'],
            first_seen=today, last_seen=today, last_changed=today,
            evidence=evidence, identity_strength='source-ref', **record)
        OfferHistory.objects.create(offer=offer, event='new', changed_on=today)
        return offer, {'new': 1, 'updated': 0, 'price_changes': 0, 'returned': 0}
    offer = matches[0]
    missing = [key for key, value in record.items() if value is None or value == '']
    # Missing values mean uncertainty, never a price reset or a fake change.
    record = {key: value for key, value in record.items() if key not in missing}
    if 'price_eur' in missing:
        record.pop('price_raw', None)
    evidence = {**evidence, 'missing_fields': missing}
    changes = [(key, getattr(offer, key), record[key]) for key in TRACKED
               if key in record and _differs(getattr(offer, key), record[key])]
    returned = not offer.is_active
    for key, value in record.items():
        setattr(offer, key, value)
    # Recompute derived fields from the retained, complete record.
    from crm.dedup import dedup_key
    offer.dedup_key = dedup_key({key: getattr(offer, key) for key in
        ('title', 'location', 'area_m2', 'bedrooms', 'floor', 'property_kind', 'deal_type')})
    if offer.price_eur is not None and offer.area_m2:
        per_m2 = offer.price_eur / offer.area_m2
        offer.price_per_m2 = per_m2 if per_m2 <= Decimal('99999999.99') else None
    price_changes = 0
    for key, before, after in changes:
        if key == 'price_eur':
            price_changes += 1
            offer.prev_price_eur = before
        OfferHistory.objects.create(offer=offer, event='changed', field=key,
            old_value='' if before is None else str(before),
            new_value='' if after is None else str(after), changed_on=today)
    if returned:
        OfferHistory.objects.create(offer=offer, event='returned', changed_on=today)
    if changes or returned:
        offer.last_changed = today
    offer.source_url = record['listing_url']
    offer.last_seen = today
    offer.times_seen += 1
    offer.is_active = True
    offer.evidence = evidence
    offer.save()
    return offer, {'new': 0, 'updated': int(bool(changes)),
                   'price_changes': price_changes, 'returned': int(returned)}


def save_image(offer, url, client):
    if offer.images.exists():
        return False
    # Development units share the agency's development cover. Reuse the
    # verified downloaded file instead of fetching it once for every unit.
    existing = OfferImage.objects.filter(offer__agency=offer.agency, source_url=url).first()
    if existing and (settings.DATA_DIR / existing.local_path).is_file():
        _, created = OfferImage.objects.get_or_create(offer=offer, sha256=existing.sha256,
            defaults=dict(local_path=existing.local_path, source_url=url, position=0))
        Offer.objects.filter(pk=offer.pk).update(image_count=offer.images.count())
        return created
    response = client.get(url, binary=True)
    blob = response.get('blob', b'')
    if not response['ok'] or len(blob) < images.MIN_BYTES or not images.looks_like_image(blob):
        raise ValueError('Main image did not return a valid photograph')
    digest = hashlib.sha256(blob).hexdigest()
    folder = images.store_dir(offer.agency.slug)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (digest[:24] + images.extension_for(blob, url))
    if not path.exists():
        path.write_bytes(blob)
    _, created = OfferImage.objects.get_or_create(offer=offer, sha256=digest, defaults={
        'local_path': str(path.relative_to(settings.DATA_DIR)), 'source_url': url, 'position': 0})
    Offer.objects.filter(pk=offer.pk).update(image_count=offer.images.count())
    return created


def crawl(*, limit=None, max_pages=100, discover_only=False, no_images=False,
          sample_seed=None, emit=print, client=None):
    if limit is not None and limit <= 0 or max_pages <= 0:
        raise CommandError('limit and max-pages must be positive')
    agency = Agency.objects.filter(slug=SLUG).first()
    city = City.objects.filter(slug='sofia').first()
    if not agency or not city:
        raise CommandError('Existing Bulgarian Properties agency and seeded Sofia city are required')
    if agency.crawl_opt_out:
        raise CommandError('Agency has opted out of crawling')
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [HOST_LOCK])
        if not cursor.fetchone()[0]:
            raise CommandError('Bulgarian Properties crawl is already running')
    try:
        return _crawl(agency, city, limit, max_pages, discover_only, no_images, sample_seed, emit, client)
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(%s)', [HOST_LOCK])


def _crawl(agency, city, limit, max_pages, discover_only, no_images, sample_seed, emit, client):
    started = time.monotonic()
    client = client or SourceClient([parser.HOST, 'static.bulgarianproperties.com'])
    run = CrawlRun.objects.create(kind='sites', run_date=timezone.localdate(), status='running')
    probe = SiteProbe.objects.create(city=city, agency_slug=SLUG, agency_name=agency.name,
        website=f'https://{parser.HOST}/', run_id=uuid.uuid4().hex[:12], run_started=run.started_at,
        status='no_listings', final_url=parser.CATALOGUE)
    stats = dict(agency=SLUG, city='sofia', discovered=0, fetched=0, stored=0,
        new=0, updated=0, price_changes=0, returned=0, marked_inactive=0,
        errors=0, blocked=0, images=0, image_errors=0, project=0, outside_city=0,
        unavailable=0, pages=0, advertised=0, discovery_complete=False,
        detail_complete=False, discover_only=discover_only, limit=limit, max_pages=max_pages,
        sample_seed=sample_seed)
    entries, discovered, stored = [], {}, []
    robots = RobotFileParser()
    respect = getattr(settings, 'CRAWL_RESPECT_ROBOTS', False)
    def get(url, **kwargs):
        if respect and not robots.can_fetch(settings.CRAWL_USER_AGENT_BOT, url):
            raise SourceBlocked(f'robots policy excludes {url}')
        response = client.get(url, **kwargs)
        if not response['ok']:
            raise parser.ParseError(f'HTTP {response["status"]} at {url}')
        return response
    try:
        response = client.get(f'https://{parser.HOST}/robots.txt')
        probe.robots_found = response['ok']
        if response['ok']:
            robots.parse(response['body'].splitlines())
            probe.robots_disallow = [line.split(':', 1)[1].strip() for line in response['body'].splitlines()
                                    if line.lower().startswith('disallow:')]
            probe.sitemaps = robots.site_maps() or []
            probe.robots_blocks_listings = not robots.can_fetch(settings.CRAWL_USER_AGENT_BOT, parser.CATALOGUE)
        elif respect:
            raise SourceBlocked('Unable to verify robots policy')
        url, visited = parser.CATALOGUE, set()
        while url and stats['pages'] < max_pages:
            if url in visited:
                raise parser.ParseError('Repeated pagination URL')
            visited.add(url)
            response = get(url)
            page = parser.catalogue(response['body'], url)
            probe.meta_charset = response.get('encoding', '')
            probe.http_status = response['status']
            stats['pages'] += 1
            if stats['pages'] == 1:
                stats['advertised'] = page['total']
            elif page['total'] != stats['advertised']:
                raise parser.ParseError('Catalogue count changed during discovery; repeat later')
            new_rows = {row['ref']: row for row in page['rows'] if row['ref'] not in discovered}
            if page['rows'] and not new_rows:
                raise parser.ParseError('Pagination repeated previously discovered listings')
            discovered.update(new_rows)
            stats['discovered'] = len(discovered)
            emit(f'BP Sofia: page {stats["pages"]}, {len(discovered)}/{stats["advertised"]} URLs')
            url = page['next_url']
        stats['discovery_complete'] = not url and len(discovered) == stats['advertised']
        if not url and not stats['discovery_complete']:
            raise parser.ParseError('Pagination ended before advertised count was reached')
        probe.status = 'ok'
        probe.listing_pattern = r'AD\d+BG_'
        if not discover_only:
            selected = list(discovered.values())
            if sample_seed is not None:
                random.Random(sample_seed).shuffle(selected)
            selected = selected[:limit]
            for row in selected:
                stats['fetched'] += 1
                try:
                    response = get(row['url'])
                    parsed = parser.detail(response['body'], row['url'])
                    outcome = parsed['outcome']
                    if outcome != 'offer':
                        stats[outcome] += 1
                        entries.append(parsed)
                        if outcome == 'unavailable':
                            from market.sofia_crawl import mark_verified_unavailable
                            stats['marked_inactive'] += mark_verified_unavailable(agency, parsed,
                                dict(run=run.pk, source_url=row['url'], fetched_at=timezone.now().isoformat(),
                                     body_sha256=hashlib.sha256(response['body'].encode()).hexdigest()))
                        if outcome == 'project' and limit is None:
                            from market.bp_units import price_list_url, units
                            price_url = price_list_url(response['body'], row['url'])
                            if price_url:
                                try:
                                    unit_response = get(price_url)
                                    unit_rows = units(unit_response['body'], response['body'], row['url'])
                                    stats['projects_expanded'] = stats.get('projects_expanded', 0) + 1
                                    stats['units_discovered'] = stats.get('units_discovered', 0) + len(unit_rows)
                                    for unit in unit_rows:
                                        if unit['outcome'] != 'offer':
                                            stats['units_unavailable'] = stats.get('units_unavailable', 0) + 1
                                            entries.append(unit)
                                            if unit['outcome'] == 'unavailable':
                                                from market.sofia_crawl import mark_verified_unavailable
                                                stats['marked_inactive'] += mark_verified_unavailable(agency, unit,
                                                    dict(run=run.pk, source_url=price_url, source_ref=unit['ref'],
                                                        fetched_at=timezone.now().isoformat(),
                                                        body_sha256=hashlib.sha256(unit_response['body'].encode()).hexdigest()))
                                            continue
                                        unit_evidence = dict(crawler='crawl_live', adapter='bulgarian-properties-units-v1',
                                            city='sofia', run=run.pk, source_ref=unit['ref'], source_url=unit['url'],
                                            fetched_at=timezone.now().isoformat(), method='own-public-price-list-row',
                                            price_list_url=price_url, quoted_price_text=unit['record']['price_raw'],
                                            fields=unit['fields'], image_scope='development',
                                            body_sha256=hashlib.sha256(unit_response['body'].encode()).hexdigest())
                                        offer, changes = save_offer(agency, unit, unit_evidence)
                                        for key, count in changes.items():
                                            stats[key] += count
                                        stats['stored'] += 1
                                        stats['units_stored'] = stats.get('units_stored', 0) + 1
                                        stored.append(offer.pk)
                                        entries.append(dict(ref=unit['ref'], url=unit['url'], outcome='stored',
                                            offer_id=offer.pk, project_unit=True, **changes))
                                        if not no_images and unit['images']:
                                            try:
                                                stats['images'] += int(save_image(offer, unit['images'][0], client))
                                            except SourceBlocked:
                                                raise
                                            except (ValueError, OSError) as exc:
                                                stats['image_errors'] += 1
                                                entries.append(dict(ref=unit['ref'], image_error=str(exc)[:300]))
                                    emit(f'BP Sofia: project {row["ref"]}, {len(unit_rows)} units checked; {stats.get("units_stored", 0)} units stored')
                                except SourceBlocked:
                                    raise
                                except (ValueError, OSError) as exc:
                                    stats['errors'] += 1
                                    entries.append(dict(ref=row['ref'], project_unit_error=str(exc)[:300]))
                        continue
                    evidence = {'crawler': 'crawl_live', 'adapter': 'bulgarian-properties-v1',
                        'city': 'sofia', 'run': run.pk, 'source_ref': parsed['ref'],
                        'source_url': parsed['url'], 'fetched_at': timezone.now().isoformat(),
                        'body_sha256': hashlib.sha256(response['body'].encode()).hexdigest(),
                        'encoding': response.get('encoding', ''), 'method': 'own-dom-and-jsonld',
                        'quoted_price_text': parsed['record']['price_raw'],
                        'image_sources': parsed['images'][:1]}
                    offer, changes = save_offer(agency, parsed, evidence)
                    for key, count in changes.items():
                        stats[key] += count
                    stats['stored'] += 1
                    stored.append(offer.pk)
                    entries.append({'ref': parsed['ref'], 'url': parsed['url'],
                                    'outcome': 'stored', 'offer_id': offer.pk, **changes})
                    if not no_images and parsed['images']:
                        try:
                            stats['images'] += int(save_image(offer, parsed['images'][0], client))
                        except SourceBlocked:
                            raise
                        except (ValueError, OSError) as exc:
                            stats['image_errors'] += 1
                            entries.append({'ref': parsed['ref'], 'image_error': str(exc)[:300]})
                except SourceBlocked:
                    raise
                except (ValueError, OSError) as exc:
                    stats['errors'] += 1
                    entries.append({'ref': row['ref'], 'url': row['url'], 'error': str(exc)[:300]})
                emit(f'BP Sofia: fetched {stats["fetched"]}, stored {stats["stored"]}, errors {stats["errors"]}')
            stats['detail_complete'] = stats['discovery_complete'] and stats['fetched'] == len(discovered) and not stats['errors']
    except SourceBlocked as exc:
        stats['blocked'] += 1
        probe.status = 'blocked'
        entries.append({'error': str(exc)[:300]})
    except Exception as exc:
        # Persist failure evidence, including unexpected errors. Never retire data.
        stats['errors'] += 1
        probe.status = 'http_error'
        entries.append({'error': f'{type(exc).__name__}: {exc}'[:300]})
    finally:
        stats['seconds'] = round(time.monotonic() - started, 2)
        qs = Offer.objects.filter(pk__in=stored)
        denominator = len(stored)
        def pct(count):
            return round(count * 100 / denominator, 1) if denominator else None
        stats['quality'] = {'sample_size': denominator,
            'price_fill_pct': pct(qs.filter(price_eur__isnull=False).count()),
            'area_fill_pct': pct(qs.filter(area_m2__isnull=False).count()),
            'location_fill_pct': pct(qs.exclude(location='').count()),
            'neighbourhood_resolved_pct': pct(qs.filter(geo__neighbourhood__isnull=False).count()),
            'image_fill_pct': pct(qs.filter(images__isnull=False).distinct().count())}
        probe.strategy = {'adapter': 'bulgarian-properties-v1', 'catalogue': parser.CATALOGUE,
            'pagination': 'follow actual next link; index1.html is page 2',
            'identity': 'agency + numeric AD reference', 'retirement_enabled': False,
            'statistics': stats, 'requests': client.responses,
            'discovered_urls': list(discovered.values()), 'outcomes': entries}
        probe.note = 'Sofia city adapter; projects and unavailable listings skipped; no missing-offer retirement.'
        probe.save()
        complete = stats['discovery_complete'] if discover_only else stats['detail_complete']
        success = complete and not stats['errors'] and not stats['blocked']
        run.status = 'ok' if success else ('partial' if stats['discovered'] else 'failed')
        run.finished_at = timezone.now()
        run.sources_ok = int(success)
        run.sources_dead = int(bool(stats['blocked'] or stats['errors']))
        run.offers_total, run.offers_new, run.offers_changed = stats['stored'], stats['new'], stats['updated']
        run.log = json.dumps({'stats': stats, 'outcomes': entries, 'probe_id': probe.pk}, ensure_ascii=False)
        run.save()
        folder = settings.RUNS_DIR
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f'bp-sofia-{run.pk}.json').write_text(run.log, encoding='utf-8')
        emit(json.dumps({'run': run.pk, 'status': run.status, **stats}, ensure_ascii=False))
    return run, stats
