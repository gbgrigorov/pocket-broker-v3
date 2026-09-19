# -*- coding: utf-8 -*-
"""Reading one listing page into the same record shape a price sheet produces.

Four sources, in descending order of how much they can be trusted:

1. the agency's own spec table -- "Площ: 50 кв.м", "Вид сделка: Под наем" --
   because the label says what the number means;
2. `RealEstateListing` / `Product` JSON-LD, published on purpose;
3. a site-specific pattern, where reconnaissance found a value in a known spot;
4. the visible text below the heading, for whatever the first three left open.

Everything reads from the post-heading content window, never the whole page. The
first version of this module did read the whole page, and stored a filter menu's
"Студии До 55 000€" as the asking price of three unrelated flats.

Anything still unknown stays None. A flat whose floor we do not know is a flat
to ring the agency about -- which downstream is exactly the "unverified" band.
"""
import re

from crm import features as feature_lib
from crm.dedup import dedup_key, title_norm
from sourcing.salvage import resolve_location
from sourcing.web import dom, labels

BGN_PER_EUR = 1.95583

MONEY = re.compile(r'([\d][\d\s .,]{2,12})\s*(€|EUR|евро|лв\.?|BGN)', re.I)
MONEY_LABELLED = re.compile(
    r'(?:цена|price|стоимост)\D{0,24}?([\d][\d\s .,]{2,12})\s*(€|EUR|евро|лв\.?|BGN)', re.I)
AREA = re.compile(r'([\d]+(?:[.,]\d+)?)\s*(?:кв\.?\s*м|м\s?2|м²|m\s?2|m²|sq\.?\s?m)', re.I)
BEDROOMS = re.compile(r'(\d)\s*[-\s]?\s*(?:спалн|bedroom|schlafzimmer)', re.I)
ROOMS_DIGIT = re.compile(r'(\d)\s*[-\s]?(?:х\s*)?(?:стаен|стайн|комнатн|комнат|room)', re.I)
FLOOR = re.compile(r'(?:етаж|этаж|floor)\D{0,8}(\d{1,2})|(\d{1,2})\s*[-\s]?(?:ти|ри|й|ый)?\s*(?:етаж|этаж|floor)', re.I)
STUDIO = re.compile(r'(студи|studio|monolocale|einzimmer)', re.I)
RENT = re.compile(r'(под наем|наем|аренда|for rent|rental|на нощувка|per night)', re.I)
# "Продан", "Продадено", "Продаден" -- one stem covers the lot. The first
# version missed the bare "Продан" that one agency uses as its status value.
SOLD = re.compile(r'(прода(?:н|ден)|sold|резервиран|зарезервирован|reserved|'
                  r'капаро|снят с продаж)', re.I)

# Written-out room counts, which no digit pattern catches. "Двустаен" is two
# rooms, therefore one bedroom -- the conversion the sheets already make.
ROOM_WORDS = [
    (1, r'(едностаен|однокомнатн|one[- ]room|1[- ]staen)'),
    (2, r'(двустаен|двухкомнатн|two[- ]room)'),
    (3, r'(тристаен|трехкомнатн|трёхкомнатн|three[- ]room)'),
    (4, r'(четиристаен|четырехкомнатн|четырёхкомнатн|four[- ]room)'),
]
ROOM_WORDS = [(n, re.compile(p, re.I)) for n, p in ROOM_WORDS]

KIND_WORDS = [
    ('villa', r'(вил[ла]|villa|вилла)'),
    ('townhouse', r'(таунхаус|townhouse|town house|редова къща)'),
    ('penthouse', r'(пентхаус|penthouse)'),
    ('maisonette', r'(мезонет|maisonette|мезонин)'),
    ('house', r'(къща|house|\bдом\b|дома\b|haus)'),
    ('land', r'(парцел|\bземя\b|\bland\b|\bplot\b|участок)'),
    ('office', r'(офис|office)'),
    ('shop', r'(магазин|\bshop\b|\bstore\b)'),
    ('hotel', r'(хотел|hotel)'),
]
KIND_WORDS = [(k, re.compile(p, re.I)) for k, p in KIND_WORDS]


def number(raw):
    """'88 900,00' / '88,900' / '88.900' -> 88900.0"""
    if raw is None:
        return None
    # Take the first number and stop. Stripping every non-digit instead
    # turned "33 кв. м." into "33.." and lost a value the page stated plainly.
    match = re.search(r'-?\d[\d\s .,]*', str(raw))
    if not match:
        return None
    clean = re.sub(r'[\s ]', '', match.group(0)).rstrip('.,')
    if not clean or not any(ch.isdigit() for ch in clean):
        return None
    if ',' in clean and '.' in clean:
        clean = (clean.replace('.', '').replace(',', '.')
                 if clean.rfind(',') > clean.rfind('.') else clean.replace(',', ''))
    elif ',' in clean:
        clean = clean.replace(',', '.') if re.search(r',\d{1,2}$', clean) else clean.replace(',', '')
    elif re.search(r'\.\d{3}$', clean):
        clean = clean.replace('.', '')
    try:
        return float(clean)
    except ValueError:
        return None


