# -*- coding: utf-8 -*-
"""Reconnaissance: what does this agency's site actually look like?

Rule 7 of docs/PLAN.md exists because a previous scraper in this family was
written against 404 pages served from a stale cache -- it "looked right and
parsed nothing". So nothing here infers structure. Every field this module
reports was read off a live response, and a page that did not come back 200 is
recorded as a failure rather than guessed around.

The output is docs/crawl-map.md and a SiteProbe row per agency. Recipes in
phase 3 are written from that, never from a hunch about how a site is laid out.
"""
import json
import re
import subprocess
import threading
import time
from urllib.parse import urljoin, urlsplit

from django.conf import settings

USER_AGENT = (
    'VarnaMarketBot/0.1 (+https://github.com/gbgrigorov/varna-market; '
    'aggregator recon; contact: gabriel.spmn@gmail.com)')
MAX_BYTES = 3_000_000

_locks, _last, _guard = {}, {}, threading.Lock()
_blocked = set()


def host_of(url):
    return (urlsplit(url).hostname or '').lower()


def _wait(host):
    """Never two requests to one host inside CRAWL_HOST_DELAY."""
    delay = float(getattr(settings, 'CRAWL_HOST_DELAY', 2.0))
    with _guard:
        lock = _locks.setdefault(host, threading.Lock())
    with lock:
        gap = time.monotonic() - _last.get(host, 0.0)
        if gap < delay:
            time.sleep(delay - gap)
        _last[host] = time.monotonic()


def get(url, timeout=None):
    """One request. Returns a dict; never raises for an HTTP error.

    A host that answers 429/503 is added to a run-local blocklist after
    CRAWL_BACKOFF_LIMIT strikes and is not contacted again this run. Being
    slow is cheap; being banned costs us the whole agency.
    """
    timeout = timeout or int(getattr(settings, 'CRAWL_TIMEOUT', 90))
    host = host_of(url)
    if host in _blocked:
        return {'ok': False, 'status': 0, 'error': 'host blocked earlier this run',
                'url': url, 'final_url': url, 'body': '', 'headers': {}}
    _wait(host)
    sep = '@@VM@@'
    proc = subprocess.run(
        ['curl', '-sSL', '-A', USER_AGENT, '--max-time', str(timeout), '--compressed',
         '--max-filesize', str(MAX_BYTES), '-D', '-',
         '-w', f'\n{sep}%{{http_code}}{sep}%{{url_effective}}{sep}%{{content_type}}', url],
        capture_output=True, text=True, errors='replace')
    raw = proc.stdout or ''
    if sep not in raw:
        return {'ok': False, 'status': 0, 'error': (proc.stderr or 'no response')[:200],
                'url': url, 'final_url': url, 'body': '', 'headers': {}}
    payload, status, final_url, ctype = raw.rsplit(sep, 3)
    status = int(status or 0)

    # curl -D - prefixes the body with the header block of every hop.
    headers, body = {}, payload
    while re.match(r'^HTTP/\d', body):
        head, _, body = body.partition('\r\n\r\n') if '\r\n\r\n' in body else body.partition('\n\n')
        for line in head.splitlines()[1:]:
            key, _, value = line.partition(':')
            if value:
                headers[key.strip().lower()] = value.strip()

    if status in (429, 503):
        strikes = _strike(host)
        if strikes >= int(getattr(settings, 'CRAWL_BACKOFF_LIMIT', 3)):
            _blocked.add(host)

    return {'ok': 200 <= status < 300, 'status': status, 'url': url,
            'final_url': final_url.strip(), 'content_type': ctype.strip(),
            'body': body, 'headers': headers, 'error': ''}


_strikes = {}


def _strike(host):
    _strikes[host] = _strikes.get(host, 0) + 1
    return _strikes[host]


# --------------------------------------------------------------- detection --

PLATFORMS = (
    ('WordPress', (r'/wp-content/', r'/wp-includes/', r'name="generator"[^>]*WordPress')),
    ('Houzez',    (r'houzez', )),
    ('Realhomes', (r'realhomes', )),
    ('Wix',       (r'wix\.com', r'_wixCssImports')),
    ('Joomla',    (r'/media/jui/', r'name="generator"[^>]*Joomla')),
    ('Drupal',    (r'/sites/default/files/', r'name="generator"[^>]*Drupal')),
    ('Shopify',   (r'cdn\.shopify\.com', )),
    ('Next.js',   (r'/_next/static/', )),
    ('Nuxt',      (r'/_nuxt/', )),
)


def detect_platform(body):
    found = [name for name, pats in PLATFORMS
             if any(re.search(p, body, re.I) for p in pats)]
    # Houzez and Realhomes are WordPress themes; naming the theme is more useful.
    if 'Houzez' in found or 'Realhomes' in found:
        found = [f for f in found if f != 'WordPress']
    return found


