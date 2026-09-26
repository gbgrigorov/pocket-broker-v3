"""Five-source Sofia cohort. Public catalogue/detail recipes verified 2026-09-26.

Owned by Pocket Broker; the vendored Varna adapters are deliberately untouched.
Only a listing's own fields are facts. Menus, broker biographies, recommendations
and development price ranges must never supply a unit's city, rooms or price.
"""
import json
import re
from decimal import Decimal
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from crm.dedup import dedup_key, title_norm
from market.bulgarian_properties import Node, ParseError, Tree, first_number, number, text

COHORT = ('bulgarian-properties', 'yavlena', 'home2u', 'luximmo', 'arco-real-estate')
ROOM_NAMES = {1: 'Едностаен апартамент', 2: 'Двустаен апартамент',
              3: 'Тристаен апартамент', 4: 'Четиристаен апартамент'}
RANGE = re.compile(r'\d\s*[-–—]\s*\d|(?:от|from)\s+\d', re.I)


def public_url(url, host, base=None):
    parts = urlsplit(urljoin(base or f'https://{host}/', url))
    if (parts.scheme != 'https' or parts.hostname not in (host, host.removeprefix('www.'))
            or parts.username or parts.password or parts.port not in (None, 443)):
        raise ParseError('URL outside verified public source')
    return urlunsplit(('https', host, quote(unquote(parts.path), safe='/()-._~'), parts.query, ''))


def own_canonical(root, url, host, *, og=False):
    links = [n.attrs.get('href') for n in root.all(tag='link') if n.attrs.get('rel') == 'canonical']
    if og:
        links += [n.attrs.get('content') for n in root.all(tag='meta') if n.attrs.get('property') == 'og:url']
    if not links or public_url(links[0], host) != public_url(url, host):
        raise ParseError('Canonical listing identity missing or inconsistent')
    return public_url(links[0], host)


def integer(value, low=-3, high=100):
    value = str(value if value is not None else '').strip()
    if value.casefold() == 'партер':
        return 0
    if re.fullmatch(r'-?\d+', value) and low <= int(value) <= high:
        return int(value)
    return None


def kind_of(value):
    """Bulgarian total rooms, never interpreted directly as bedrooms."""
    for token, rooms in [('едностаен', 1), ('двустаен', 2), ('тристаен', 3), ('четиристаен', 4)]:
        if token in value.casefold():
            return ROOM_NAMES[rooms], rooms
    match = re.search(r'(?<!\d)([1-9])\s*[- ]?\s*стаен', value, re.I)
    if match:
        rooms = int(match[1])
        return ROOM_NAMES.get(rooms, 'Многостаен апартамент'), rooms
    for pattern, kind in [(r'мезонет', 'Мезонет'), (r'студио', 'Студио'),
                          (r'апартамент', 'Апартамент'), (r'къща|вила', 'Къща'),
                          (r'парцел', 'Парцел'), (r'магазин', 'Магазин'),
                          (r'пром(?:ишлено|\.)?\s+помещение', 'Промишлено помещение'),
                          (r'склад', 'Склад'), (r'офис', 'Офис'), (r'гараж|паркомясто', 'Гараж')]:
        if re.search(pattern, value, re.I):
            return kind, 1 if kind == 'Студио' else None
    return value[:40], None


def pet_fact(value):
    match = re.search(r'(?:Не се допускат|Без|Допускат се|Приемат се)\s+домашни любимци|'
                      r'Домашни любимци\s+(?:са )?(?:разрешени|позволени|не са позволени)', value, re.I)
    return match.group() if match else ''


