# -*- coding: utf-8 -*-
"""Turn 30 differently-shaped agency price lists into one canonical offer schema.

The hard parts, and how they are handled:

* Headers sit anywhere in the first ~15 rows, in 4 languages  -> scored header
  detection against a multilingual alias table (vocab.FIELD_ALIASES).
* A bare row like "БУРГАС" or "1 BEDS" is a *section* whose meaning carries down
  to the rows beneath it -> section-context tracking, classified as location or
  type via the gazetteer.
* The same sheet repeats its header for every section -> repeated headers are
  detected and skipped rather than parsed as offers.
* Values are free text: "140 000", "5 евро/м2", "0.03", "3 000 евро", "1 спалня"
  -> dedicated parsers per field, each keeping the raw string for audit.
* Some columns lie (a FLOOR holding 46274, an Excel date serial) -> per-field
  sanity ranges; out-of-range values are quarantined into `data_flags` instead
  of silently poisoning the database.
"""
import hashlib, json, re, sys, unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import vocab
from xlsx_reader import read_workbook, idx_to_col

ROOT = Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------- text utils
def norm_text(s):
    if s is None:
        return ''
    s = unicodedata.normalize('NFKC', str(s)).replace(' ', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def key(s):
    """Aggressive fold used for header/alias matching."""
    s = norm_text(s).lower()
    return re.sub(r'[^\wЀ-ӿ€²]+', ' ', s).strip()


def _num(s):
    """First number in a string: '140 000 \u20ac' -> 140000.0, '30 000\u0415\u0432\u0440\u043e' -> 30000.0

    Thousands separators may be a plain space, a non-breaking space, a thin
    space, a dot or a comma, and the number is often glued to Cyrillic text, so
    the lookahead must not rely on a word boundary (Cyrillic letters are word
    characters, so "000\u0415\u0432\u0440\u043e" has no boundary after the digits).
    """
    if s is None or s == '':
        return None
    t = norm_text(s)
    for ch in ('\u00a0', '\u2009', '\u202f', '\u2007'):
        t = t.replace(ch, ' ')
    t = re.sub(r'(?<=\d)[ .](?=\d{3}(?!\d))', '', t)   # 30 000 / 140.000
    t = re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', t)      # 1,250,000
    m = re.search(r'-?\d+(?:[.,]\d+)?', t)
    if not m:
        return None
    try:
        return float(m.group().replace(',', '.'))
    except ValueError:
        return None


# ------------------------------------------------------------- field parsers
PRICE_STATUS = ['стоп', 'stop', 'продано', 'продадено', 'sold', 'резерв', 'reserved',
                'депозит', 'капаро', 'договаряне', 'по договаряне', 'запитване', 'on request']


def price_is_status(raw):
    t = key(raw)
    return bool(t) and any(w == t or (len(t) < 20 and w in t) for w in PRICE_STATUS)


def parse_price(raw):
    if price_is_status(raw):
        return None, None          # handled as a status, not a parse failure
    v = _num(raw)
    if v is None:
        return None, None
    t = key(raw)
    if 'лв' in t or 'bgn' in t:                                 # leva -> euro
        v = round(v / 1.95583)
    if 0 < v < 1000 and re.search(r'\d\s*(k|к)\b', t):          # "95k"
        v *= 1000
    return (v, 'ok') if 3000 <= v <= 15_000_000 else (None, f'price out of range: {raw}')


def parse_area(raw):
    v = _num(raw)
    if v is None:
        return None, None
    return (v, 'ok') if 8 <= v <= 3000 else (None, f'area out of range: {raw}')


def parse_floor(raw):
    t = norm_text(raw)
    if not t:
        return None, None
    low = key(t)
    if any(w in low for w in ['партер', 'ground', 'parter']):
        return 0, 'ok'
    v = _num(t)
    if v is None:
        return None, None
    if -2 <= v <= 40:
        return int(v), 'ok'
    if 40000 <= v <= 60000:        # Excel date serial: a completion date, not a floor
        return None, f'date:{_serial_date(v)}'
    return None, f'floor implausible: {raw}'


def _serial_date(v):
    from datetime import datetime, timedelta
    try:
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).date().isoformat()
    except Exception:
        return None