def detect_encoding(body, headers):
    meta = re.search(r'<meta[^>]+charset=["\']?\s*([\w-]+)', body, re.I)
    ctype = headers.get('content-type', '')
    declared = re.search(r'charset=([\w-]+)', ctype, re.I)
    return {
        'meta_charset': (meta.group(1).lower() if meta else None),
        'header_charset': (declared.group(1).lower() if declared else None),
    }


def parse_robots(text):
    """Every Disallow and every declared sitemap. Recorded, never obeyed."""
    disallow, sitemaps = [], []
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith('disallow:'):
            value = line.split(':', 1)[1].strip()
            if value:
                disallow.append(value)
        elif line.lower().startswith('sitemap:'):
            sitemaps.append(line.split(':', 1)[1].strip())
    return sorted(set(disallow)), sorted(set(sitemaps))


SITEMAP_GUESSES = (
    '/sitemap.xml', '/sitemap_index.xml', '/wp-sitemap.xml',
    '/sitemap-index.xml', '/sitemap/sitemap-index.xml',
)


def sitemap_urls(xml):
    """<loc> values, whichever kind of sitemap this is."""
    return re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', xml, re.I)


def is_index(xml):
    return '<sitemapindex' in xml.lower()


def url_shapes(urls, limit=12):
    """Group URLs by their path skeleton, so listing patterns stand out.

    /property/sunny-beach-flat -> /property/*   (2 341 urls)
    Digits and slugs collapse; what survives is the shape a recipe matches on.

    Returns (shape, count, samples). The samples are the point: a shape is a
    hypothesis, and phase 3 is not allowed to write a recipe until a real page
    behind one of these URLs has been fetched and confirmed to be a listing.
    """
    shapes, samples = {}, {}
    for url in urls:
        path = urlsplit(url).path
        parts = []
        for seg in path.strip('/').split('/'):
            if not seg:
                continue
            if re.fullmatch(r'\d+', seg) or len(seg) > 24 or re.search(r'\d{3,}', seg):
                parts.append('*')
            elif '-' in seg and len(seg) > 12:
                parts.append('*')
            else:
                parts.append(seg)
        shape = '/' + '/'.join(parts[:3])
        shapes[shape] = shapes.get(shape, 0) + 1
        samples.setdefault(shape, [])
        if len(samples[shape]) < 3:
            samples[shape].append(url)
    ordered = sorted(shapes.items(), key=lambda kv: -kv[1])[:limit]
    return [(shape, count, samples[shape]) for shape, count in ordered]


# A page is a property listing if it prices something and measures it. Both
# signals, not either: a news article about the market quotes prices too, which
# is exactly how a previous scraper in this family ended up parsing news.
PRICE_RE = re.compile(r'(?:€|EUR|лв\.?|BGN)\s*[\d\s.,]{3,}|[\d\s.,]{3,}\s*(?:€|EUR|лв\.?|BGN)', re.I)
AREA_RE = re.compile(r'\d[\d\s.,]*\s*(?:m2|m²|кв\.?\s*м|sq\.?\s*m|кв\.м)', re.I)
ROOMS_RE = re.compile(r'(едностаен|двустаен|тристаен|многостаен|мезонет|'
                      r'bedroom|спалн|студио|studio)', re.I)
# Only unambiguous news. An earlier version vetoed on `<article`, which every
# WordPress theme wraps its listings in -- that rejected four agencies whose
# pages were priced, measured and room-counted. The lesson is the same one rule
# 7 teaches: check the page before believing the heuristic.
NEWS_RE = re.compile(r'"@type"\s*:\s*"(NewsArticle|BlogPosting|Article)"', re.I)


def shape_of(url):
    """The skeleton of one URL, using the same rules as url_shapes."""
    parts = []
    for seg in urlsplit(url).path.strip('/').split('/'):
        if not seg:
            continue
        if re.fullmatch(r'\d+', seg) or len(seg) > 24 or re.search(r'\d{3,}', seg):
            parts.append('*')
        elif '-' in seg and len(seg) > 12:
            parts.append('*')
        else:
            parts.append(seg)
    return '/' + '/'.join(parts[:3])


# A detail page may link to a handful of similar properties; a catalogue links
# to a screenful. Counting prices cannot tell them apart -- a "related
# properties" carousel prices six flats and made titan-properties and roneva
# read as catalogues. Counting same-shape links can.
SIBLING_LIMIT = 9