def result(ref, url, *, title, location, deal, kind, price_raw, area, bedrooms=None,
           floor=None, fields=None, photos=(), notes='', furnished=None):
    if not title or not location or '\ufffd' in title + location:
        raise ParseError('Missing or undecodable own title/location')
    fields = fields or {}
    price = first_number(price_raw) if re.search(r'€|EUR', price_raw, re.I) else None
    if price is not None and not 0 < price <= Decimal('9999999999.99'):
        raise ParseError('Price outside storage bounds')
    area = first_number(str(area))
    if area == 0:
        fields = {**fields, 'area_placeholder': str(area)}
        area = None
    if area is not None and not 0 < area <= Decimal('999999.99'):
        raise ParseError('Area outside storage bounds')
    record = dict(ref=str(ref), listing_url=url, title=title[:400], title_norm=title_norm(title)[:400],
        location=location[:120], location_raw=location[:300], deal_type=deal,
        property_kind=kind[:40], type_raw=kind[:200], price_eur=price, price_raw=price_raw[:120],
        area_m2=area, bedrooms=integer(bedrooms, 0, 30), floor=integer(floor),
        status='active', notes=notes[:1200], furnished=furnished)
    record['dedup_key'] = dedup_key(record)
    return dict(outcome='offer', ref=str(ref), url=url, record=record,
                images=list(dict.fromkeys(photos)), fields=fields)


def skip(outcome, ref, url, location=''):
    return dict(outcome=outcome, ref=str(ref), url=url, location=location)


def next_flight(root):
    """Decode ordinary server-rendered Next flight; ignore referenced biographies.

    JSONDecoder stops at the end of each JSON record, even when a text record
    contains literal newlines. We only return props with exact primary keys.
    """
    fragments = []
    for script in root.all(tag='script'):
        raw = ''.join(c for c in script.children if isinstance(c, str))
        match = re.search(r'self\.__next_f\.push\((\[.*\])\)', raw)
        if not match:
            continue
        value = json.loads(match[1])
        if len(value) > 1 and isinstance(value[1], str):
            fragments.append(value[1])
    flight = ''.join(fragments)
    # Flight T records carry a UTF-8 byte length and need no trailing newline.
    # A description can therefore end immediately before the primary props.
    # Remove length-delimited text before looking for JSON record boundaries;
    # text that happens to resemble a record must never become source facts.
    encoded = flight.encode('utf-8')
    chunks, offset = [], 0
    while offset < len(encoded):
        match = re.compile(rb'[0-9a-f]+:T([0-9a-f]+),').match(encoded, offset)
        if not match:
            match = re.compile(rb'(?:^|\n)[0-9a-f]+:T([0-9a-f]+),').search(encoded, offset)
        if not match:
            break
        end = match.end() + int(match[1], 16)
        if end > len(encoded):
            raise ParseError('Incomplete Flight text record')
        chunks.extend((encoded[offset:match.start()], b'\n'))
        offset = end
    chunks.append(encoded[offset:])
    flight = b''.join(chunks).decode('utf-8')
    decoder = json.JSONDecoder()
    for match in re.finditer(r'(?:^|\n)[0-9a-f]+:(?=\[|\{)', flight):
        try:
            item, _ = decoder.raw_decode(flight, match.end())
        except ValueError:
            continue
        if isinstance(item, list) and len(item) == 4 and isinstance(item[3], dict):
            yield item[3]


