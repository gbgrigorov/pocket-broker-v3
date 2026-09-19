# -*- coding: utf-8 -*-
"""Write a day's parse into the database: insert, diff, retire.

A port of the upstream sync_offers() to the ORM, preserving its three
hard-earned behaviours:

* **Weak-identity rekeying.** A thin row's fingerprint includes its price, so a
  repriced one arrives looking like a stranger while the original looks gone.
  Matching on `weak_core` claims the existing row instead of minting a new offer
  and retiring a good one -- but only when the match is unambiguous, because two
  candidates mean the sheet genuinely holds two similar flats.
* **Change tracking on a fixed field list**, so a price cut is history rather
  than a silent overwrite.
* **Retirement scoped to sources we actually re-read.** An offer missing from a
  sheet that failed to download is not gone; it is unknown.

What we add: location salvage, feature resolution, the romanised title, and our
own dedup key -- all computed once here rather than at query time.
"""
import json
import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from crm import features as feature_lib
from crm.dedup import dedup_key, title_norm
from sourcing import salvage
from sourcing.models import Offer, OfferHistory

log = logging.getLogger(__name__)

# Fields whose change is worth recording. Mirrors the crawler's TRACKED list.
TRACKED = ['price_eur', 'status', 'commission_value', 'commission_raw', 'maintenance_eur',
           'area_m2', 'floor', 'bedrooms', 'title', 'location', 'view', 'furnished',
           'documents', 'notes', 'photos_url']

# Record key -> model field. Only the ones that differ in name or need care.
DECIMAL_FIELDS = ('price_eur', 'price_per_m2', 'area_m2', 'commission_value',
                  'maintenance_eur', 'maintenance_per_m2')
INT_FIELDS = ('bedrooms', 'floor', 'source_row')
TEXT_FIELDS = ('ref', 'title', 'location', 'location_raw', 'price_raw', 'type_raw',
               'property_kind', 'commission_kind', 'commission_raw', 'commission_note',
               'maintenance_raw', 'view', 'documents', 'status', 'notes', 'ready_date',
               'source_tab', 'weak_core', 'dup_group', 'identity_strength', 'deal_type')
URL_FIELDS = ('listing_url', 'photos_url', 'video_url')

MAX_LENGTHS = {
    'ref': 80, 'title': 400, 'location': 120, 'location_raw': 300, 'price_raw': 120,
    'type_raw': 200, 'property_kind': 40, 'commission_kind': 20, 'commission_raw': 200,
    'commission_note': 400, 'maintenance_raw': 200, 'view': 300, 'documents': 200,
    'status': 40, 'ready_date': 80, 'source_tab': 120, 'weak_core': 300,
    'dup_group': 32, 'identity_strength': 20, 'deal_type': 10,
    'listing_url': 700, 'photos_url': 700, 'video_url': 700,
}


def _dec(value):
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _int(value):
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _text(value, limit):
    if value is None:
        return ''
    return str(value).strip()[:limit]


def _compare(value):
    """Compare the way the column stores it, so no-op runs record no changes."""
    if value is None:
        return None
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, Decimal):
        return format(value.normalize(), 'f')
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def build_payload(record, agency):
    """One parsed record -> the model field values it maps onto."""
    salvage.salvage(record)

    payload = {'agency': agency, 'source': 'sheet'}
    for field in TEXT_FIELDS:
        payload[field] = _text(record.get(field), MAX_LENGTHS.get(field, 400))
    for field in URL_FIELDS:
        payload[field] = _text(record.get(field), MAX_LENGTHS[field])
    for field in DECIMAL_FIELDS:
        payload[field] = _dec(record.get(field))
    for field in INT_FIELDS:
        payload[field] = _int(record.get(field))

    payload['furnished'] = record.get('furnished')
    payload['location_salvaged'] = bool(record.get('location_salvaged'))
    payload['data_flags'] = record.get('data_flags') or {}
    payload['raw'] = json.loads(json.dumps(record, ensure_ascii=False, default=str))
    payload['title_norm'] = title_norm(record.get('title') or '')[:400]
    payload['features'] = feature_lib.resolve(record)
    payload['dedup_key'] = dedup_key(record)[:32]
    if not payload['deal_type']:
        payload['deal_type'] = 'sale'
    return payload


