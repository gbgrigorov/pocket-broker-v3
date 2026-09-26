"""Verified Bulgarian Properties city catalogue and detail parser (2026-09-25).

Parse the listing's own components, never menus, SEO links or related cards.
Development AggregateOffers are evidence for future project ingestion, not flats.
"""
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from crm.dedup import dedup_key, title_norm

HOST = 'www.bulgarianproperties.com'
CATALOGUE = f'https://{HOST}/Properties_in_the_town_of_Sofia/index.html'
LISTING = re.compile(r'/AD(\d+)(?:PL(\d+))?BG_[^/]+\.html$')
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


class ParseError(ValueError):
    pass


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def all(self, tag=None, cls=None, id=None):
        for child in self.children:
            if isinstance(child, Node):
                if ((tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get('class', '').split())
                        and (id is None or child.attrs.get('id') == id)):
                    yield child
                yield from child.all(tag, cls, id)

    def find(self, **kwargs):
        return next(self.all(**kwargs), None)

    def text(self):
        if self.tag in ('script', 'style'):
            return ''
        return ' '.join(' '.join(child.text() if isinstance(child, Node) else child
                                for child in self.children).split())


class Tree(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node('document')
        self.stack = [self.root]
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def text(node):
    return node.text() if node else ''


def listing_url(url, base=CATALOGUE):
    parsed = urlsplit(urljoin(base, url))
    if parsed.scheme != 'https' or parsed.hostname != HOST or parsed.port not in (None, 443) or parsed.username:
        raise ParseError('Listing URL outside canonical public domain')
    if not LISTING.search(parsed.path):
        raise ParseError('Not a verified AD listing URL')
    return urlunsplit(('https', HOST, parsed.path, '', ''))


def reference(url):
    match = LISTING.search(urlsplit(listing_url(url)).path)
    return match[1] + ('PL' + match[2] if match[2] else '')


def catalogue(html, url=CATALOGUE):
    parsed_url = urlsplit(url)
    if (parsed_url.scheme != 'https' or parsed_url.hostname != HOST or parsed_url.username
            or parsed_url.port not in (None, 443) or parsed_url.query
            or not re.fullmatch(r'/Properties_in_the_town_of_Sofia/index\d*\.html', parsed_url.path)):
        raise ParseError('Not the verified Sofia city catalogue')
    root = Tree(html).root
    wrapper = root.find(id='propertiesItemsContentWrapper')
    toolbar = wrapper.find(cls='component-list-properties-toolbar') if wrapper else None
    count = text(toolbar.find(cls='count')) if toolbar else ''
    if not wrapper or not count.isdigit():
        raise ParseError('Missing catalogue results wrapper/count')
    rows = {}
    for card in wrapper.all(cls='component-property-item'):
        link = card.find(tag='a', cls='title')
        if not link:
            raise ParseError('Catalogue card without title link')
        href = listing_url(link.attrs.get('href', ''), url)
        ref = reference(href)
        if card.attrs.get('id') != ref:
            raise ParseError('Catalogue card ID does not match its URL')
        location = text(card.find(cls='location'))
        row = {'ref': ref, 'url': href, 'location': location,
               'inactive': 'is-inactive' in card.attrs.get('class', '').split()}
        if ref in rows and rows[ref] != row:
            raise ParseError('Conflicting duplicate catalogue reference')
        rows[ref] = row
    total = int(count)
    if total and not rows:
        raise ParseError('Nonempty catalogue returned zero listing cards')
    current_path = urlsplit(url).path
    base = current_path.rsplit('/', 1)[0] + '/'
    links = {}
    for a in root.all(tag='a'):
        href = urljoin(url, a.attrs.get('href', ''))
        parts = urlsplit(href)
        if (parts.hostname != HOST or parts.scheme != 'https' or parts.query
                or parts.username or parts.port not in (None, 443)):
            continue
        match = re.fullmatch(re.escape(base) + r'index(\d*)\.html', parts.path)
        if match and 'pagination_' in a.attrs.get('data-preference-element-id', ''):
            links[int(match.group(1) or 0)] = href
    current = re.search(r'index(\d*)\.html$', current_path)
    current_index = int(current.group(1) or 0) if current else 0
    # These are URLs linked by the source. index1.html is the SECOND page.
    next_url = links.get(current_index + 1)
    return {'rows': list(rows.values()), 'total': total, 'next_url': next_url,
            'page_index': current_index, 'page_links': links}


def number(value):
    if isinstance(value, (int, float, Decimal)):
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else None
    value = re.sub(r'[\s\u00a0\u202f\u2009\u2019\']+', '', str(value or ''))
    if not re.fullmatch(r'-?\d+(?:[.,]\d+)*', value):
        return None
    if ',' in value and '.' in value:
        if value.rfind(',') > value.rfind('.'):
            value = value.replace('.', '').replace(',', '.')
        else:
            value = value.replace(',', '')
    elif ',' in value:
        value = value.replace(',', '' if re.fullmatch(r'\d{1,3}(,\d{3})+', value) else '.')
    elif re.fullmatch(r'\d{1,3}(\.\d{3})+', value):
        value = value.replace('.', '')
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def first_number(value):
    match = re.search(r'\d[\d\s\u00a0\u202f\u2009.,\u2019\']*', value or '')
    return number(match.group()) if match else None


def single_integer(value):
    if value.lower() in ('ground', 'ground floor', 'партер'):
        return 0
    match = re.fullmatch(r'(-?\d+)(?:\s+of\s+\d+)?', value)
    return int(match.group(1)) if match else None


def detail(html, url, city='sofia'):
    requested = listing_url(url)
    ref = reference(requested)
    parent_ref, _, unit_ref = ref.partition('PL')
    root = Tree(html).root
    scripts = '\n'.join(''.join(c for c in s.children if isinstance(c, str)) for s in root.all(tag='script'))
    primary = next((m for m in re.finditer(r'\bvar\s+master_IID\s*=\s*(\d+)\s*;\s*var\s+master_unit_ID\s*=\s*(\d+)\s*;', scripts)
                    if m[1] != '0'), None)
    canonical = next((n.attrs.get('href') for n in root.all(tag='link') if n.attrs.get('rel') == 'canonical'), None)
    if not canonical or reference(canonical) != (parent_ref if unit_ref else ref):
        raise ParseError('Canonical source identity missing or inconsistent')
    canonical = listing_url(canonical)
    if unit_ref:
        if not primary or (primary[1], primary[2]) != (parent_ref, unit_ref):
            raise ParseError('Requested unit identity missing from its own page')
        canonical = requested
    info = root.find(cls='component-single-property-general-information')
    features = root.find(cls='component-single-property-characteristic')
    pricing = root.find(cls='component-single-property-price')
    if not info or not features or not pricing:
        raise ParseError('Not a complete listing page')
    title = text(info.find(tag='h1'))
    location = text(info.find(cls='location'))
    if not title or not location or '\ufffd' in title + location:
        raise ParseError('Missing or undecodable listing identity/location')
    labels = text(info.find(cls='labels')).lower()
    city_name = {'sofia': 'Sofia', 'varna': 'Varna'}[city]
    values = {}
    for item in features.all(cls='characteristic'):
        values[text(item.find(cls='label')).strip().lower()] = text(item.find(cls='value'))
    stated_ref = values.get('ref. no.', '')
    if not re.search(r'(?<!\d)' + parent_ref + r'(?!\d)', stated_ref):
        # The visible marketing reference can contain an agency typo. The
        # canonical AD URL and its own primary page ID must independently
        # agree before retaining that typo as evidence rather than an ID.
        if not primary or primary[1] != parent_ref or primary[2] != (unit_ref or '0'):
            raise ParseError('Listing reference does not agree with canonical URL')
        values['marketing reference differs from primary id'] = stated_ref
    product = None
    for script in root.all(tag='script'):
        if script.attrs.get('type') != 'application/ld+json':
            continue
        try:
            item = json.loads(''.join(c for c in script.children if isinstance(c, str)), strict=False)
        except (ValueError, TypeError):
            continue
        if isinstance(item, dict) and item.get('@type') == 'Product':
            product = item
            break
    offer = (product or {}).get('offers') or {}
    if not isinstance(offer, dict):
        raise ParseError('Unexpected structured offer')
    if offer.get('url') and reference(offer['url']) not in (parent_ref, ref):
        raise ParseError('Structured offer identifies a different listing')
    # Validate identity before classifying a page as safely outside our scope.
    if ('_near_' + city_name.lower() in canonical.lower()
            or not re.match(r'^' + city_name + r'(?:\s*,|\s*$)', location, re.I)):
        return {'outcome': 'outside_city', 'ref': ref, 'url': canonical, 'location': location}
    availability = str(offer.get('availability', '')).rsplit('/', 1)[-1].lower()
    if any(token in labels for token in ('sold', 'rented', 'invalid offer', 'reserved')) or availability in ('outofstock', 'soldout', 'discontinued'):
        return {'outcome': 'unavailable', 'ref': ref, 'url': canonical, 'status': labels,
                'location': location}
    range_pattern = r'\d\s*(?:[-–—]|\bto\b)\s*\d'
    if not unit_ref and (offer.get('@type') == 'AggregateOffer' or root.find(cls='pricelist')
            or ',' in values.get('bedrooms', '')
            or 'various types' in values.get('type of property', '').lower()
            or re.search(range_pattern, values.get('area', ''), re.I)
            or re.search(range_pattern, values.get('floor', ''), re.I)):
        return {'outcome': 'project', 'ref': ref, 'url': canonical, 'location': location,
                'low_price': offer.get('lowPrice'), 'high_price': offer.get('highPrice')}
    if ('for sale' in labels) == ('for rent' in labels):
        raise ParseError('Missing or ambiguous deal type')
    deal = 'rent' if 'for rent' in labels else 'sale'
    price_node = pricing.find(id='newprice') or pricing.find(cls='regular-price') or pricing.find(cls='new-price')
    price_raw = text(price_node)
    if re.search(range_pattern, price_raw, re.I) or 'from' in price_raw.lower():
        return {'outcome': 'project', 'ref': ref, 'url': canonical, 'location': location}
    displayed = first_number(price_raw) if ('€' in price_raw or 'EUR' in price_raw) else None
    own_price = not unit_ref or (offer.get('url') and reference(offer['url']) == ref)
    structured = number(offer.get('price')) if own_price and offer.get('priceCurrency') == 'EUR' else None
    if displayed is not None and structured is not None and displayed != structured:
        raise ParseError('Visible and structured prices disagree')
    price = displayed if displayed is not None else structured
    # Some active commercial listings publish a zero placeholder for an
    # undisclosed asking price. Retain the listing with an unknown price.
    if price == 0:
        price = None
    if price is not None and (price <= 0 or price > Decimal('9999999999.99')):
        raise ParseError('Price outside storage bounds')
    area = first_number(values.get('area', ''))
    if area is not None and (area <= 0 or area > Decimal('999999.99')):
        raise ParseError('Area outside storage bounds')
    kind = values.get('type of property', '')
    bedrooms = single_integer(values.get('bedrooms', ''))
    floor = single_integer(values.get('floor', ''))
    if bedrooms is not None and not 0 <= bedrooms <= 30:
        bedrooms = None
    if floor is not None and not -3 <= floor <= 100:
        floor = None
    if bedrooms is None and kind.lower() == 'studio':
        bedrooms = 0
    image = (product or {}).get('image')
    images = [image] if isinstance(image, str) else (image if isinstance(image, list) else [])
    for meta in root.all(tag='meta'):
        if meta.attrs.get('property') == 'og:image':
            images.append(meta.attrs.get('content', ''))
    images = list(dict.fromkeys(i for i in images if isinstance(i, str) and
        urlsplit(i).scheme == 'https' and urlsplit(i).hostname == 'static.bulgarianproperties.com'
        and '/property-images/' in urlsplit(i).path))
    record = {'ref': ref, 'listing_url': canonical, 'title': title[:400],
              'location': location[:120], 'location_raw': location[:300],
              'deal_type': deal, 'property_kind': kind[:40], 'type_raw': kind[:200],
              'price_eur': price, 'price_raw': price_raw[:120], 'area_m2': area,
              'bedrooms': bedrooms, 'floor': floor, 'status': 'active',
              'title_norm': title_norm(title)[:400]}
    record['dedup_key'] = dedup_key(record)
    return {'outcome': 'offer', 'ref': ref, 'url': canonical, 'record': record,
            'images': images, 'fields': values}