class Yavlena:
    slug, name, host = 'yavlena', 'Явлена', 'www.yavlena.com'
    hosts = (host, 'yavlena.com', 'images.yavlena.com')
    starts = {deal: f'https://www.yavlena.com/bg/{path}/sofia-sofia/d23l4396'
              for deal, path in [('sale', 'sales'), ('rent', 'rentals')]}

    def catalogue(self, html, url, deal):
        parts = urlsplit(public_url(url, self.host))
        if parts.path != urlsplit(self.starts[deal]).path:
            raise ParseError('Not the verified Sofia catalogue')
        root = Tree(html).root
        props = next((p for p in next_flight(root) if 'ssrResult' in p), None)
        if not props or not props['ssrResult'].get('succeeded'):
            raise ParseError('Missing successful server-rendered catalogue')
        data = props['ssrResult']['data']
        total = integer(data.get('propertyServicesCount'), 0, 1000000)
        if total is None:
            raise ParseError('Missing catalogue count')
        page = int(parse_qs(parts.query).get('page', ['0'])[0])
        links = {unquote(a.attrs.get('href', '')) for a in root.all(tag='a')}
        rows = []
        for card in data['cards']:
            ref = str(card['propertyInnerNumber'])
            path = f'/bg/{ref}' + ('/rent' if card['isRent'] else '')
            if path not in links or bool(card['isRent']) != (deal == 'rent'):
                raise ParseError('Catalogue identity/deal does not match its own link')
            rows.append(dict(ref=ref, url=f'https://{self.host}{path}', deal=deal,
                location=card.get('cityName', ''), inactive=bool(card.get('isSoldOrRented')),
                project=bool(card.get('isProject'))))
        if total and not rows:
            raise ParseError('Nonempty catalogue returned no cards')
        # Verified public SSR ?page=2 returns a distinct 50-card batch. The
        # site's page index starts at zero (same as its public scroll query).
        next_url = self.starts[deal] + f'?page={page + 1}' if (page + 1) * 50 < total else None
        return dict(rows=rows, total=total, next_url=next_url)

    def detail(self, html, url, deal):
        root = Tree(html).root
        canonical = own_canonical(root, url, self.host)
        match = re.fullmatch(r'/bg/(\d+)(/rent)?', urlsplit(canonical).path)
        if not match or bool(match[2]) != (deal == 'rent'):
            raise ParseError('Invalid listing URL/deal')
        ref = match[1]
        props = next((p for p in next_flight(root) if 'property' in p), None)
        data = (props or {}).get('property', {}).get('propertyData', {})
        if str(data.get('innerNumber')) != ref or bool(data.get('isRent')) != (deal == 'rent'):
            raise ParseError('Primary listing identity/deal mismatch')
        location = ', '.join(filter(None, [data.get('cityName'), data.get('quarterName')]))
        if data.get('cityName') != 'София':
            return skip('outside_city', ref, canonical, location)
        if data.get('isSoldOrRented'):
            return skip('unavailable', ref, canonical, location)
        if data.get('isProject'):
            return skip('project', ref, canonical, location)
        h1 = text(root.find(tag='h1'))
        kind = re.split(r'кв\.м\.?\s*', h1, maxsplit=1)[-1].strip()
        kind, _ = kind_of(kind)
        price_raw = '' if data.get('hidePrice') else str(data.get('price') or '')
        price = number(data.get('priceDecimal'))
        if price_raw and price is not None and first_number(price_raw) != price:
            raise ParseError('Visible and structured prices disagree')
        paths = {p['filePath'] for p in data.get('photos', []) if p.get('isImage')}
        photos = []
        for img in root.all(tag='img'):
            source = img.attrs.get('src', '')
            decoded = parse_qs(urlsplit(source).query).get('url', [source])[0]
            parts = urlsplit(decoded)
            if parts.scheme == 'https' and parts.hostname == 'images.yavlena.com' and parts.path.rsplit('/', 1)[-1] in paths:
                photos.append(decoded)
        # Store only factual flags; no broker biography or full descriptions.
        notes = 'Асансьор' if data.get('elevator') is True else ''
        if deal == 'rent' and data.get('allowedPets') is True:
            notes += ' Домашни любимци са разрешени.'
        fields = {k: data.get(k) for k in ('roomsCount', 'bedroomsCount', 'elevator', 'allowedPets', 'hidePrice')}
        return result(ref, canonical, title=data.get('title') or h1, location=location,
            deal=deal, kind=kind, price_raw=price_raw, area=data.get('area'),
            bedrooms=data.get('bedroomsCount'), photos=photos, fields=fields, notes=notes.strip())


