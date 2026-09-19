# -*- coding: utf-8 -*-
"""Turning a sitemap into a list of listing URLs and their timestamps.

`lastmod` is the whole economy of this crawler. With it, a morning run is one
request per site plus the pages that actually changed. Without it, every run is
the full six thousand.

It is also not trustworthy on its own -- some CMSes bump it on every reindex --
so it decides only what to *fetch*. Whether anything actually changed is settled
downstream by comparing extracted fields.
"""
import re
import time

from sourcing.web import fetch, sites

LOC = re.compile(r'<loc>\s*(?:<!\[CDATA\[)?\s*(https?://[^<\]\s]+)', re.I)
URL_BLOCK = re.compile(r'<url>(.*?)</url>', re.S | re.I)
LASTMOD = re.compile(r'<lastmod>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)', re.I)


DOUBLED = re.compile(r'^https?://.*?(https?://)', re.I)


def clean(url):
    """Repair a malformed <loc>.

    One agency's sitemap emits its base twice --
    "https://site.bghttps://site.bg/flat-t114" -- which curl cannot resolve. The
    address after the second scheme is the real one.
    """
    url = url.strip()
    match = DOUBLED.search(url)
    if match:
        url = url[match.start(1):]
    return url.split('#')[0]


def _entries(xml):
    """[(url, lastmod)] from a urlset, keeping each URL with its own timestamp."""
    out = []
    for block in URL_BLOCK.findall(xml):
        loc = LOC.search(block)
        if not loc:
            continue
        mod = LASTMOD.search(block)
        out.append((clean(loc.group(1)), mod.group(1)[:32] if mod else ''))
    if not out:                                # a plain index with no <url> wrappers
        out = [(clean(url), '') for url in LOC.findall(xml)]
    return out


def discover(agency_slug, spec=None, log=None):
    """Every listing URL this agency publishes. Returns {url: lastmod}."""
    spec = spec or sites.recipe(agency_slug)
    found = {}
    say = log or (lambda *a: None)

    queue = list(spec['sitemaps'])
    seen_sitemaps = set()
    while queue:
        url = queue.pop(0)
        if url in seen_sitemaps:
            continue
        seen_sitemaps.add(url)

        # A sitemap that 500s is usually a site generating it on the fly and
        # timing out; bgpropertyinvest, the largest index in the registry, does
        # this most times it is asked. Backing off gets it.
        for attempt in range(4):
            response = fetch.get(url, timeout=60)
            if response['status'] == 200:
                break
            time.sleep(3 * (attempt + 1))
        if response['status'] != 200:
            say(f'    sitemap {url} → HTTP {response["status"]}')
            continue

        xml = response['body']
        if '<sitemapindex' in xml.lower():
            children = [u for u in LOC.findall(xml) if u not in seen_sitemaps]
            say(f'    индекс {url} → {len(children)} файла')
            queue.extend(children)
            continue

        entries = _entries(xml)
        listings = [(u, m) for u, m in entries if sites.is_listing(u, spec)]
        say(f'    {url} → {len(entries)} адреса, {len(listings)} обяви')
        for listing_url, lastmod in listings:
            found.setdefault(listing_url, lastmod)

    return found