def parse_bedrooms(type_raw, complex_raw='', section_type=''):
    """Bedrooms, honouring the BG/RU 'двустаен = 1 bedroom' convention."""
    for src in (type_raw, section_type, complex_raw):
        t = key(src)
        if not t:
            continue
        for words, n in vocab.TYPE_BEDROOMS:
            if any(w in t for w in words):
                return n, 'ok'
        m = re.search(r'(\d+)\s*[-\s]?\s*(спалн\w*|спальн\w*|bedroom\w*|bed\b|beds\b|br\b)', t)
        if m:
            n = int(m.group(1))
            if 0 <= n <= 10:
                return n, 'ok'
        m = re.search(r'(\d+)\s*[-\s]?\s*(стаен|стаян|комнат\w*|room\w*|zimmer)', t)
        if m:
            n = int(m.group(1))
            if 1 <= n <= 10:
                return max(n - 1, 0), 'ok'      # 3-стаен / 3-комнатная = 2 bedrooms
        m = re.match(r'^(\d+)(?:\.0)?$', norm_text(src))        # bare "2" / "7.0"
        if m:
            n = int(m.group(1))
            if 0 <= n <= 10:
                # a bare room count is rooms, not bedrooms, when the header said "комнат"
                return n, 'ok'
    return None, None


def parse_property_kind(type_raw, complex_raw='', notes=''):
    t = ' '.join(key(x) for x in (type_raw, complex_raw, notes))
    for w in vocab.PARKING_WORDS:
        if w in t:
            return 'parking'
    for kind, words in vocab.KIND_WORDS.items():
        if any(w in t for w in words):
            return kind
    return 'apartment'


def parse_deal_type(*raws):
    """Sale or rent. The price lists mix both, and a EUR 5,000 'price' is a
    monthly rent or a parking space, not a flat - keeping them apart stops the
    cheap end of every sorted list from being nonsense."""
    for raw in raws:
        t = key(raw)
        if t and any(w in t for w in vocab.RENT_WORDS):
            return 'rent'
    return 'sale'


def parse_commission(raw):
    """-> (value, kind, note). kind is 'percent' | 'eur'."""
    t = norm_text(raw)
    if not t or t in ('-', '0'):
        return None, None, None
    low = key(t)
    if 'без' in low or 'no comm' in low:
        return 0, 'eur', 'no commission'
    v = _num(t)
    if v is None:
        return None, None, t or None
    if '%' in t:
        return (v * 100 if v < 1 else v), 'percent', None
    if 0 < v < 1:                       # Excel percent format: 0.03 -> 3 %
        return round(v * 100, 2), 'percent', None
    if 1 <= v <= 30 and not re.search(r'(евро|eur|€|лв)', low):
        return v, 'percent', None       # bare "3" in a commission column
    if v >= 100:
        return v, 'eur', None
    return v, 'eur', None


COMM_IN_TEXT = re.compile(
    r'(?:коми[сc]+и\w*|comm?is+ion\w*)[^0-9%]{0,12}([\d  .,]{2,12})\s*(%|евро|eur|€)?'
    r'|([\d  .,]{2,12})\s*(%|евро|eur|€)\s*(?:коми[сc]+и\w*|comm?is+ion\w*)',
    re.IGNORECASE)


def parse_commission_from_text(text):
    """Recover a commission buried in a free-text notes column,
    e.g. '2 500 евро комиссия' or 'commission 3%'."""
    t = norm_text(text)
    if not t:
        return None, None, None
    m = COMM_IN_TEXT.search(t)
    if not m:
        return None, None, None
    num = m.group(1) or m.group(3)
    unit = (m.group(2) or m.group(4) or '').lower()
    v = _num(num)
    if v is None:
        return None, None, None
    if unit == '%' or (v <= 30 and not unit):
        return (v, 'percent', t)
    return (v, 'eur', t) if v >= 100 else (None, None, None)


def parse_maintenance(raw):
    """-> (eur_per_year, per_m2_rate, raw)"""
    t = norm_text(raw)
    if not t or t in ('-', '0'):
        return None, None, t or None
    low = key(t)
    v = _num(t)
    if v is None:
        return None, None, t
    if re.search(r'(м2|m2|кв\s?м|м²|кв/м)', low):
        return None, v, t               # rate per m², annualised later with area
    if v < 60:                          # bare small number in a "такса" column = €/m²
        return None, v, t
    return v, None, t


def parse_yesno(raw):
    t = key(raw)
    if not t:
        return None
    if any(w in t for w in vocab.NO) and not any(w in t for w in ['нови мебели', 'има']):
        return False
    if any(w in t for w in vocab.YES):
        return True
    return None


