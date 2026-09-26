# -*- coding: utf-8 -*-
"""Public JSON API. Anonymous, read-only, no framework.

The rule that shapes every filter, inherited from broker-crm and kept because
agency data is patchy exactly where a filter bites:

    A missing value never removes a listing. It costs confidence, not score.

A flat whose floor the agency never published still appears in a search that
does not filter on floor, and still appears -- labelled unverified -- in one
that does. Portals drop those rows silently, which is a large part of why their
results cannot be trusted to be the whole market.
"""
from django.db.models import Count, F, Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from market import newbuild
from market.models import City, Neighbourhood
from market.geography import cluster_key, siblings_for
from sourcing.models import Agency, Offer

PER_PAGE = 24

SORTS = {
    'newest': '-first_seen',
    'price_asc': 'price_eur',
    'price_desc': '-price_eur',
    'area_desc': '-area_m2',
    'sqm_asc': 'price_per_m2',
}

# Sorting by a field is not a filter on it. An unpriced listing is still a real
# listing -- it goes to the end of a price sort rather than being dropped from
# the results or, as Postgres does by default on DESC, put at the front.
SORT_FIELDS = {
    'newest': ('first_seen', True),
    'price_asc': ('price_eur', False),
    'price_desc': ('price_eur', True),
    'area_desc': ('area_m2', True),
    'sqm_asc': ('price_per_m2', False),
}

KIND_GROUPS = {
    'apartment': ('апартамент', 'едностаен', 'двустаен', 'тристаен', 'четиристаен', 'многостаен', 'мезонет',
                  'студио', 'ателие', 'пентхаус', 'apartment', 'maisonette', 'penthouse', 'studio', 'atelier'),
    'house': ('къщ', 'вил', 'house', 'villa', 'cottage', 'mansion'),
    'land': ('парцел', 'земеделска земя', 'land', 'plot'),
    'commercial': ('офис', 'магазин', 'заведение', 'хотел',
                   'office', 'shop', 'hotel', 'beauty parlor', 'hair salon',
                   "children's area", 'dental office', 'промишлен', 'industrial', 'factory',
                   'storage room', 'warehouse', 'склад', 'производствен', 'индустриал',
                   'търговск', 'ресторант', 'кафене', 'бизнес', 'сграда', 'спа',
                   'restaurant', 'cafe', 'café', 'business', 'pharmacy', 'dry cleaning', 'beauty centre'),
}
KIND_LABELS = {'apartment': 'Апартаменти', 'house': 'Къщи',
               'land': 'Парцели', 'commercial': 'Бизнес имоти'}


def _live():
    return (Offer.objects.filter(is_active=True)
            .exclude(listing_url='')
            .select_related('agency', 'geo__city', 'geo__neighbourhood')
            .prefetch_related('images'))


def _scope(request, queryset):
    city = request.GET.get('city')
    if city:
        queryset = queryset.filter(geo__city__slug=city, geo__city__active=True)
    neighbourhood = request.GET.get('neighbourhood')
    if neighbourhood:
        if not city or not Neighbourhood.objects.filter(
                city__slug=city, slug=neighbourhood, active=True).exists():
            return queryset.none()
        queryset = queryset.filter(Q(geo__neighbourhood__slug=neighbourhood)
                                   | Q(geo__neighbourhood__isnull=True))
    return queryset


@require_GET
def cities(request):
    return JsonResponse({'cities': list(City.objects.filter(active=True).values('slug', 'name_bg', 'name_en'))})


@require_GET
def neighbourhoods(request):
    city = request.GET.get('city')
    if not city:
        return JsonResponse({'error': 'city is required'}, status=400)
    rows = Neighbourhood.objects.filter(city__slug=city, city__active=True, active=True)
    return JsonResponse({'neighbourhoods': list(rows.values('slug', 'name_bg', 'name_en'))})


