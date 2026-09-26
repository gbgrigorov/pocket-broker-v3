"""Read-only matching for anonymous buyers; personal profiles stay in their browser."""
import json
import re

from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from crm.features import match as feature_match
from market.api import _live, _serialise, KIND_GROUPS, PER_PAGE
from market.newbuild import stage_of
from market.models import City, Neighbourhood
from sourcing.models import Offer

FEATURES = {
    'lift': 'Асансьор', 'parking': 'Паркомясто', 'garden': 'Двор / градина',
    'furnished': 'Обзаведен', 'act16': 'Готов за живеене (Акт 16)',
}


def body(request):
    if len(request.body) > 20000:
        raise ValueError('Заявката е твърде голяма.')
    try:
        value = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise ValueError('Невалидна заявка.') from None
    if not isinstance(value, dict):
        raise ValueError('Невалидна заявка.')
    return value


def validate_profile(value):
    if not isinstance(value, dict):
        raise ValueError('Попълнете профила си.')
    city = value.get('city')
    if not isinstance(city, str) or not City.objects.filter(slug=city, active=True).exists():
        raise ValueError('Изберете валиден град.')
    deal = value.get('deal', 'sale')
    kind = value.get('kind', 'apartment')
    if deal not in ('sale', 'rent') or kind not in ('apartment', 'house'):
        raise ValueError('Изберете вид имот и сделка.')
    profile = {'city': city, 'deal': deal, 'kind': kind}
    for key, maximum in [('rooms', 10), ('price_min', 100000000),
                         ('price_max', 100000000), ('area_min', 100000)]:
        number = value.get(key)
        if number in (None, ''):
            profile[key] = None
        elif isinstance(number, bool) or not re.fullmatch(r'\d{1,9}', str(number)):
            raise ValueError('Въведете цели, неотрицателни числа.')
        else:
            profile[key] = int(number)
            if profile[key] > maximum or (key == 'rooms' and profile[key] < 1):
                raise ValueError('Числото е извън допустимия диапазон.')
    if (profile['price_min'] is not None and profile['price_max'] is not None
            and profile['price_min'] > profile['price_max']):
        raise ValueError('Минималната цена трябва да е по-ниска от максималната.')
    for key, allowed in [('neighbourhoods', set(Neighbourhood.objects.filter(
            city__slug=city, active=True).values_list('slug', flat=True))),
                         ('features', set(FEATURES))]:
        items = value.get(key, [])
        if (not isinstance(items, list) or len(items) > 100
                or any(not isinstance(item, str) or item not in allowed for item in items)):
            raise ValueError('Изберете валидни квартали и характеристики.')
        profile[key] = list(dict.fromkeys(items))
    pets = value.get('pets', 'none')
    if pets not in ('none', 'cat', 'dog', 'other'):
        raise ValueError('Изберете валидна настройка за домашни любимци.')
    profile['pets'] = pets
    return profile


def rooms_of(offer):
    kind = (offer.property_kind or '').casefold()
    for token, rooms in [('едностаен', 1), ('студио', 1), ('двустаен', 2), ('тристаен', 3),
                         ('четиристаен', 4)]:
        if token in kind:
            return rooms
    # Bulgarian rooms include the living room: двустаен = one bedroom.
    return offer.bedrooms + 1 if offer.bedrooms is not None else None


def pets_allowed(offer):
    text = f'{offer.title} {offer.notes}'.casefold()
    if re.search(r'без домашни любимци|не се допускат домашни|не са позволени домашни|'
                 r'no pets|pets (?:are )?not allowed|без животни', text):
        return False
    if re.search(r'домашни любимци (?:са )?(?:позволени|разрешени|добре дошли)|'
                 r'(?:допускат|приемат) се домашни любимци|pet[- ]friendly|'
                 r'pets (?:are )?(?:allowed|welcome)', text):
        return True
    return None


def requirement_feature(token, data):
    text = ' '.join(str(value or '') for value in data.values()).casefold()
    negatives = {
        'lift': r'без асансьор|няма асансьор|no (?:lift|elevator)',
        'parking': r'без паркомясто|няма паркомясто|без паркинг|no parking',
        'garden': r'без двор|без градина|няма двор|no (?:garden|yard)',
    }
    if token in negatives and re.search(negatives[token], text):
        return False
    if token == 'act16':
        if re.search(r'(?:без|няма|очакван\w*|предстои)\s+акт\s*-?\s*16|'
                     r'акт\s*-?\s*16\s*(?:се очаква|през|до края|в края|очакван|планиран)', text):
            return False
        stage, _ = stage_of(text)
        if stage:
            return stage == 'act16'
    return feature_match(token, data)