def parse_status(*raws):
    for raw in raws:
        t = key(raw)
        if not t:
            continue
        for words, st in vocab.STATUS_MAP:
            if any(w in t for w in words):
                return st
    return 'active'


LOC_LOOKUP = [(key(alias), canon) for canon, aliases in vocab.LOCATIONS.items() for alias in aliases]
LOC_LOOKUP.sort(key=lambda x: -len(x[0]))


def parse_location(*raws):
    for raw in raws:
        t = key(raw)
        if not t or re.fullmatch(r'[\d.,\s]+', t):
            continue
        for alias, canon in LOC_LOOKUP:
            if alias in t:
                return canon, norm_text(raw)
    for raw in raws:
        t = norm_text(raw)
        if t and not re.fullmatch(r'[\d.,\s]+', t):
            return None, t
    return None, None


def classify_section(text):
    """A lone label row: is it a location group or a property-type group?"""
    t = key(text)
    if not t or len(t) > 60:
        return None, None
    loc, _ = parse_location(text)
    if loc:
        return 'location', loc
    if any(w in t for w in vocab.TYPE_SECTIONS):
        return 'type', norm_text(text)
    return None, None


# ------------------------------------------------------------ header mapping
def fuzzy(s):
    """Collapse doubled letters so 'COMMISION' and 'COMMISSION' fold together."""
    return re.sub(r'(.)\1+', r'\1', key(s))


ALIAS_INDEX = []
for field, aliases in vocab.FIELD_ALIASES.items():
    for a in aliases:
        ALIAS_INDEX.append((key(a), field))
ALIAS_INDEX.sort(key=lambda x: -len(x[0]))
FUZZY_INDEX = sorted({(fuzzy(a), f) for a, f in ALIAS_INDEX}, key=lambda x: -len(x[0]))

# fields where a false positive is costly, so only an (almost) exact hit counts
STRICT = {'price', 'commission', 'maintenance', 'area', 'floor', 'price_m2'}


def match_header_cell(text):
    k = key(text)
    if not k or len(k) > 60:
        return None
    for alias, field in ALIAS_INDEX:
        if k == alias:
            return field
    for alias, field in ALIAS_INDEX:
        if len(alias) < 3:
            continue
        if field in STRICT:
            if re.search(r'(^|\W)' + re.escape(alias) + r'(\W|$)', k):
                return field
        elif alias in k:
            return field
    fk = fuzzy(text)
    for alias, field in FUZZY_INDEX:
        if len(alias) >= 5 and alias == fk:
            return field
    return None


EXACT_ALIASES = {a for a, _ in ALIAS_INDEX}


def is_header_row(row):
    """True when the row is a second header rather than an offer.

    Matching must be *exact* per cell and needs two or more hits: a substring
    test would throw away every real offer whose type is 'апартамент', because
    that word is also a header alias for the complex column.
    """
    hits = sum(1 for c in row if key(c) in EXACT_ALIASES)
    return hits >= 2 and not any(_num(c) and (_num(c) or 0) > 3000 for c in row)


def score_header(row):
    mapping, hits = {}, 0
    for i, cell in enumerate(row):
        f = match_header_cell(cell)
        if f and f not in mapping.values():
            mapping[i] = f
            hits += 1
    bonus = sum(2 for f in ('price', 'complex', 'area') if f in mapping.values())
    return hits + bonus, mapping


# --- content probes: what does a column of values actually look like? -------
def _looks_type(vals):
    hits = 0
    for v in vals:
        t = key(v)
        if any(w in t for words, _ in vocab.TYPE_BEDROOMS for w in words) or \
           any(w in t for words in vocab.KIND_WORDS.values() for w in words):
            hits += 1
    return hits / max(len(vals), 1)


VIEW_WORDS = ['море', 'sea', 'градина', 'сад', 'двор', 'басейн', 'бассейн', 'pool', 'улица',
              'street', 'парк', 'park', 'планина', 'mountain', 'город', 'град', 'city',
              'panorama', 'панорама', 'garden', 'yard', 'лес', 'north', 'south', 'east', 'west']


def _looks_view(vals):
    hits = sum(1 for v in vals if any(w in key(v) for w in VIEW_WORDS))
    return hits / max(len(vals), 1)


def _looks_price(vals):
    ok = sum(1 for v in vals if (lambda n: n is not None and 3000 <= n <= 15_000_000)(_num(v)))
    return ok / max(len(vals), 1)