def page_kind(body, shape=None, base=None):
    """What is this page: one property, a catalogue of them, or neither?

    The distinction matters because a recipe needs both, in different slots:
    catalogue URLs are what the crawler walks, detail URLs are what it stores.
    Conflating them produces a crawl that fetches index pages forever and
    ingests nothing.

    Returns (kind, why) where kind is 'detail', 'catalogue' or 'other'.
    """
    prices = PRICE_RE.findall(body)
    areas = AREA_RE.findall(body)
    has_rooms = bool(ROOMS_RE.search(body))
    newsy = bool(NEWS_RE.search(body))
    n_price, n_area = len(prices), len(areas)

    siblings = None
    if shape and base:
        siblings = sum(1 for url in links_on(body, base) if shape_of(url) == shape)

    why = (f'prices={n_price} areas={n_area} rooms={has_rooms} '
           f'siblings={siblings if siblings is not None else "n/a"} '
           f'news_markers={newsy}')

    if newsy:
        return 'other', why
    if not (n_price or n_area):
        return 'other', why

    priced_and_measured = bool(n_price and n_area)
    plausible = priced_and_measured or (n_price + n_area >= 1 and has_rooms)
    if not plausible:
        return 'other', why

    # A page that links to a screenful of its own siblings is an index of them.
    if siblings is not None:
        return ('catalogue' if siblings >= SIBLING_LIMIT else 'detail'), why

    # No shape to count against: fall back to volume, which is cruder.
    if n_price >= 10 and n_area >= 10:
        return 'catalogue', why
    return 'detail', why


def looks_like_listing(body, shape=None, base=None):
    """Is this one property? Catalogues do not count."""
    kind, why = page_kind(body, shape=shape, base=base)
    return kind == 'detail', why


def wp_types(base_url):
    """WordPress custom post types, which is where listings live if it is WP.

    Agencies put listings under `property`, `estate`, `imot`, `listing`... The
    REST index names them, so the type is read rather than guessed. ACF fields
    are usually NOT in REST (rule 6), so this tells us what to enumerate, not
    where the price is.
    """
    res = get(urljoin(base_url, '/wp-json/wp/v2/types'))
    if not res['ok']:
        return {}
    try:
        data = json.loads(res['body'])
    except (ValueError, TypeError):
        return {}
    out = {}
    for slug, meta in (data.items() if isinstance(data, dict) else []):
        if slug in ('post', 'page', 'attachment', 'nav_menu_item', 'wp_block',
                    'wp_template', 'wp_template_part', 'wp_navigation', 'wp_font_family',
                    'wp_global_styles', 'wp_font_face'):
            continue
        rest_base = (meta or {}).get('rest_base') or slug
        out[slug] = rest_base
    return out


def wp_count(base_url, rest_base):
    """How many items of that type exist, from the X-WP-Total header."""
    res = get(urljoin(base_url, f'/wp-json/wp/v2/{rest_base}?per_page=1'))
    if not res['ok']:
        return None
    total = res['headers'].get('x-wp-total')
    return int(total) if total and total.isdigit() else None


# ----------------------------------------------------------------- harvest --

LINK_RE = re.compile(r'<a\b[^>]*?href=["\']([^"\'#]+)', re.I)
SKIP_EXT = ('.css', '.js', '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg',
            '.pdf', '.zip', '.ico', '.woff', '.woff2', '.mp4', '.xml')


def links_on(body, base):
    """Same-host, same-document links, absolute and de-fragmented."""
    host = host_of(base)
    out = set()
    for href in LINK_RE.findall(body):
        href = href.strip()
        if not href or href.startswith(('mailto:', 'tel:', 'javascript:', 'data:')):
            continue
        url = urljoin(base, href)
        if host_of(url) != host:
            continue
        if urlsplit(url).path.lower().endswith(SKIP_EXT):
            continue
        out.add(url.split('#')[0])
    return out


def harvest(base, hints, max_pages=24, depth=2):
    """Breadth-first link harvest, for the many BG agency sites with no sitemap.

    Sitemaps are the cheap path and are tried first. When a site has none --
    which is common here, and not a reason to give up on an agency -- this
    walks a bounded number of its own pages and collects the URLs it links to,
    preferring pages whose own URL suggests a catalogue.

    Bounded on purpose: this is reconnaissance, not the crawl. It answers
    "what shape are the listing URLs" using a couple of dozen requests.
    """
    seen, collected, fetched = {base}, set(), 0
    frontier = [(base, 0)]
    while frontier and fetched < max_pages:
        url, level = frontier.pop(0)
        res = get(url)
        fetched += 1
        if not res['ok'] or 'html' not in res.get('content_type', ''):
            continue
        found = links_on(res['body'], res['final_url'] or url)
        collected |= found
        if level >= depth:
            continue
        # Follow catalogue-looking pages first; they are where listings hang.
        ranked = sorted(found, key=lambda u: 0 if any(
            h in u.lower() for h in hints) else 1)
        for link in ranked:
            if link not in seen and len(seen) < max_pages * 8:
                seen.add(link)
                frontier.append((link, level + 1))
    return collected, fetched
