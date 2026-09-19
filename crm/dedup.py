# -*- coding: utf-8 -*-
"""Recognising the same flat twice.

Two guarantees, and they need different machinery:

1. Never re-propose what this client already saw -- a database constraint on
   (client, offer), plus an exclusion set on every key already spent.
2. Never show one flat under two agencies' names -- which the crawler's own
   `dup_group` cannot do. Measured on the live data, exactly **2** dup_group
   clusters span more than one agency out of 1,135 offers, because the hash
   demands identical titles and the agencies write "Гранд Камелия", "Grand
   Kamelia" and "GRAND KAMELIA".

Hence two passes: the crawler's exact key where it fires, and a Postgres
trigram search where it does not. The second pass deliberately does **not**
merge anything. It flags, and lets the broker see both -- because the flag is
worth money to her ("same flat, €5,000 cheaper at Eurometr") and because
auto-collapsing on a fuzzy signal hides real inventory.
"""
import hashlib
import re

from django.db import connection

from crm.features import norm

# Below this, trigram similarity starts pairing unrelated complexes that merely
# share a common Bulgarian word ("Морски", "Гранд", "Резиденс").
TRIGRAM_THRESHOLD = 0.55
AREA_TOLERANCE_M2 = 3.0
PRICE_TOLERANCE_PCT = 3.0

_STOPWORDS = {'комплекс', 'complex', 'апартамент', 'apartment', 'резиденс', 'residence',
              'квартира', 'flat', 'студио', 'studio',
              'kompleks', 'apartament', 'rezidens', 'kvartira', 'studio'}

# Official Bulgarian romanisation, plus the three Russian-only letters the
# Russian-language sheets use. Without this step the whole second dedup pass is
# dead weight: "Гранд Камелия" and "Grand Kamelia" are the same building written
# by two agencies, and as raw strings they share not one trigram. Folding both
# onto Latin gives 'grand kameliya' vs 'grand kamelia', which similarity() reads
# as a near-match.
_TRANSLIT = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ж': 'zh', 'з': 'z',
    'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p',
    'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch',
    'ш': 'sh', 'щ': 'sht', 'ъ': 'a', 'ь': 'y', 'ю': 'yu', 'я': 'ya',
    'ы': 'y', 'э': 'e', 'ё': 'e',
}


def translit(text):
    return ''.join(_TRANSLIT.get(ch, ch) for ch in text)


def title_norm(title):
    """The form the trigram index is built on: normalised and romanised."""
    words = [w for w in translit(norm(title)).split()
             if w not in _STOPWORDS and not w.isdigit()]
    return ' '.join(words)


def dedup_key(record):
    """Pass 1 -- the crawler's own clustering, recomputed.

    Mirrors normalize.dup_group(): location, a short title key, bedrooms, area
    rounded to 5 m², floor. Requires at least three known parts, so thin rows
    get no key rather than a meaningless one -- and a NULL key never collides,
    which is exactly right for a row we cannot cluster honestly.
    """
    existing = record.get('dup_group')
    if existing:
        return existing                      # agree with the crawler where it spoke

    location = norm(record.get('location') or '')
    title = title_norm(record.get('title') or '')[:24]
    bedrooms = record.get('bedrooms')
    area = record.get('area_m2')
    floor = record.get('floor')

    parts = [
        location,
        title,
        '' if bedrooms is None else str(bedrooms),
        '' if area is None else str(int(round(float(area) / 5.0) * 5)),
        '' if floor is None else str(floor),
    ]
    if sum(1 for p in parts if p) < 3:
        return ''
    return hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()[:16]


def find_possible_duplicates(offer, among_ids=None):
    """Pass 2 -- fuzzy cross-agency siblings of `offer`.

    Same resort, same bedroom count, area within 3 m², price within 3%, a
    different agency, and a similar enough name. Returns rows, never merges.
    """
    if not offer.title_norm or not offer.location:
        return []

    sql = """
        SELECT o.id, o.agency_id, a.name AS agency_name, o.title, o.price_eur,
               o.area_m2, o.floor, similarity(o.title_norm, %(title)s) AS sim
        FROM sourcing_offer o
        JOIN sourcing_agency a ON a.id = o.agency_id
        WHERE o.id <> %(id)s
          AND o.is_active
          AND o.agency_id <> %(agency)s
          AND o.location = %(location)s
          AND o.deal_type = %(deal)s
          AND (%(beds)s::int IS NULL OR o.bedrooms IS NULL OR o.bedrooms = %(beds)s::int)
          AND (%(area)s::numeric IS NULL OR o.area_m2 IS NULL
               OR abs(o.area_m2 - %(area)s::numeric) <= %(area_tol)s)
          AND (%(price)s::numeric IS NULL OR o.price_eur IS NULL
               OR abs(o.price_eur - %(price)s::numeric)
                   <= %(price)s::numeric * %(price_tol)s / 100.0)
          AND similarity(o.title_norm, %(title)s) >= %(threshold)s
        ORDER BY sim DESC, o.price_eur ASC
        LIMIT 5
    """
    params = {
        'id': offer.pk, 'agency': offer.agency_id, 'location': offer.location,
        'deal': offer.deal_type, 'title': offer.title_norm,
        'beds': offer.bedrooms, 'area': offer.area_m2, 'price': offer.price_eur,
        'area_tol': AREA_TOLERANCE_M2, 'price_tol': PRICE_TOLERANCE_PCT,
        'threshold': TRIGRAM_THRESHOLD,
    }
    with connection.cursor() as cur:
        cur.execute(sql, params)
        columns = [c[0] for c in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def also_at_payload(duplicates, reference_price):
    """Compact the sibling rows into what the candidate card shows."""
    out = []
    for row in duplicates:
        delta = None
        if row['price_eur'] is not None and reference_price is not None:
            delta = float(row['price_eur']) - float(reference_price)
        out.append({
            'offer_id': row['id'],
            'agency': row['agency_name'],
            'title': row['title'],
            'price_eur': float(row['price_eur']) if row['price_eur'] is not None else None,
            'price_delta': delta,
            'similarity': round(float(row['sim']), 3),
        })
    return out