def _column_values(rows, start, col, limit=25):
    out = []
    for _, r in rows[start:]:
        if col < len(r) and norm_text(r[col]):
            out.append(norm_text(r[col]))
        if len(out) >= limit:
            break
    return out


AMBIGUOUS = {'type', 'view'}


def refine_mapping(colmap, rows, hidx):
    """Header text alone is not enough: 'Вид' means *view* in Russian sheets and
    *type* in Bulgarian ones. Decide from the values actually in the column."""
    cands = [c for c, f in colmap.items() if f in AMBIGUOUS]
    if not cands:
        return colmap
    scored = {}
    for c in cands:
        vals = _column_values(rows, hidx + 1, c)
        scored[c] = (_looks_type(vals), _looks_view(vals))
    colmap = dict(colmap)
    best_type = max(cands, key=lambda c: scored[c][0], default=None)
    best_view = max(cands, key=lambda c: scored[c][1], default=None)
    if best_type is not None and scored[best_type][0] >= 0.4:
        for c in cands:
            if colmap.get(c) == 'type' and c != best_type:
                colmap[c] = 'view' if scored[c][1] > 0.3 else 'notes_extra'
        colmap[best_type] = 'type'
    if best_view is not None and best_view != best_type and scored[best_view][1] >= 0.4:
        colmap[best_view] = 'view'
    return colmap


def find_header(rows, scan=25):
    best = (0, {}, None)
    for i, row in enumerate(rows[:scan]):
        sc, mapping = score_header(row)
        if sc > best[0]:
            best = (sc, mapping, i)
    return best  # (score, {col_idx: field}, row_idx)


# ------------------------------------------------------------------ the sheet
URL_RE = re.compile(r'https?://\S+')

# default worksheet names in the locales these files come from - never a title
GENERIC_TABS = {'лист', 'sheet', 'tabelle', 'tabellenblatt', 'hoja', 'feuil', 'страница',
                'прайс', 'pricelist', 'прайслист', 'price', 'таблица', 'list'}


def is_generic_tab(name):
    """'Лист1', 'Sheet 2', 'Tabellenblatt2' are default worksheet names, not
    building names - a trailing index and any spacing are ignored."""
    t = re.sub(r'[\s\d]+', '', key(name))   # 'ПРАЙС ЛИСТ' -> 'прайслист'
    return t in GENERIC_TABS

# tracking/session noise that makes one unchanged link look like a new one
_DRIVE_USER = re.compile(r'/u/\d+/')
_NOISE_PARAMS = ('usp', 'st', 'rlkey', '_ga', 'fbclid', 'dl', 'e', 'ouid', 'sd', 'rtpof')


def canonical_url(url):
    """Same folder, same string.

    Google rewrites Drive links with the signed-in user's index (/u/0/, /u/6/)
    and Dropbox appends a rotating `st=` token, so the raw strings drift between
    crawls and every offer would report a 'photos link changed' forever.
    """
    if not url:
        return None
    url = url.strip()
    if 'google.com' in url:
        url = _DRIVE_USER.sub('/', url)     # /drive/u/0/folders -> /drive/folders
    if '?' in url:
        base, _, qs = url.partition('?')
        keep = [kv for kv in qs.split('&')
                if kv and kv.split('=')[0].lower() not in _NOISE_PARAMS]
        url = base + ('?' + '&'.join(keep) if keep else '')
    return url.rstrip('/?&') or None