class Home2U:
    slug, name, host = 'home2u', 'Home2U', 'home2u.bg'
    hosts = (host, 'www.home2u.bg', 'home2u.skyholding.media')
    starts = {'sale': 'https://home2u.bg/nedvizhimi-imoti-sofia/',
              'rent': 'https://home2u.bg/wp-admin/admin-ajax.php?' + urlencode(dict(
                  action='filter_properties', city=5, offer_type=353,
                  properties_page=1, listing_type='list', lang='bg'))}

    def catalogue(self, html, url, deal):
        url = public_url(url, self.host)
        parts = urlsplit(url)
        property_types = None
        if parts.path == '/wp-admin/admin-ajax.php':
            query = parse_qs(parts.query)
            if query.get('action') != ['filter_properties'] or query.get('city') != ['5'] or query.get('offer_type') != [str(352 if deal == 'sale' else 353)]:
                raise ParseError('Not the verified public Sofia filter')
            payload = json.loads(html)
            if payload.get('success') is not True:
                raise ParseError('Unsuccessful public catalogue search')
            root = Tree(payload['data']['content_html']).root
            page = int(query['properties_page'][0])
            property_types = query.get('property_type[]')
        else:
            apartment_rent = 'https://home2u.bg/apartamenti-pod-naem-sofia/'
            if url != self.starts[deal] and not (deal == 'rent' and url == apartment_rent):
                raise ParseError('Not the verified Sofia catalogue')
            if url == apartment_rent:
                property_types = [48, 12, 11, 20]
            root = Tree(html).root
            form = root.find(id='property-filter')
            selected = [n.attrs.get('value') for n in (form.all(tag='option') if form else []) if 'selected' in n.attrs and n.attrs.get('value') == '5']
            if not selected:
                raise ParseError('Sofia filter was not selected')
            page = 1
        wrapper = root.find(cls='js-properties-listing')
        if not wrapper:
            raise ParseError('Missing own catalogue results wrapper')
        rows = {}
        for card in wrapper.all(tag='article', cls='article-catalog'):
            a = next((n for n in card.all(tag='a') if re.search(r'/(?:property|project)/', n.attrs.get('href', ''))), None)
            if not a:
                raise ParseError('Missing listing link')
            href = public_url(a.attrs['href'], self.host, url)
            if not re.fullmatch(r'/(?:property|project)/[^/]+/', unquote(urlsplit(href).path)):
                raise ParseError('Unexpected listing URL')
            rows[href] = dict(ref=unquote(urlsplit(href).path).split('/')[2], url=href, deal=deal,
                              project='/project/' in urlsplit(href).path)
        pages = {int(n.attrs['data-page']) for n in wrapper.all(cls='js-pagination-link') if n.attrs.get('data-page', '').isdigit()}
        next_url = None
        if page + 1 in pages:
            query = dict(action='filter_properties', city=5, offer_type=352 if deal == 'sale' else 353,
                         properties_page=page + 1, listing_type='list', lang='bg')
            # Preserve an explicit public filter, but the default full rental
            # catalogue has no apartment-only restriction.
            if property_types:
                query['property_type[]'] = property_types
            next_url = f'https://{self.host}/wp-admin/admin-ajax.php?' + urlencode(query, doseq=True)
        if not rows and pages:
            raise ParseError('Catalogue returned no cards despite pagination')
        return dict(rows=list(rows.values()), total=None, next_url=next_url,
                    advertised_pages=max(pages, default=page))

    def detail(self, html, url, deal):
        root = Tree(html).root
        canonical = own_canonical(root, url, self.host)
        if '/project/' in urlsplit(canonical).path:
            return skip('project', unquote(urlsplit(canonical).path).split('/')[2], canonical)
        info, specs, sticky = root.find(cls='section-building-info-secondary'), root.find(cls='list-building-info'), root.find(cls='section-sticky')
        match = re.search(r'Код на обявата:\s*(\d+)', text(sticky))
        if not info or not specs or not match:
            raise ParseError('Missing own listing body/specifications/code')
        ref = match[1]
        fields = {}
        for li in specs.all(tag='li'):
            label, sep, value = li.text().partition(':')
            if sep:
                fields[label.strip()] = value.strip()
        location_raw = fields.get('Местоположение', '')
        components = [s.strip() for s in location_raw.split(',')]
        if components.count('София') != 1 or any(re.search(r'^(?:с\.|село |Банкя$)', s, re.I) for s in components):
            return skip('outside_city', ref, canonical, location_raw)
        location = ', '.join(['София'] + [s for s in components if s != 'София'])
        title = text(info.find(tag='h1'))
        type_pattern = r'стаен|апартамент|мезонет|студио|ателие|къща|вила|парцел|магазин|офис|гараж|паркомясто|пром\.?\s*помещение|склад|заведение|ресторант|земеделска'
        if not title or re.match(r'^За имота(?:\s|$)', title, re.I) or not re.search(type_pattern, title, re.I):
            candidate = next((n.attrs.get('content', '') for n in root.all(tag='meta')
                              if n.attrs.get('property') == 'og:title'), '')
            # A verified own page can have a blank H1 but a specific property
            # title in its Open Graph metadata. Never use a generic site title.
            if re.search(type_pattern, candidate.split(',')[0], re.I):
                title = candidate.split(', Home2U')[0]
                fields['title_source'] = 'own og:title'
        price_raw = text(info.find(cls='section__head-price').find(tag='h2')) if info.find(cls='section__head-price') else ''
        if re.search(r'продаден|отдаден|резервиран', title, re.I):
            return skip('unavailable', ref, canonical, location)
        if RANGE.search(price_raw) or RANGE.search(fields.get('Площ в квадратни метри', '')):
            return skip('project', ref, canonical, location)
        kind, rooms = kind_of(title)
        content = text(info.find(cls='section__content'))
        known_kinds = set(ROOM_NAMES.values()) | {'Многостаен апартамент', 'Мезонет', 'Студио',
            'Апартамент', 'Къща', 'Парцел', 'Магазин', 'Промишлено помещение', 'Склад', 'Офис', 'Гараж'}
        # A recognised one-word heading (e.g. Парцел) equals its kind. It
        # must not be replaced with the first words of a description.
        if kind not in known_kinds and not re.search(type_pattern, title, re.I):
            content_kind, content_rooms = kind_of(content)
            kind, rooms = (content_kind, content_rooms) if content_kind in known_kinds else ('', None)
        notes = pet_fact(content)
        furnished = None
        if re.search(r'необзаведен|без обзавеждане', content, re.I):
            furnished = False
        elif re.search(r'напълно обзаведен|изцяло обзаведен', content, re.I):
            furnished = True
        if re.search(r'два работещи асансьора|с асансьор|има асансьор', content, re.I):
            notes += ' Асансьор.'
        photos = []
        gallery = root.find(cls='section-building-gallery')
        for img in gallery.all(tag='img') if gallery else []:
            src = img.attrs.get('data-lazy-src') or img.attrs.get('src', '')
            p = urlsplit(src)
            if p.scheme == 'https' and p.hostname == 'home2u.skyholding.media' and re.search(r'\.(jpg|jpeg|png|webp)$', p.path, re.I):
                photos.append(src)
        if not photos:
            for script in root.all(tag='script'):
                if script.attrs.get('type') != 'application/ld+json':
                    continue
                try:
                    data = json.loads(''.join(c for c in script.children if isinstance(c, str)))
                except ValueError:
                    continue
                graph = data.get('@graph', []) if isinstance(data, dict) else []
                for page in graph if isinstance(graph, list) else []:
                    if not isinstance(page, dict):
                        continue
                    if page.get('@type') != 'WebPage' or page.get('url') != canonical:
                        continue
                    src = page.get('thumbnailUrl', '')
                    if not isinstance(src, str):
                        continue
                    p = urlsplit(src)
                    if p.scheme == 'https' and p.hostname == 'home2u.skyholding.media' and re.search(r'\.(jpg|jpeg|png|webp)$', p.path, re.I):
                        photos.append(src)
        return result(ref, canonical, title=title, location=location, deal=deal, kind=kind,
            price_raw=price_raw, area=fields.get('Площ в квадратни метри'),
            bedrooms=rooms - 1 if rooms else None, floor=fields.get('Етаж'),
            fields=fields, photos=photos, notes=notes.strip(), furnished=furnished)