def _money(raw):
    """A labelled money string -> euros, converting leva."""
    if not raw:
        return None
    value = number(raw)
    if value is None:
        return None
    if re.search(r'(лв|BGN)', raw, re.I):
        value = round(value / BGN_PER_EUR, 2)
    return value


def _from_ld(objects):
    found = {}
    for node in objects:
        types = node.get('@type')
        types = types if isinstance(types, list) else [types]
        types = {str(t) for t in types if t}

        if types & {'RealEstateListing', 'Residence', 'Apartment', 'House', 'Product',
                    'SingleFamilyResidence', 'Offer', 'Accommodation'}:
            found.setdefault('title', node.get('name'))
            found.setdefault('description', node.get('description'))
            price, currency = node.get('price'), node.get('priceCurrency')
            offers = node.get('offers')
            if price is None and isinstance(offers, dict):
                price, currency = offers.get('price'), offers.get('priceCurrency')
            if price is not None:
                found.setdefault('price', number(price))
                found.setdefault('currency', (currency or 'EUR'))
            if node.get('numberOfBedrooms') is not None:
                found.setdefault('bedrooms', number(node['numberOfBedrooms']))
            if node.get('numberOfRooms') is not None:
                found.setdefault('rooms', number(node['numberOfRooms']))
            size = node.get('floorSize')
            if isinstance(size, dict):
                found.setdefault('area', number(size.get('value')))
            address = node.get('address')
            if isinstance(address, dict):
                found.setdefault('location_raw', ' '.join(
                    str(address[k]) for k in
                    ('streetAddress', 'addressLocality', 'addressRegion') if address.get(k)))

        if 'PropertyValue' in types and node.get('value') not in (None, ''):
            name = str(node.get('name') or '').lower()
            value = node['value']
            if re.search(r'(площ|area|size|кв)', name):
                found.setdefault('area', number(value))
            elif re.search(r'(спал|bedroom)', name):
                found.setdefault('bedrooms', number(value))
            elif re.search(r'(комнат|стаи|rooms)', name):
                found.setdefault('rooms', number(value))
            elif re.search(r'(етаж|этаж|floor)', name):
                found.setdefault('floor', number(value))
            elif re.search(r'(цена|price|стоимост)', name) and not re.search(r'(м2|кв)', name):
                found.setdefault('price', number(value))
    return {k: v for k, v in found.items() if v not in (None, '')}


def _kind(text):
    for kind, pattern in KIND_WORDS:
        if pattern.search(text):
            return kind
    return 'apartment'


def _bedrooms(spec, ld, window, title):
    if spec.get('bedrooms') is not None:
        value = number(spec['bedrooms'])
        if value is not None:
            return int(value)
    if spec.get('rooms') is not None:
        value = number(spec['rooms'])
        if value is not None:
            return max(int(value) - 1, 0)
    if ld.get('bedrooms') is not None:
        return int(ld['bedrooms'])
    if ld.get('rooms') is not None:
        return max(int(ld['rooms']) - 1, 0)

    match = BEDROOMS.search(title) or BEDROOMS.search(window)
    if match:
        return int(match.group(1))
    for rooms, pattern in ROOM_WORDS:
        if pattern.search(title) or pattern.search(window):
            return max(rooms - 1, 0)
    match = ROOMS_DIGIT.search(title) or ROOMS_DIGIT.search(window)
    if match:
        return max(int(match.group(1)) - 1, 0)
    if STUDIO.search(title) or STUDIO.search(window[:400]):
        return 0
    return None


def _price(spec, ld, window, hints, html):
    """Asking price in euros, and the text it was read from."""
    if spec.get('price'):
        value = _money(spec['price'])
        if value and 1000 <= value <= 5_000_000:
            return value, spec['price'][:120]

    if ld.get('price'):
        value = ld['price']
        if str(ld.get('currency', 'EUR')).upper() == 'BGN':
            value = round(value / BGN_PER_EUR, 2)
        if 1000 <= value <= 5_000_000:
            return value, f'{ld["price"]} {ld.get("currency", "EUR")}'

    for pattern in hints or ():
        match = re.search(pattern, html, re.I)
        if match:
            value = number(match.group(1))
            if value and 1000 <= value <= 5_000_000:
                return value, match.group(0)[:120]

    for matcher in (MONEY_LABELLED, MONEY):
        for match in matcher.finditer(window):
            value = number(match.group(1))
            if value is None:
                continue
            if re.search(r'(лв|BGN)', match.group(2), re.I):
                value = round(value / BGN_PER_EUR, 2)
            if 1000 <= value <= 5_000_000:
                return value, match.group(0)[:120]

    # One agency publishes a rate per square metre and no total at all. The
    # product of two numbers it does publish is a fair asking price -- but it is
    # arithmetic, not a quote, so it is marked as such wherever it is shown.
    rate, size = _money(spec.get('price_per_m2')), number(spec.get('area'))
    if rate and size and 1000 <= rate * size <= 5_000_000:
        return round(rate * size, 2), f"{spec['price_per_m2']} × {spec['area']}"
    return None, ''


