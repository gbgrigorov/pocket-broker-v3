# -*- coding: utf-8 -*-
"""Walking an agency's own catalogue instead of its sitemap.

The sitemap is a poor source: it is an archive. Measured across this registry it
was 71% sold at one agency and 99.7% sold at another, and every one of those
sold pages had to be downloaded before we could learn it was sold.

The catalogue is the opposite. It is what the agency is advertising right now,
so a sold flat simply is not in it -- there is nothing to fetch, nothing to
skip, and nothing to store. The agency does the filtering for us, and it keeps
doing it every day for free.

Pagination is discovered from the pages themselves rather than guessed: every
catalogue here links to its own later pages, several of them to the last one.
"""
import re
from urllib.parse import urljoin, urlsplit

from sourcing.web import fetch, sites

HREF = re.compile(r'href=["\']([^"\'>]+)["\']')
BASE = re.compile(r'<base[^>]+href=["\']([^"\']+)["\']', re.I)
PAGE = re.compile(r'(?:[?&]page=|[?&]p=|/page/|/p/)(\d{1,4})')
ASSET = re.compile(r'\.(?:png|jpe?g|gif|css|js|ico|svg|webp|pdf|zip|mp4)(?:\?|$)', re.I)

MAX_PAGES = 600            # a catalogue larger than this is a misconfiguration
BARREN_LIMIT = 3           # consecutive pages with nothing new ends the walk


def _same_host(url, host):
    return (urlsplit(url).hostname or '').lower().lstrip('.').endswith(host)


def _is_page_of(url, base):
    """A later page of this catalogue, rather than some other section."""
    base_path = urlsplit(base).path.rstrip('/')
    path = urlsplit(url).path.rstrip('/')
    if not (path == base_path or path.startswith(base_path + '/')):
        return False
    return bool(PAGE.search(url))


def discover(agency_slug, spec=None, log=None):
    """Every listing the agency is currently advertising. Returns {url: ''}.

    The return shape matches the sitemap discovery it replaces, so the crawler
    above it does not care which one produced the URLs.
    """
    spec = spec or sites.recipe(agency_slug)
    say = log or (lambda *a: None)
    entries = spec.get('catalog') or []
    if isinstance(entries, str):
        entries = [entries]

    listings, visited = {}, set()
    queue = list(entries)
    host = (urlsplit(entries[0]).hostname or '').lower().lstrip('www.') if entries else ''
    barren = 0

    while queue and len(visited) < MAX_PAGES:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)

        response = fetch.get(url)
        if response['status'] != 200:
            continue

        # A page may declare its own base for relative links. bratanov does,
        # and resolving against the current URL instead doubled every path.
        base_match = BASE.search(response['body'])
        base = urljoin(url, base_match.group(1)) if base_match else url

        before = len(listings)
        pages = []
        for raw in HREF.findall(response['body']):
            if raw.startswith(('mailto:', 'tel:', 'javascript:', '#')):
                continue
            link = urljoin(base, raw).split('#')[0]
            if ASSET.search(link) or not _same_host(link, host):
                continue
            if sites.is_listing(link, spec):
                listings.setdefault(link.rstrip('/') + '/' if spec.get('trailing_slash')
                                    else link, '')
            elif _is_page_of(link, entries[0]) and link not in visited:
                pages.append(link)

        # Breadth first, in page order, so a walk that is cut short still holds
        # the front of the catalogue rather than a random slice of it.
        for link in sorted(set(pages), key=_page_number):
            if link not in visited and link not in queue:
                queue.append(link)

        gained = len(listings) - before
        barren = barren + 1 if gained == 0 else 0
        if gained:
            say(f'    {url[-60:]} → +{gained} (общо {len(listings)})')
        if barren >= BARREN_LIMIT:
            say(f'    спиране: {BARREN_LIMIT} последователни страници без нови обяви')
            break

    say(f'    {len(visited)} страници от каталога → {len(listings)} обяви')
    return listings


def _page_number(url):
    match = PAGE.search(url)
    return int(match.group(1)) if match else 0