class Luximmo:
    slug, name, host = 'luximmo', 'LUXIMMO', 'www.luximmo.bg'
    hosts = (host, 'luximmo.bg', 'static.luximmo.org')
    # The agency's linked city catalogue includes all property kinds and both
    # deals. Each card's own URL identifies its deal; the detail breadcrumb
    # independently verifies it before any offer is stored.
    starts = {'all': 'https://www.luximmo.bg/bulgaria/oblast-sofiya/sofiya-luksozni-imoti/index.html'}
    apartment_starts = {deal: f'https://www.luximmo.bg/bulgaria/{path}-sofiya/apartamenti/index.html'
                       for deal, path in [('sale', 'prodajba'), ('rent', 'naem')]}

    def reference(self, url):
        match = re.search(r'/luksozen-imot-(\d+)-[^/]+\.html$', urlsplit(public_url(url, self.host)).path)
        if not match:
            raise ParseError('Not a verified LUXIMMO unit URL')
        return match[1]

    def catalogue(self, html, url, deal):
        url = public_url(url, self.host)
        first = self.starts.get(deal) or self.apartment_starts.get(deal)
        if not first:
            raise ParseError('Unknown catalogue scope')
        prefix = first.rsplit('/', 1)[0] + '/'
        if not re.fullmatch(re.escape(prefix) + r'index\d*\.html', url):
            raise ParseError('Not the verified Sofia catalogue')
        root = Tree(html).root
        wrapper = root.find(id='more-projects')
        count = text(root.find(cls='found-properties'))
        match = re.search(r'(\d[\d ]*)\s+оферти', count)
        if not wrapper or not match:
            raise ParseError('Missing own catalogue/count')
        rows = []
        for card in wrapper.all(cls='card'):
            link = card.find(cls='card-url')
            if not link:
                raise ParseError('Catalogue card without primary link')
            href = public_url(link.attrs['href'], self.host, url)
            own_deal = deal
            if deal == 'all':
                own_deal = 'sale' if '-za-prodajba-' in href else 'rent' if '-pod-naem-' in href else None
                if own_deal is None:
                    raise ParseError('Mixed catalogue card has no verified deal in its own URL')
            rows.append(dict(ref=self.reference(href), url=href, deal=own_deal))
        current = int(re.search(r'index(\d*)\.html$', url)[1] or 0)
        next_url = None
        pager = root.find(cls='pagination')
        for a in pager.all(tag='a') if pager else []:
            candidate = public_url(a.attrs.get('href', '#'), self.host, url)
            if candidate == prefix + f'index{current + 1}.html':
                next_url = candidate
        return dict(rows=rows, total=int(match[1].replace(' ', '')), next_url=next_url)

    def detail(self, html, url, deal):
        root = Tree(html).root
        canonical = own_canonical(root, url, self.host)
        ref = self.reference(canonical)
        content = root.find(id='content')
        specs = content.find(cls='scroll') if content else None
        pricing = content.find(id='panel_wrap') if content else None
        if not content or not specs:
            raise ParseError('Missing own specifications')
        fields = {}
        for row in specs.all(cls='grid-x'):
            cells = [c for c in row.children if isinstance(c, Node) and 'cell' in c.attrs.get('class', '').split()]
            if len(cells) == 2:
                fields[cells[0].text().rstrip(':')] = cells[1].text()
        location_node = next((n for n in content.all(cls='color-medium') if ' / ' in n.text()), None)
        place = text(location_node)
        location_parts = [s.strip() for s in place.split(' / ')]
        city = next((s for s in location_parts if s.startswith('ГР.') or s.startswith('С.')), '')
        quarter = next((s.removeprefix('КВ.').strip().title() for s in location_parts if s.startswith('КВ.')), '')
        location = ', '.join(filter(None, ['София', quarter]))
        # Numeric URL ID is distinct from the public marketing reference.
        favorite = content.find(cls='offer-fav')
        ids = [n.attrs.get('data-property-id') for n in content.all() if n.attrs.get('data-property-id')]
        if favorite and favorite.attrs.get('rel'):
            ids.append(favorite.attrs['rel'])
        if city != 'ГР. СОФИЯ':
            return skip('outside_city', ref, canonical, place)
        badges = ' '.join(n.text() for n in content.all(cls='badge')).casefold()
        gallery = content.find(id='g_container')
        availability = text(gallery.find(cls='band')) if gallery else ''
        if re.search(r'продаден|отдаден|резервиран|неактив|неактуал', badges + ' ' + availability, re.I):
            return skip('unavailable', ref, canonical, location)
        if ref not in ids:
            raise ParseError('Own source identity missing')
        if not pricing:
            raise ParseError('Missing own price')
        price_raw = text(pricing.find(cls='font-xlarge'))
        if RANGE.search(price_raw) or RANGE.search(fields.get('Обща площ', '').split('(')[0]):
            return skip('project', ref, canonical, location)
        breadcrumb = text(root.find(cls='breadcrumbs')).casefold()
        actual_deal = 'rent' if 'под наем' in breadcrumb else 'sale' if 'за продажба' in breadcrumb else None
        if actual_deal != deal:
            raise ParseError('Own breadcrumb deal does not match catalogue')
        kind, _ = kind_of(fields.get('Тип', ''))
        photos = [n.attrs.get('data-src') for n in content.all(cls='offer-col-gall')
                  if urlsplit(n.attrs.get('data-src', '')).hostname == 'static.luximmo.org']
        if not photos:
            og = next((n.attrs.get('content', '') for n in root.all(tag='meta')
                       if n.attrs.get('property') == 'og:image'), '')
            parts = urlsplit(og)
            if parts.scheme == 'https' and parts.hostname == 'static.luximmo.org' and re.search(rf'T{ref}[_\.]', parts.path):
                photos.append(og)
        notes = 'Асансьор.' if fields.get('Асансьор') == 'да' else ''
        if 'акт 16' in badges:
            notes += ' Акт 16.'
        return result(ref, canonical, title=text(content.find(tag='h1')), location=location,
            deal=deal, kind=kind, price_raw=price_raw, area=fields.get('Обща площ'),
            bedrooms=fields.get('Спални'), floor=fields.get('Етаж'),
            fields=fields, photos=photos, notes=notes.strip())