# The phrases that mark new construction, as a database clause. Kept next to
# market/newbuild.py's patterns -- if one changes the other must.
NEWBUILD_TOKENS = ('ново строителство', 'новострой', 'в строеж', 'новопостроен',
                   'на зелено', 'до ключ', 'акт 14', 'акт 15', 'акт 16',
                   'акт14', 'акт15', 'акт16', 'new construction')


def _newbuild_clause():
    clause = Q()
    for token in NEWBUILD_TOKENS:
        clause |= (Q(title__icontains=token) | Q(notes__icontains=token))
    return clause


def _kind_clause(key):
    clause = Q()
    for token in KIND_GROUPS[key]:
        clause |= Q(property_kind__icontains=token) | Q(title__icontains=token)
    return clause


def _offer_text(offer):
    return ' '.join(filter(None, [offer.title, offer.notes, offer.location]))


def _serialise(offer):
    geo = getattr(offer, 'geo', None)
    image = offer.images.all()[:1]
    is_new, _key, stage = newbuild.describe(_offer_text(offer))
    known = [f for f in ('price_eur', 'area_m2', 'bedrooms', 'floor', 'location')
             if getattr(offer, f) not in (None, '')]
    return {
        'id': offer.pk,
        'title': offer.title,
        'price': float(offer.price_eur) if offer.price_eur else None,
        'price_per_m2': float(offer.price_per_m2) if offer.price_per_m2 else None,
        'area': float(offer.area_m2) if offer.area_m2 else None,
        'bedrooms': offer.bedrooms,
        'floor': offer.floor,
        'location': offer.location,
        'city': geo.city.slug if geo and geo.city_id else None,
        'city_name': geo.city.name_bg if geo and geo.city_id else None,
        'neighbourhood': geo.neighbourhood.slug if geo and geo.neighbourhood_id else None,
        'neighbourhood_name': geo.neighbourhood.name_bg if geo and geo.neighbourhood_id else None,
        'geo_confidence': float(geo.confidence) if geo else 0,
        'geo_matched_by': geo.matched_by if geo else 'unresolved',
        'cluster_key': cluster_key(offer),
        'kind': offer.property_kind,
        'deal': offer.deal_type,
        'url': offer.listing_url,
        'agency': {'slug': offer.agency.slug, 'name': offer.agency.name},
        'image': f'/media/{image[0].local_path}' if image else None,
        # How much of this listing the agency actually published. The card shows
        # it rather than hiding the gaps.
        'confidence': round(len(known) / 5, 2),
        'missing': [f for f in ('price_eur', 'area_m2', 'bedrooms', 'floor')
                    if getattr(offer, f) is None],
        'first_seen': offer.first_seen.isoformat() if offer.first_seen else None,
        'dedup_key': offer.dedup_key or '',
        # 41% of Varna stock is new construction and none of it was findable.
        # "Пред Акт 16" means NOT yet habitable -- see market/newbuild.py.
        'new_build': is_new,
        'stage': stage,
    }