def extract_offers(slug, agency, xlsx_path, snapshot_date):
    wb = read_workbook(xlsx_path)
    offers, diagnostics = [], []
    for sheet in wb['sheets']:
        if sheet['hidden']:
            continue
        grid = sheet['grid']
        rows = [(i, r) for i, r in enumerate(grid) if any(norm_text(c) for c in r)]
        if len(rows) < 3:
            continue
        score, colmap, hidx = find_header([r for _, r in rows])
        if score < 5 or not colmap:
            diagnostics.append({'slug': slug, 'tab': sheet['name'], 'issue': 'no header found',
                                'score': score, 'rows': len(rows)})
            continue
        colmap = refine_mapping(colmap, rows, hidx)
        header_sig = key(' '.join(rows[hidx][1]))
        inv = {v: k for k, v in colmap.items()}
        # a tab named "Summer Ravda" / "Villa Margarita Святой Влас" carries the
        # location (and often the complex) that the columns never state
        tab_loc, _ = parse_location(sheet['name'])
        tab_title = norm_text(sheet['name']) if 'complex' not in colmap.values() else None
        if tab_title and is_generic_tab(tab_title):
            tab_title = None      # 'Лист1' / 'Sheet1' is not a building name
        section_loc, section_type = None, None
        n_before = len(offers)

        for pos, (gridrow, row) in enumerate(rows):
            if pos <= hidx:
                continue
            filled = [c for c in row if norm_text(c)]
            if not filled:
                continue
            # a repeated header for the next section
            if key(' '.join(row)) == header_sig or score_header(row)[0] >= score - 1:
                continue
            # a lone label = section context
            if len(filled) <= 2:
                kind, val = classify_section(' '.join(filled))
                if kind == 'location':
                    section_loc, section_type = val, None
                elif kind == 'type':
                    section_type = val
                continue

            def cell(field):
                i = inv.get(field)
                return norm_text(row[i]) if i is not None and i < len(row) else ''

            def link(field):
                i = inv.get(field)
                if i is None:
                    return ''
                ref = f'{idx_to_col(i)}{gridrow + 1}'
                url = sheet['links'].get(ref, '')
                if not url and i < len(row):
                    m = URL_RE.search(row[i])
                    url = m.group() if m else ''
                return url

            if is_header_row(row):
                continue          # a repeated/secondary header row, not an offer
            price, price_flag = parse_price(cell('price'))
            if price is None:                     # some sheets hide price in a €/m² column
                price, _ = parse_price(cell('price_m2') if not cell('price') else '')
            complex_name = cell('complex') or tab_title or cell('notes')
            if complex_name and re.fullmatch(r'[\d.,\s]+', complex_name):
                unit_code = re.sub(r'\.0$', '', complex_name)
                label = tab_title or norm_text(sheet['name']) or section_loc or ''
                complex_name = f'{label} — {unit_code}'.strip(' —') or None
            else:
                unit_code = None
            if price is None and not complex_name:
                continue

            area, area_flag = parse_area(cell('area'))
            floor, floor_flag = parse_floor(cell('floor'))
            beds, _ = parse_bedrooms(cell('type'), complex_name, section_type or '')
            comm_v, comm_kind, comm_note = parse_commission(cell('commission'))
            if comm_v is None:
                # several agencies bury it in a free-text notes column
                comm_v, comm_kind, _ = parse_commission_from_text(cell('notes'))
            maint_eur, maint_m2, maint_raw = parse_maintenance(cell('maintenance'))
            if maint_eur is None and maint_m2 and area:
                maint_eur = round(maint_m2 * area, 2)
            loc_canon, loc_raw = parse_location(cell('location'), section_loc or '',
                                                complex_name, tab_loc or '',
                                                agency.get('name', ''))
            if loc_canon is None and tab_loc:
                loc_canon = tab_loc
            status = parse_status(cell('status'), cell('price'), cell('notes'), complex_name)

            ready_date = None
            if floor_flag and floor_flag.startswith('date:'):
                ready_date, floor_flag = floor_flag[5:], None
            flags = [f for f in (price_flag, area_flag, floor_flag) if f and f != 'ok']

            rec = {
                'agency_slug': slug,
                'agency_name': agency['name'],
                'source_tab': sheet['name'],
                'source_row': gridrow + 1,
                'ref': cell('ref') or unit_code or None,
                'title': complex_name or None,
                'location': loc_canon,
                'location_raw': loc_raw,
                'price_eur': price,
                'price_raw': cell('price') or None,
                'bedrooms': beds,
                'type_raw': cell('type') or section_type or None,
                'property_kind': parse_property_kind(cell('type'), complex_name, cell('notes')),
                'deal_type': parse_deal_type(complex_name, cell('type'), cell('notes'),
                                             cell('deal'), sheet['name']),
                'area_m2': area,
                'floor': floor,
                'commission_value': comm_v,
                'commission_kind': comm_kind,
                'commission_raw': cell('commission') or None,
                'maintenance_eur': maint_eur,
                'maintenance_per_m2': maint_m2,
                'maintenance_raw': maint_raw,
                'view': cell('view') or None,
                'furnished': parse_yesno(cell('furnished')),
                'documents': cell('documents') or None,
                'status': status,
                'ready_date': ready_date,
                'commission_note': comm_note,
                'notes': cell('notes') or None,
                'listing_url': canonical_url(link('ref') or link('complex') or link('notes')),
                'photos_url': canonical_url(link('photos')),
                'video_url': canonical_url(link('video')),
                'data_flags': '; '.join(flags) or None,
                'snapshot_date': snapshot_date,
            }
            # A row carrying nothing but a complex name is not an offer. Some
            # sheets run a named block hundreds of rows past its last entry;
            # eurometr's 'Villa Maragrita' tab alone trails 37 of them.
            if (price is None and area is None and beds is None
                    and not valid_ref(rec['ref']) and floor is None
                    and not rec['notes'] and not rec['photos_url']):
                continue
            rec['price_per_m2'] = round(price / area) if price and area else None
            rec['fingerprint'] = fingerprint(rec)
            rec['weak_core'] = weak_core(rec)
            rec['dup_group'] = dup_group(rec)
            offers.append(rec)

        if len(offers) == n_before:
            diagnostics.append({'slug': slug, 'tab': sheet['name'],
                                'issue': 'header found but 0 offers parsed', 'score': score})
    return offers, diagnostics