@transaction.atomic
def sync_agency_offers(agency, records, run_date):
    """Insert / update / retire one agency's offers. Returns a counts dict."""
    existing = {o.fingerprint: o for o in Offer.objects.filter(agency=agency,
                                                               source='sheet')}
    weak_index = {}
    for fingerprint, offer in existing.items():
        if offer.is_active and offer.weak_core:
            weak_index.setdefault(offer.weak_core, []).append(fingerprint)

    seen, rekeyed = set(), {}
    counts = {'new': 0, 'changed': 0, 'unchanged': 0, 'gone': 0, 'rekeyed': 0}
    history = []

    for record in records:
        fingerprint = record.get('fingerprint')
        if not fingerprint or fingerprint in seen:
            continue                       # the same flat listed twice in one sheet
        seen.add(fingerprint)

        payload = build_payload(record, agency)
        offer = existing.get(fingerprint)

        if offer is None and record.get('weak_core'):
            candidates = [fp for fp in weak_index.get(record['weak_core'], [])
                          if fp not in seen and fp not in rekeyed]
            if len(candidates) == 1:
                old = candidates[0]
                offer = existing.pop(old)
                rekeyed[old] = fingerprint
                offer.fingerprint = fingerprint
                existing[fingerprint] = offer
                counts['rekeyed'] += 1

        if offer is None:
            offer = Offer(fingerprint=fingerprint, first_seen=run_date, last_seen=run_date,
                          last_changed=run_date, is_active=True, times_seen=1, **payload)
            offer.save()
            existing[fingerprint] = offer
            history.append(OfferHistory(offer=offer, event=OfferHistory.NEW,
                                        changed_on=run_date))
            counts['new'] += 1
            continue

        diffs = []
        for field in TRACKED:
            before, after = _compare(getattr(offer, field)), _compare(payload.get(field))
            if before != after and not (before is None and after is None):
                diffs.append((field, before, after))

        price_changed = any(d[0] == 'price_eur' for d in diffs)
        previous_price = offer.price_eur

        for field, value in payload.items():
            setattr(offer, field, value)
        offer.last_seen = run_date
        offer.is_active = True
        offer.times_seen += 1
        if diffs:
            offer.last_changed = run_date
            if price_changed:
                offer.prev_price_eur = previous_price
        offer.save()

        if diffs:
            counts['changed'] += 1
            for field, before, after in diffs:
                history.append(OfferHistory(offer=offer, event=OfferHistory.CHANGED,
                                            field=field, old_value=before or '',
                                            new_value=after or '', changed_on=run_date))
        else:
            counts['unchanged'] += 1

    # Anything active that this agency's sheet no longer lists. Only reached when
    # the sheet was read successfully -- the caller does not call us otherwise.
    for fingerprint, offer in existing.items():
        if fingerprint in seen or not offer.is_active:
            continue
        offer.is_active = False
        offer.last_changed = run_date
        offer.save(update_fields=['is_active', 'last_changed', 'updated_at'])
        history.append(OfferHistory(offer=offer, event=OfferHistory.REMOVED,
                                    field='is_active', old_value='1', new_value='0',
                                    changed_on=run_date))
        counts['gone'] += 1

    OfferHistory.objects.bulk_create(history, batch_size=500)
    agency.last_fetch = timezone.now()
    if counts['new'] or counts['changed'] or counts['gone']:
        agency.last_change = timezone.now()
    agency.save(update_fields=['last_fetch', 'last_change', 'updated_at'])
    return counts


@transaction.atomic
def retire_agency(agency, run_date, reason='merged'):
    """Withdraw every offer of an agency that turned out to be an alias."""
    rows = list(Offer.objects.filter(agency=agency, is_active=True))
    for offer in rows:
        offer.is_active = False
        offer.last_changed = run_date
        offer.save(update_fields=['is_active', 'last_changed', 'updated_at'])
    OfferHistory.objects.bulk_create([
        OfferHistory(offer=o, event=OfferHistory.MERGED, field='is_active',
                     old_value='1', new_value='0', changed_on=run_date) for o in rows])
    return len(rows)