class Arco:
    slug, name, host = 'arco-real-estate', 'ARCO Real Estate', 'www.arcoreal.bg'
    hosts = (host, 'arcoreal.bg')
    starts = {deal: 'https://www.arcoreal.bg/%D0%BE%D1%84%D0%B5%D1%80%D1%82%D0%B8?' + urlencode(dict(t=t, c=1))
              for deal, t in [('sale', 2), ('rent', 4)]}

    def reference(self, url):
        path = unquote(urlsplit(public_url(url, self.host)).path)
        match = re.fullmatch(r'/оферти/[^/]+-(\d+)', path)
        if not match:
            raise ParseError('Not a verified ARCO unit URL')
        return match[1]

    def catalogue(self, html, url, deal):
        url = public_url(url, self.host)
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        if unquote(parts.path) != '/оферти' or query.get('c') != ['1'] or query.get('t') != [str(2 if deal == 'sale' else 4)]:
            raise ParseError('Not the verified Sofia city filter')
        root = Tree(html).root
        count = re.search(r'Общо оферти:\s*(\d+)', text(root.find(cls='total')))
        if not count:
            raise ParseError('Missing own catalogue count')
        wrapper = root.find(cls='offers')
        if not wrapper:
            raise ParseError('Missing own catalogue results wrapper')
        rows = []
        for card in wrapper.all(cls='offer-box'):
            href = public_url(card.find(tag='a').attrs['href'], self.host, url)
            ref = self.reference(href)
            if f'offer-{ref}' not in card.attrs.get('class', '').split():
                raise ParseError('Card identity does not match URL')
            rows.append(dict(ref=ref, url=href, deal=deal))
        page = int(query.get('page', ['1'])[0])
        next_url = None
        pager = root.find(cls='paging')
        for a in pager.all(tag='a') if pager else []:
            if f'OffersControls.setPage({page + 1});' in a.attrs.get('onclick', ''):
                params = dict(t=2 if deal == 'sale' else 4, c=1, page=page + 1, limit=10)
                next_url = f'https://{self.host}{parts.path}?' + urlencode(params)
        # The site's pager rounds down and omits a final partial page. Its
        # own displayed result range still proves that more results remain.
        shown = re.search(r'Показани резултати:\s*(\d+)-(\d+)\s+от общо\s+(\d+)', text(pager))
        if shown and int(shown[3]) == int(count[1]) and int(shown[2]) < int(count[1]):
            size = int(query.get('limit', ['10'])[0])
            if int(shown[1]) == (page - 1) * size + 1:
                next_url = f'https://{self.host}{parts.path}?' + urlencode(dict(
                    t=2 if deal == 'sale' else 4, c=1, page=page + 1, limit=size))
        return dict(rows=rows, total=int(count[1]), next_url=next_url)

    def detail(self, html, url, deal):
        root = Tree(html).root
        canonical = own_canonical(root, url, self.host, og=True)
        ref = self.reference(canonical)
        own = root.find(cls='offer')
        info = own.find(cls='info') if own else None
        if not info or not re.search(r'Оферта №' + ref + r'(?!\d)', text(root.find(tag='title'))):
            raise ParseError('Primary listing identity missing')
        title = text(info.find(tag='h1'))
        fields = {}
        specs = info.find(cls='details')
        for row in specs.all(cls='row') if specs else []:
            label, value = row.find(cls='label'), row.find(cls='value')
            if label and value:
                fields[label.text()] = value.text()
        location = next((n.text() for n in info.all() if n.attrs.get('itemprop') == 'address'), '')
        if not location.startswith('София (град),'):
            return skip('outside_city', ref, canonical, location)
        location = location.replace('София (град)', 'София', 1)
        if re.search(r'продаден|отдаден|резервиран', title, re.I):
            return skip('unavailable', ref, canonical, location)
        actual_deal = 'sale' if title.startswith('Продава,') else 'rent' if title.startswith('Отдава под наем,') else None
        if actual_deal != deal:
            raise ParseError('Own title deal does not match catalogue')
        pricing = next((n for n in info.all() if n.attrs.get('itemprop') == 'price'), None)
        # First euro price, never the neighbouring BGN or price-per-m2 value.
        price_raw = text(pricing.find(tag='strong')) if pricing else ''
        if RANGE.search(price_raw) or RANGE.search(fields.get('Площ', '')):
            return skip('project', ref, canonical, location)
        kind, _ = kind_of(title.split(',', 2)[1].strip())
        photos = []
        gallery = own.find(cls='gallery')
        for a in gallery.all(tag='a') if gallery else []:
            match = re.search(r"selectImage\('([^']+)'\)", a.attrs.get('onclick', ''))
            if match and urlsplit(match[1]).path == '/image':
                photos.append(public_url(match[1], self.host))
        # The agency's own OG thumbnail is another size of the same gallery
        # photograph. It can survive a broken large-image rendition.
        image_ids = {parse_qs(urlsplit(p).query).get('id', [''])[0] for p in photos}
        og_image = next((n.attrs.get('content', '') for n in root.all(tag='meta')
                         if n.attrs.get('property') == 'og:image'), '')
        if og_image:
            image_url = public_url(og_image, self.host, canonical)
            parts = urlsplit(image_url)
            if parts.path == '/image' and parse_qs(parts.query).get('id', [''])[0] in image_ids:
                photos.append(image_url)
        notes = ' '.join(f'{k}: {v}.' for k, v in fields.items() if k in ('Етап на строителство', 'Отопление'))
        return result(ref, canonical, title=title, location=location, deal=deal, kind=kind,
            price_raw=price_raw, area=fields.get('Площ'), bedrooms=fields.get('Спални'),
            floor=fields.get('Етаж'), fields=fields, photos=photos, notes=notes)


ADAPTERS = {adapter.slug: adapter for adapter in (Yavlena(), Home2U(), Luximmo(), Arco())}
