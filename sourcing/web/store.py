# -*- coding: utf-8 -*-
"""Writing a crawled listing into the offer table.

The listing URL is the identity, hashed into `fingerprint`. That single choice
is what makes a second pass cheap -- the crawler asks the database which URLs it
already holds and never fetches those pages again -- and what makes a liveness
check possible later, because every row can be traced back to the page it came
from.

Nothing here merges anything. A flat that three agencies advertise becomes three
rows, exactly as the sheets already do it. Recognising those three as one flat
is the dedup pass's job, and it runs over stored rows, not over a crawl.
"""
import hashlib
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from sourcing.models import Offer, OfferHistory, OfferSource

# Changing any of these is a real change worth a history line. `last_seen`
# moving is not.
TRACKED = ('price_eur', 'bedrooms', 'area_m2', 'floor', 'title', 'location',
           'property_kind', 'deal_type', 'status')


def fingerprint(url):
    return 'web' + hashlib.sha1(url.encode('utf-8')).hexdigest()[:13]


def known_urls(agency):
    """The listing URLs already stored for this agency -> fingerprint.

    Handed to the crawler before it fetches anything, so a second run costs one
    sitemap request per site instead of six thousand page requests.
    """
    return dict(Offer.objects.filter(agency=agency, source=OfferSource.WEB)
                .exclude(listing_url='')
                .values_list('listing_url', 'fingerprint'))


def _differs(before, after):
    """Has this field really moved?

    Postgres hands back Decimal('50000.00') where the crawler produced 50000,
    and comparing those as strings reported every listing as changed on every
    run -- writing a history line and a false previous price each morning.
    """
    if before is None and after is None:
        return False
    if before is None or after is None:
        return True
    if isinstance(before, Decimal) or isinstance(after, Decimal):
        try:
            return Decimal(str(before)) != Decimal(str(after))
        except (InvalidOperation, ValueError):
            pass
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return abs(float(before) - float(after)) > 1e-9
    return str(before) != str(after)


def store(agency, record, evidence, today=None):
    """Upsert one crawled listing. Returns 'new', 'changed' or 'same'."""
    today = today or timezone.localdate()
    key = fingerprint(record['listing_url'])
    existing = Offer.objects.filter(fingerprint=key).first()

    # Only live offers are stored. A catalogue should not contain a sold flat
    # at all, but a stale badge slips through now and then -- it is dropped on
    # the spot rather than kept as a row nobody can ever act on.
    if record.get('status') == 'sold':
        if existing is not None:
            Offer.objects.filter(pk=existing.pk).update(
                is_active=False, status='sold', last_changed=today)
            return 'sold'
        return 'sold'

    if existing is None:
        Offer.objects.create(
            fingerprint=key, agency=agency, source=OfferSource.WEB,
            first_seen=today, last_seen=today, is_active=True,
            evidence=evidence, source_url=record['listing_url'][:700],
            **record)
        return 'new'

    changes = []
    for field in TRACKED:
        if field not in record:
            continue
        before, after = getattr(existing, field), record[field]
        if not _differs(before, after):
            continue
        changes.append((field, before, after))

    for field, value in record.items():
        setattr(existing, field, value)
    existing.last_seen = today
    existing.is_active = True
    existing.evidence = evidence
    existing.times_seen += 1
    if changes:
        # The previous asking price is what makes "dropped €4 000 since Tuesday"
        # possible, so it is kept on the row rather than only in the log.
        for field, before, after in changes:
            if field == 'price_eur' and before is not None:
                existing.prev_price_eur = before
        existing.last_changed = today
    existing.save()

    for field, before, after in changes:
        OfferHistory.objects.create(
            offer=existing, event=OfferHistory.CHANGED, field=field,
            old_value=str(before or ''), new_value=str(after or ''), changed_on=today)
    return 'changed' if changes else 'same'


def retire_missing(agency, seen_urls, today=None):
    """Listings the site no longer publishes are withdrawn, not deleted.

    A row that disappears is still the flat a client was shown last week, and
    the candidate that points at it must keep resolving.
    """
    today = today or timezone.localdate()
    stale = (Offer.objects.filter(agency=agency, source=OfferSource.WEB, is_active=True)
             .exclude(listing_url__in=list(seen_urls)))
    gone = list(stale.values_list('id', 'listing_url'))
    stale.update(is_active=False, last_changed=today)
    for offer_id, _url in gone:
        OfferHistory.objects.create(offer_id=offer_id, event=OfferHistory.REMOVED,
                                    field='', old_value='', new_value='', changed_on=today)
    return len(gone)