def extract(html, url, spec_recipe=None):
    """One page -> a record dict, or None if it is not a usable listing."""
    recipe = spec_recipe or {}
    page = dom.read(html)
    ld = _from_ld(page['ld'])

    title = (page['h1'] or ld.get('title') or page['og'].get('title') or page['title'] or '')
    title = re.split(r'\s+[|–—]\s{1,}', title)[0].strip()[:400]
    if len(title) < 3:
        return None

    # Several themes hide their <h1> inside a wrapper this module reads as
    # furniture, so the window is anchored on whatever title we ended up with.
    window = page['content']
    if not page['h1']:
        window = dom.read(html, anchor=title)['content']
    if len(window) < 120:
        return None

    spec = labels.pairs(window)

    description = (ld.get('description') or page['og'].get('description') or '')[:4000]
    if not description:
        description = window[:1500]

    price, quoted = _price(spec, ld, window, recipe.get('price_hints'), html)
    derived_price = bool(price and '×' in quoted)

    area = number(spec.get('area')) or ld.get('area')
    if area is None:
        match = AREA.search(window)
        area = number(match.group(1)) if match else None
    if area is not None and not (10 <= area <= 1000):
        area = None

    bedrooms = _bedrooms(spec, ld, window, title)
    if bedrooms is not None and not 0 <= bedrooms <= 6:
        bedrooms = None

    floor = labels.floor_value(spec.get('floor'), number) if spec.get('floor') else None
    if floor is None:
        floor = ld.get('floor')
    if floor is None:
        for match in FLOOR.finditer(window):
            # "Етажност: 26" is how many floors the building has, not which one
            # this flat is on.
            before = window[max(0, match.start() - 24):match.start()].lower()
            if re.search(r'(етажност|общо етаж|всего этаж|total floor|из)', before):
                continue
            floor = number(match.group(1) or match.group(2))
            break
    if floor is not None:
        floor = int(floor)
        if not -1 <= floor <= 30:
            floor = None

    # Sold and reserved flats are still on these sites for weeks. Storing one as
    # live stock puts the broker on the phone offering something that is gone.
    status_text = f"{spec.get('status', '')} {title} {window[:300]}"
    sold = bool(SOLD.search(status_text))

    deal_source = f"{spec.get('deal', '')} {title} {window[:300]}"
    deal_type = 'rent' if RENT.search(deal_source) else 'sale'

    slug = re.sub(r'[-_/]+', ' ', url.split('//', 1)[-1])
    # Only what the page states about this listing: its location label, its
    # structured address, its heading, its URL, and its own summary line under
    # the heading. A loose sweep of the whole body reads resort names out of
    # menus and files a Bansko flat under Sunny Beach.
    location = (resolve_location(spec.get('location') or '', ld.get('location_raw') or '',
                                 title, slug)
                or resolve_location(window[:400], loose=True) or '')

    record = {
        'title': title,
        'title_norm': title_norm(title)[:400],
        'location': location,
        'location_raw': (spec.get('location') or ld.get('location_raw') or title)[:300],
        'location_salvaged': bool(location and not spec.get('location')),
        'price_eur': price,
        'price_raw': quoted[:120],
        'bedrooms': bedrooms,
        'area_m2': area,
        'floor': floor,
        'property_kind': _kind(f"{spec.get('kind', '')} {title}"),
        'deal_type': deal_type,
        'view': (spec.get('view') or '')[:300],
        'status': ('sold' if sold else 'active'),
        'furnished': labels.boolean(spec.get('furnished')),
        'maintenance_raw': (spec.get('maintenance') or '')[:200],
        'notes': description,
        'listing_url': url[:700],
        'ref': (spec.get('ref') or '')[:80],
        'data_flags': {'price_derived': True} if derived_price else {},
    }
    if record['price_eur'] and record['area_m2']:
        record['price_per_m2'] = round(record['price_eur'] / record['area_m2'], 2)

    # Sitemaps list town pages and category pages alongside real listings. A
    # page that states none of price, size or rooms is one of those, and storing
    # it would put empty rows in front of a client.
    known = sum(1 for value in (record['price_eur'], record['area_m2'],
                                record['bedrooms']) if value is not None)
    if known < 2:
        return None

    record['features'] = feature_lib.resolve(
        {**record, 'view': f"{record['view']} {spec.get('sea_distance', '')}",
         'notes': f'{description} {window[:3000]}', 'documents': ''})
    record['dedup_key'] = dedup_key(record)[:32]
    return record
