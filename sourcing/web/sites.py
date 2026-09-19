# -*- coding: utf-8 -*-
"""What each agency's site looks like, measured rather than assumed.

Every entry here was verified against the live site on 18.09.2026 -- see
docs/crawl-map.md for the reconnaissance it came from. An agency without an
entry is simply not crawled; guessing a listing path produces a crawl that
walks a site's blog and stores nothing.

`catalog`   the agency's own listing pages -- what it advertises today. Sold
            flats are not in it, so they are never fetched and never stored.
`sitemaps`  the archive index. Kept for reference; no longer walked.
`include`   a URL is a listing only if it matches one of these. A bare string
            is a substring test; a 're:' prefix makes it a regular expression.
`drop`      language duplicates to discard, so one flat is not stored six times
            in six languages. Whatever survives is the canonical URL.
`price_hints` site-specific patterns tried before the generic reader.
`deal_type` forced, for sites that are entirely rentals or entirely sales.
"""
import re

RECIPES = {
    'bgpropertyinvest-festival': {
        'catalog': ['https://bgpropertyinvest.com/search/sale'],
        'sitemaps': ['https://bgpropertyinvest.com/sitemap-properties.xml'],
        # /complex/ pages describe a building, not a flat for sale.
        'include': ['/bulgarian_properties/'],
    },
    'ibg-real-estate': {
        'catalog': ['https://ibgrealestates.com/properties/'],
        'sitemaps': ['https://ibgrealestates.com/property-sitemap.xml'],
        'include': ['/property/'],
    },
    'grand-estates-group': {
        'catalog': ['https://grandgroupbg.com/property/'],
        'sitemaps': ['https://grandgroupbg.com/property-sitemap.xml',
                     'https://grandgroupbg.com/property-sitemap2.xml',
                     'https://grandgroupbg.com/property-sitemap3.xml'],
        'include': ['/property/'],
        'drop': ['/bg/', '/en/'],
    },
    'premium-property': {
        'catalog': ['https://premiumpropertybg.com/property/'],
        'sitemaps': ['https://premiumpropertybg.com/property-sitemap.xml'],
        'include': ['/property/'],
        'drop': ['/en/'],
        # Houzez renders the asking price into its mortgage calculator, which is
        # the only place on the page it appears as bare digits.
        'price_hints': [r'id=["\']homePrice["\'][^>]*value=["\']([\d\s.,]+)["\']'],
    },
    'leo-castle': {
        'catalog': ['https://leocastle.ru/property/'],
        'sitemaps': ['https://leocastle.ru/wp-sitemap-posts-property-1.xml'],
        'include': ['/property/'],
    },
    'bulgarian-riviera': {
        'catalog': ['https://bulgarian-riviera.com/nedvizhimost'],
        'sitemaps': ['https://bulgarian-riviera.com/sitemap.xml?page=1',
                     'https://bulgarian-riviera.com/sitemap.xml?page=2'],
        'include': ['/nedvizhimost/'],
    },
    'bratanov': {
        'catalog': ['https://www.bratanov.bg/bg/estate/index/'],
        'sitemaps': ['https://www.bratanov.bg/sitemap.xml'],
        'include': ['/estate/view/'],
        'drop': ['/en/', '/ru/'],
    },
    'bolgarskiy-dom': {
        'catalog': ['https://bolgarskiydom.com/vtorichnaya-nedvizhimost/'],
        'sitemaps': ['https://bolgarskiydom.com/sitemap.xml'],
        'include': ['/vtorichnaia_nedvijimosti/'],
    },
    'resell-my-apartment': {
        'catalog': ['https://www.resellmyapartment.com/en/properties'],
        'sitemaps': ['https://www.resellmyapartment.com/sitemap_property.xml'],
        # Listings carry no path marker, but the catalogue links only listings.
        'include': [r're:^https://www\.resellmyapartment\.com/[a-z0-9-]{12,}$'],
    },
}

# Sites with a website we cannot yet index. Kept visible rather than forgotten.
NO_INDEX = {
    'property-group-easy-rentals':
        'sitemap-ът съдържа само страници на населени места, не обяви',
    'nils-ott': 'sitemap-ът съдържа само съдържателни страници',
    'five-homes': 'няма sitemap — обявите се стигат през менюто',
    'bg-home': 'sitemap-ът сочи към develop домейн на изпълнителя',
    'michael-properties': 'няма тип „обява“ и няма sitemap',
}

# Sites that answer automated requests with a block page or a login wall. Listed
# rather than silently omitted, because the right next step is a phone call to
# the agency, not a cleverer crawler.
BLOCKED = {
    'eurometr-mulgaria': 'Imperva — блокира автоматичен достъп на всеки адрес',
    'lodax-estate': 'Imperva — блокира автоматичен достъп',
    'optimus-estate': 'целият сайт е зад парола',
}


def recipe(slug):
    return RECIPES.get(slug)


def is_listing(url, spec):
    """Does this URL point at one property?"""
    for prefix in spec.get('drop', ()):
        path = url.split('//', 1)[-1]
        path = path[path.find('/'):] if '/' in path else '/'
        if path.startswith(prefix):
            return False
    rules = spec.get('include') or []
    if not rules:
        return True
    for rule in rules:
        if rule.startswith('re:'):
            if re.search(rule[3:], url):
                return True
        elif rule in url:
            return True
    return False