# words that show up in a "ref" column but are a status, not an identifier
JUNK_REF = ['депозит', 'deposit', 'продано', 'продадено', 'sold', 'reserved', 'резерв',
            'нов', 'new', 'ref', 'id', 'свободно', 'активен', 'active', '-', 'капаро']


def valid_ref(ref):
    """An agency reference is only usable as identity if it looks like one.

    Several sheets put 'ДЕПОЗИТ' or 'REF -' in the ID column; treating those as
    identifiers silently merges every unrelated apartment that shares the word.
    """
    t = key(ref)
    if not t or len(t) < 3:
        return False
    if not re.search(r'\d', t):
        return False
    if t in JUNK_REF or any(t == j for j in JUNK_REF):
        return False
    stripped = re.sub(r'[a-zа-я\s.\-№#]+', '', t)
    return bool(stripped)


def identity_parts(rec):
    """-> (parts, strength). 'weak' identity has to include price, otherwise two
    different apartments in the same building collapse into one row."""
    if valid_ref(rec.get('ref')):
        return [f"ref:{key(rec['ref'])}"], 'ref'
    core = [
        key(rec.get('title') or ''),
        str(rec.get('bedrooms') if rec.get('bedrooms') is not None else ''),
        str(int(rec['area_m2']) if rec.get('area_m2') else ''),
        str(rec.get('floor') if rec.get('floor') is not None else ''),
        key(rec.get('location') or ''),
    ]
    # title + area + (floor or bedrooms) is enough to pin one unit down
    strong = bool(core[0]) and bool(core[2]) and (bool(core[3]) or bool(core[1]))
    if strong:
        return core, 'attributes'
    return core + [str(int(rec['price_eur'])) if rec.get('price_eur') else ''], 'weak'


def weak_core(rec):
    """A weak identity with the price taken back out.

    Price has to stay in the fingerprint of a thin row - nothing else tells two
    of them apart, and dropping it merges unrelated apartments, or splits the
    Bulgarian and English tabs of one sheet into two listings. The cost is that
    a price edit retires one identity and mints another. `db.sync_offers` uses
    this key to recognise that pair as one repriced offer instead.
    """
    parts, strength = identity_parts(rec)
    if strength != 'weak':
        return None
    return '|'.join([rec['agency_slug']] + parts[:-1])


def fingerprint(rec):
    """Stable identity for an offer across days.

    For strong identities price is deliberately excluded, so a price cut is
    recorded as a *change* to a known offer rather than as one offer vanishing
    and a new one appearing.
    """
    parts, strength = identity_parts(rec)
    rec['identity_strength'] = strength
    base = '|'.join([rec['agency_slug']] + parts)
    return hashlib.sha1(base.encode('utf-8')).hexdigest()[:16]


def dup_group(rec):
    """Cross-agency clustering key: the same physical apartment offered by
    several agencies. Agency is excluded on purpose - that is the whole point."""
    if not rec.get('title'):
        return None
    parts = [
        key(rec.get('location') or ''),
        re.sub(r'[^\wЀ-ӿ]+', '', key(rec['title']))[:24],
        str(rec.get('bedrooms') if rec.get('bedrooms') is not None else ''),
        str(round(rec['area_m2'] / 5) * 5 if rec.get('area_m2') else ''),   # 5 m² tolerance
        str(rec.get('floor') if rec.get('floor') is not None else ''),
    ]
    if sum(1 for p in parts if p) < 3:
        return None
    return hashlib.sha1('|'.join(parts).encode('utf-8')).hexdigest()[:16]
