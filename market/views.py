# -*- coding: utf-8 -*-
"""The public search. One card per real thing.

The rule that shapes every filter here, inherited from broker-crm and kept
because agency data is patchy in exactly the places a filter bites:

    A missing value never removes a listing. It costs confidence, not score.

A flat whose floor the agency never published still appears in a search that
does not filter on floor, and still appears -- marked -- in one that does. The
portals drop those rows silently, which is a large part of why their results
cannot be trusted to be the whole market.
"""
import re
from collections import Counter

from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404, render

from sourcing.models import Agency, Offer
from market.geography import siblings_for
from market.api import _scope

PER_PAGE = 24

SORTS = {
    'newest': ('-first_seen', 'Най-нови'),
    'price_asc': ('price_eur', 'Цена ↑'),
    'price_desc': ('-price_eur', 'Цена ↓'),
    'area_desc': ('-area_m2', 'Площ ↓'),
    'sqm_asc': ('price_per_m2', '€/м² ↑'),
}

# The property kinds agencies actually publish, grouped: the same flat is
# "двустаен" at one agency and "apartment" at another.
KIND_GROUPS = {
    'apartment': ('едностаен', 'двустаен', 'тристаен', 'многостаен', 'мезонет',
                  'apartment', 'maisonette', 'penthouse', 'студио'),
    'house': ('къща', 'вила', 'house', 'villa'),
    'land': ('парцел', 'земеделска земя', 'land'),
    'commercial': ('офис', 'магазин', 'заведение', 'хотел', 'office', 'shop', 'hotel'),
}
KIND_LABELS = {'apartment': 'Апартаменти', 'house': 'Къщи',
               'land': 'Парцели', 'commercial': 'Бизнес имоти'}


def _live():
    return (Offer.objects.filter(is_active=True)
            .exclude(listing_url='')
            .select_related('agency', 'geo__city', 'geo__neighbourhood')
            .prefetch_related('images'))


def _apply(request, queryset):
    """Filters. Each one keeps rows whose value is unknown -- see module docstring."""
    get = request.GET.get
    queryset = _scope(request, queryset)
    applied = {}

    deal = get('deal') or 'sale'
    queryset = queryset.filter(deal_type=deal)
    applied['deal'] = deal

    query = (get('q') or '').strip()
    if query:
        queryset = queryset.filter(
            Q(title__icontains=query) | Q(location__icontains=query)
            | Q(notes__icontains=query))
        applied['q'] = query

    kind = get('kind')
    if kind in KIND_GROUPS:
        clause = Q()
        for token in KIND_GROUPS[kind]:
            clause |= Q(property_kind__icontains=token) | Q(title__icontains=token)
        queryset = queryset.filter(clause)
        applied['kind'] = kind

    for field, param in (('price_eur', 'price'), ('area_m2', 'area')):
        low, high = get(f'{param}_min'), get(f'{param}_max')
        if low and low.isdigit():
            # `| isnull` is the confidence rule in SQL: an unpriced flat is not
            # evidence that it is over budget, so it stays and is labelled.
            queryset = queryset.filter(Q(**{f'{field}__gte': int(low)})
                                       | Q(**{f'{field}__isnull': True}))
            applied[f'{param}_min'] = low
        if high and high.isdigit():
            queryset = queryset.filter(Q(**{f'{field}__lte': int(high)})
                                       | Q(**{f'{field}__isnull': True}))
            applied[f'{param}_max'] = high

    beds = get('beds')
    if beds and beds.isdigit():
        queryset = queryset.filter(Q(bedrooms__gte=int(beds)) | Q(bedrooms__isnull=True))
        applied['beds'] = beds

    agency = get('agency')
    if agency:
        queryset = queryset.filter(agency__slug=agency)
        applied['agency'] = agency

    if get('with_photo'):
        queryset = queryset.filter(images__isnull=False).distinct()
        applied['with_photo'] = '1'

    return queryset, applied


def search(request):
    base = _live()
    queryset, applied = _apply(request, base)

    sort = request.GET.get('sort', 'newest')
    order, _label = SORTS.get(sort, SORTS['newest'])
    if sort in ('price_asc', 'sqm_asc'):
        queryset = queryset.filter(**{f'{order}__isnull': False})
    queryset = queryset.order_by(order, '-id')

    page = Paginator(queryset, PER_PAGE).get_page(request.GET.get('page'))

    # Facets are counted over the whole live set for this deal type, so a
    # filter never hides the option that would widen it again.
    deal_set = base.filter(deal_type=applied['deal'])
    facets = {
        'agencies': (deal_set.values('agency__slug', 'agency__name')
                     .annotate(n=Count('id')).order_by('-n')),
        'kinds': [(key, KIND_LABELS[key], _kind_count(deal_set, key))
                  for key in KIND_GROUPS],
        'total': deal_set.count(),
    }

    querystring = request.GET.copy()
    querystring.pop('page', None)

    return render(request, 'market/search.html', {
        'page_obj': page, 'applied': applied, 'facets': facets,
        'sorts': SORTS, 'sort': sort,
        'querystring': querystring.urlencode(),
        'stats': _stats(),
    })


def _kind_count(queryset, key):
    clause = Q()
    for token in KIND_GROUPS[key]:
        clause |= Q(property_kind__icontains=token) | Q(title__icontains=token)
    return queryset.filter(clause).count()


def offer(request, pk):
    row = get_object_or_404(_live(), pk=pk)
    # Other agencies advertising what looks like the same flat. dup_group is
    # the crawler's cross-agency cluster key; the price spread between them is
    # the most interesting number on this page.
    siblings = []
    if row.dedup_key:
        siblings = list(siblings_for(row, _live())[:PER_PAGE])
    prices = [o.price_eur for o in [row] + siblings if o.price_eur]
    spread = (max(prices) - min(prices)) if len(prices) > 1 else None
    return render(request, 'market/offer.html', {
        'offer': row, 'siblings': siblings, 'spread': spread,
        'stats': _stats(),
    })


def agencies(request):
    rows = (Agency.objects.annotate(
        live=Count('offers', filter=Q(offers__is_active=True))
    ).filter(live__gt=0).order_by('-live'))
    return render(request, 'market/agencies.html',
                  {'agencies': rows, 'stats': _stats()})


def _stats():
    live = Offer.objects.filter(is_active=True)
    return {
        'offers': live.count(),
        'agencies': Agency.objects.filter(offers__is_active=True).distinct().count(),
        'with_photo': live.filter(images__isnull=False).distinct().count(),
    }