def score_offer(offer, profile):
    checks = [('Град', True, 3), ('Вид сделка', True, 2)]
    geo = getattr(offer, 'geo', None)
    kind = (offer.property_kind or '').casefold()
    kinds = {group for group, tokens in KIND_GROUPS.items() if any(token in kind for token in tokens)}
    if re.search(r'четиристаен|петстаен|\d[- ]?стаен', kind):
        kinds.add('apartment')
    # Explicit non-residential types must not masquerade as unknown apartments.
    if kind and not kinds and re.search(r'гараж|паркомясто|склад|garage|parking|warehouse', kind):
        return None
    checks.append(('Вид имот', profile['kind'] in kinds if kinds else None, 2))
    if profile['rooms'] is not None:
        rooms = rooms_of(offer)
        checks.append((f"{profile['rooms']} стаи", rooms == profile['rooms'] if rooms is not None else None, 3))
    if profile['price_min'] is not None or profile['price_max'] is not None:
        price = offer.price_eur
        fits = None if price is None else (
            (profile['price_min'] is None or price >= profile['price_min']) and
            (profile['price_max'] is None or price <= profile['price_max']))
        checks.append(('Бюджет', fits, 3))
    if profile['area_min'] is not None:
        checks.append(('Минимална площ', offer.area_m2 >= profile['area_min'] if offer.area_m2 is not None else None, 2))
    if profile['neighbourhoods']:
        checks.append(('Квартал', geo.neighbourhood.slug in profile['neighbourhoods']
                       if geo and geo.neighbourhood_id else None, 3))
    data = {field: getattr(offer, field, None) for field in
            ('title', 'notes', 'documents', 'status', 'ready_date', 'furnished')}
    for token in profile['features']:
        answer = requirement_feature(token, data)
        checks.append((FEATURES[token], answer, 1))
    if profile['pets'] != 'none' and profile['deal'] == 'rent':
        checks.append(('Домашни любимци са разрешени', pets_allowed(offer), 2))
    # Known contradictions fail requirements. Missing facts remain candidates.
    if any(answer is False for _, answer, _ in checks):
        return None
    total = sum(weight for _, _, weight in checks)
    known = sum(weight for _, answer, weight in checks if answer is not None)
    return {
        'confidence': round(100 * known / total),
        'band': 'verified' if known == total else 'unverified',
        'reasons': [label for label, answer, _ in checks if answer is True],
        'unknown': [label for label, answer, _ in checks if answer is None],
    }


@never_cache
@require_GET
def options(request):
    return JsonResponse({'features': [{'key': key, 'label': label} for key, label in FEATURES.items()],
                         'csrf_token': get_token(request)})


@never_cache
@require_POST
def matches(request):
    try:
        value = body(request)
        profile = validate_profile(value.get('profile'))
        page = value.get('page', 1)
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise ValueError('Невалидна страница.')
    except ValueError as error:
        return JsonResponse({'error': str(error)}, status=400)
    candidates = Offer.objects.filter(is_active=True, geo__city__slug=profile['city'],
            geo__city__active=True, deal_type=profile['deal']).exclude(listing_url='').select_related(
            'geo__city', 'geo__neighbourhood').order_by('-first_seen', '-pk')
    ranked = []
    for offer in candidates:
        result = score_offer(offer, profile)
        if result is not None:
            ranked.append((offer.pk, result))
    ranked.sort(key=lambda row: row[1]['confidence'], reverse=True)
    start = (page - 1) * PER_PAGE
    selected = ranked[start:start + PER_PAGE]
    rows = {offer.pk: _serialise(offer) for offer in _live().filter(pk__in=[pk for pk, _ in selected])}
    return JsonResponse({'results': [dict(rows[pk], match=result) for pk, result in selected if pk in rows],
                         'total': len(ranked), 'page': page, 'per_page': PER_PAGE,
                         'city': profile['city']})


@never_cache
@require_POST
def wishlist(request):
    try:
        ids = body(request).get('ids')
        if (not isinstance(ids, list) or len(ids) > 200 or
                any(isinstance(pk, bool) or not isinstance(pk, int) or pk < 1 or pk > 2**63 - 1 for pk in ids)):
            raise ValueError('Невалиден списък с имоти (до 200).')
    except ValueError as error:
        return JsonResponse({'error': str(error)}, status=400)
    rows = {offer.pk: _serialise(offer) for offer in _live().filter(pk__in=ids)}
    return JsonResponse({'results': [rows[pk] for pk in dict.fromkeys(ids) if pk in rows],
                         'unavailable': [pk for pk in dict.fromkeys(ids) if pk not in rows]})
