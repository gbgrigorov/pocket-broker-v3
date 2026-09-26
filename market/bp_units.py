"""Individual development inventory from BP's public price/availability tables.

The agency canonicalizes unit pages to the parent development. Source identity
therefore includes BOTH AD and PL IDs. A summary price range is never a unit.
"""
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from market.bulgarian_properties import Node, ParseError, Tree, first_number, listing_url, number, reference, text
from market.sofia_sources import result


def price_list_url(html, url):
    parent = reference(url)
    root = Tree(html).root
    info = root.find(cls='component-single-property-characteristic')
    links = [n.attrs.get('data-url', '') for n in (info.all() if info else [])
             if n.attrs.get('data-src') == '#singlePropertyPriceList']
    # The navigation is also the agency's own price-list button.
    links += [n.attrs.get('data-url', '') for n in root.all(cls='pricelist')
              if n.attrs.get('data-src') == '#singlePropertyPriceList']
    for link in links:
        parts = urlsplit(urljoin(url, link))
        q = parse_qs(parts.query)
        if (parts.scheme == 'https' and parts.hostname == 'www.bulgarianproperties.com'
                and parts.path == '/pdetail.php' and q.get('IID') == [parent]
                and q.get('scmd') == ['propprice'] and q.get('xajax') == ['1']):
            # Same GET the public Show button makes with all types/statuses.
            return 'https://www.bulgarianproperties.com/pdetail.php?' + urlencode(dict(
                IID=parent, xajax=1, scmd='propprice', searching=1, search_form=1,
                no_css_js=1, adm_ref='', search_type=0, search_status=0,
                search_min_area='', search_max_price=''))
    return None


ORDINALS = dict(zip(('first second third fourth fifth sixth seventh eighth ninth tenth '
                    'eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth '
                    'eighteenth nineteenth twentieth').split(), range(1, 21)))


def floor_number(label):
    value = label.casefold().strip()
    if value in ('ground floor', 'ground'):
        return 0
    match = re.fullmatch(r'(minus )?([a-z]+) floor', value)
    if match and match[2] in ORDINALS:
        return ORDINALS[match[2]] * (-1 if match[1] else 1)
    match = re.fullmatch(r'(-?\d+)(?:st|nd|rd|th)? floor', value)
    return int(match[1]) if match and -3 <= int(match[1]) <= 100 else None


def unit_tables(node, floor=None):
    """Track the displayed floor heading, not data-floor's internal enum."""
    for child in node.children:
        if not isinstance(child, Node):
            continue
        if 'sub-title' in child.attrs.get('class', '').split():
            floor = floor_number(child.text())
        elif child.tag == 'table':
            yield child, floor
        else:
            yield from unit_tables(child, floor)


def units(html, project_html, project_url):
    parent = reference(project_url)
    root, own = Tree(html).root, Tree(project_html).root
    wrapper = root.find(id='price-list')
    info = own.find(cls='component-single-property-general-information')
    if not wrapper or not info or 'PL' in parent:
        raise ParseError('Missing public development price-list identity')
    canonical = next((n.attrs.get('href') for n in own.all(tag='link') if n.attrs.get('rel') == 'canonical'), '')
    if reference(canonical) != parent:
        raise ParseError('Development canonical identity mismatch')
    location, title = text(info.find(cls='location')), text(info.find(tag='h1'))
    if not re.match(r'^Sofia(?:\s*,|\s*$)', location, re.I) or '_near_sofia' in project_url.lower():
        raise ParseError('Development is outside Sofia city')
    labels = text(info.find(cls='labels')).casefold()
    if ('for sale' in labels) == ('for rent' in labels):
        raise ParseError('Development deal missing or ambiguous')
    deal = 'rent' if 'for rent' in labels else 'sale'
    image = []
    for s in own.all(tag='script'):
        if s.attrs.get('type') == 'application/ld+json':
            try:
                product = json.loads(''.join(c for c in s.children if isinstance(c, str)), strict=False)
            except ValueError:
                continue
            if isinstance(product, dict) and product.get('@type') == 'Product':
                src = product.get('image')
                if isinstance(src, str) and urlsplit(src).hostname == 'static.bulgarianproperties.com':
                    image = [src]
    seen, rows = set(), []
    for table, floor in unit_tables(wrapper):
        for tr in table.all(tag='tr'):
            unit = tr.attrs.get('data-id', '')
            if not unit:
                continue
            if not unit.isdigit() or unit in seen:
                raise ParseError('Duplicate or invalid own price-list unit ID')
            seen.add(unit)
            ref = parent + 'PL' + unit
            url = listing_url(project_url.replace(f'/AD{parent}BG_', f'/AD{ref}BG_'))
            status = tr.find(cls='stat')
            value = text(status).upper()
            if value in ('SOLD', 'RESERVED') or (status and 'reserved' in status.attrs.get('class', '').split()):
                rows.append(dict(outcome='unavailable', ref=ref, url=url, location=location))
                continue
            if value != 'AVAILABLE' or not status:
                raise ParseError(f'Unknown own unit availability {ref}: {value}')
            kind, area, price_raw = text(tr.find(cls='apr_type')), text(tr.find(cls='apr_area')), text(tr.find(cls='apr_price'))
            if (first_number(area) or None) != (number(tr.attrs.get('data-size')) or None):
                raise ParseError(f'Own unit area disagrees with its data attribute: {ref}')
            shown_price, data_price = first_number(price_raw), number(tr.attrs.get('data-price'))
            rounded = (shown_price is not None and data_price is not None
                       and shown_price == shown_price.to_integral_value()
                       and shown_price == data_price.quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            if shown_price is not None and shown_price != data_price and not rounded:
                raise ParseError(f'Own unit price disagrees with its data attribute: {ref}')
            bedrooms = None
            match = re.fullmatch(r'(\d+)-bed', kind)
            if match:
                bedrooms = int(match[1])
                kind = f'{bedrooms}-bedroom apartment'
            elif kind.casefold() == 'studio':
                bedrooms = 0
            elif kind.casefold() == 'maisonette':
                kind = 'Maisonette'
            name = text(tr.find(tag='td')).removeprefix('#').strip()
            parsed = result(ref, url, title=f'{kind} {name} — {title}', location=location,
                deal=deal, kind=kind, price_raw=price_raw, area=area if first_number(area) else None, bedrooms=bedrooms,
                floor=floor, photos=image, fields=dict(project_ref=parent, unit_ref=unit,
                    unit_name=name, availability=value, floor_heading=floor,
                    area=area, price=price_raw, data_price=tr.attrs.get('data-price'),
                    visible_price_rounded=rounded and shown_price != data_price, image_scope='development'))
            if shown_price is not None and data_price is not None and data_price > 0:
                parsed['record']['price_eur'] = data_price
            rows.append(parsed)
    return rows