@require_GET
def offers(request):
    get = request.GET.get
    queryset = _scope(request, _live())
    deal = get('deal') or 'sale'
    queryset = queryset.filter(deal_type=deal)

    query = (get('q') or '').strip()
    if query:
        queryset = queryset.filter(Q(title__icontains=query)
                                   | Q(location__icontains=query))

    kind = get('kind')
    if kind in KIND_GROUPS:
        queryset = queryset.filter(_kind_clause(kind))

    for field, param in (('price_eur', 'price'), ('area_m2', 'area')):
        low, high = get(f'{param}_min'), get(f'{param}_max')
        if low and low.isdigit():
            queryset = queryset.filter(Q(**{f'{field}__gte': int(low)})
                                       | Q(**{f'{field}__isnull': True}))
        if high and high.isdigit():
            queryset = queryset.filter(Q(**{f'{field}__lte': int(high)})
                                       | Q(**{f'{field}__isnull': True}))

    beds = get('beds')
    if beds and beds.isdigit():
        queryset = queryset.filter(Q(bedrooms__gte=int(beds))
                                   | Q(bedrooms__isnull=True))

    agency = get('agency')
    if agency:
        queryset = queryset.filter(agency__slug=agency)

    if get('with_photo') in ('1', 'true'):
        queryset = queryset.filter(images__isnull=False).distinct()

    build = get('build')
    if build in ('new', 'resale'):
        queryset = queryset.filter(_newbuild_clause() if build == 'new'
                                   else ~_newbuild_clause())

    sort = get('sort') if get('sort') in SORT_FIELDS else 'newest'
    field, descending = SORT_FIELDS[sort]
    expression = F(field).desc(nulls_last=True) if descending else F(field).asc(nulls_last=True)
    queryset = queryset.order_by(expression, '-id')

    total = queryset.count()
    try:
        page = max(1, int(get('page') or 1))
    except ValueError:
        page = 1
    # A fixed 60-page ceiling made stock beyond 1,440 offers unreachable.
    # Bound the offset by the actual filtered catalogue instead.
    page = min(page, max(1, (total + PER_PAGE - 1) // PER_PAGE))
    start = (page - 1) * PER_PAGE
    rows = [_serialise(o) for o in queryset[start:start + PER_PAGE]]

    return JsonResponse({'results': rows, 'total': total, 'page': page,
                         'per_page': PER_PAGE, 'sort': sort, 'deal': deal})


@require_GET
def facets(request):
    """Counted over the whole live set for this deal type, so a filter never
    hides the option that would widen it again."""
    deal = request.GET.get('deal') or 'sale'
    scoped = _scope(request, _live())
    base = scoped.filter(deal_type=deal)
    return JsonResponse({
        'total': base.count(),
        'kinds': [{'key': k, 'label': KIND_LABELS[k],
                   'count': base.filter(_kind_clause(k)).count()}
                  for k in KIND_GROUPS],
        'agencies': list(base.values('agency__slug', 'agency__name')
                         .annotate(count=Count('id')).order_by('-count')),
        'deals': [{'key': d, 'count': scoped.filter(deal_type=d).count()}
                  for d in ('sale', 'rent')],
        'build': [
            {'key': 'new', 'label': 'Ново строителство',
             'count': base.filter(_newbuild_clause()).count()},
            {'key': 'resale', 'label': 'Вторичен пазар',
             'count': base.filter(~_newbuild_clause()).count()},
        ],
    })


@require_GET
def offer_detail(request, pk):
    try:
        row = _scope(request, _live()).get(pk=pk)
    except Offer.DoesNotExist:
        return JsonResponse({'error': 'not found'}, status=404)
    data = _serialise(row)
    # Other agencies advertising what looks like the same flat. The spread
    # between them is the most interesting number on the page.
    siblings = [_serialise(o) for o in siblings_for(row, _live())[:PER_PAGE]]
    prices = [d['price'] for d in [data] + siblings if d['price']]
    data['siblings'] = siblings
    data['spread'] = (max(prices) - min(prices)) if len(prices) > 1 else None
    data['images'] = [f'/media/{i.local_path}' for i in row.images.all()]
    return JsonResponse(data)


@require_GET
def agencies(request):
    scoped_ids = _scope(request, Offer.objects.filter(is_active=True)).values('pk')
    rows = (Agency.objects.annotate(
        live=Count('offers', filter=Q(offers__pk__in=scoped_ids)))
        .filter(live__gt=0).order_by('-live'))
    return JsonResponse({'agencies': [
        {'slug': a.slug, 'name': a.name, 'website': a.website,
         'live': a.live, 'notes': a.notes} for a in rows]})


@require_GET
def stats(request):
    live = _scope(request, Offer.objects.filter(is_active=True))
    return JsonResponse({
        'offers': live.count(),
        'agencies': live.values('agency_id').distinct().count(),
        'with_photo': live.filter(images__isnull=False).distinct().count(),
        'sale': live.filter(deal_type='sale').count(),
        'rent': live.filter(deal_type='rent').count(),
    })
