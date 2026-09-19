# -*- coding: utf-8 -*-
"""What each Varna agency's site looks like, measured rather than assumed.

Every entry was written from a SiteProbe row -- a live fetch of a real page --
and never from a guess about how a site is laid out. `docs/crawl-map.md` is the
evidence; `manage.py probe_agencies` is how it is refreshed.

These are merged into sourcing.web.sites.RECIPES at app startup (see apps.py)
rather than edited into that vendored file, so the copy stays byte-identical to
broker-crm and `vendor_check` keeps working.

Recipe keys, as the vendored crawler reads them:
  catalog     listing index pages -- what to walk when there is no sitemap
  sitemaps    the archive index, walked with <lastmod> diffing
  include     a URL is a listing only if it matches one of these
  drop        prefixes to discard -- almost always language duplicates
  price_hints site-specific patterns tried before the generic reader
  deal_type   forced, for sites that are entirely sales or entirely rentals

And one of ours:
  image       extra regexes for the main photo, tried after og:image

THE LANGUAGE TRAP. Most of these agencies publish the same flat under two or
three language prefixes: titan-properties shows 6 707 URLs under /en/property/
and 3 348 under /bg/imot/, and home2u carries bg, ru and en copies of all 2 436
of its listings. Crawled naively that is the same apartment stored three times,
which is precisely the duplication this product exists to remove. One language
is canonical per site and the rest are dropped; Bulgarian wins where it exists.
"""

RECIPES = {
    # 6 707 URLs under /en/, 3 348 under /bg/. Bulgarian is canonical.
    'titan-properties': {
        'catalog': ['https://titanproperties.bg/bg/prodazhbi'],
        'sitemaps': ['https://titanproperties.bg/sitemap.xml'],
        'include': [r're:/bg/imot/[^/]+'],
        'drop': ['/en/', '/ru/'],
    },
    # WordPress. Also publishes /project/ pages -- building-level, and the
    # anchor phase 5b wants. Not crawled yet; recorded so it is not forgotten.
    'home2u': {
        'sitemaps': ['https://home2u.bg/sitemap_index.xml'],
        'include': [r're:/property/[^/]+'],
        'drop': ['/en/', '/ru/', '/property/page/'],
    },
    'nov-dom-1': {
        'catalog': ['https://novdom1.bg/imot/'],
        'sitemaps': ['https://novdom1.bg/sitemap_index.xml'],
        'include': [r're:/imot/[^/]+'],
        # /imot/page/111/ matches the include rule above, so without this the
        # walker files every pagination link as a listing and never follows it.
        'drop': ['/en/', '/ru/', '/imot/page/'],
    },
    'roneva': {
        'catalog': ['https://www.roneva.bg/properties/'],
        'sitemaps': ['https://www.roneva.bg/sitemap.xml'],
        'include': [r're:/property/[^/]+'],
        'drop': ['/property/page/'],
    },
    # /property/ and /en/property/ hold the same 232 listings.
    'ekip-sart': {
        'catalog': ['https://ekipsart.com/property/'],
        'sitemaps': ['https://ekipsart.com/sitemap-post-type-property.xml'],
        'include': [r're:/property/[^/]+'],
        'drop': ['/en/', '/ru/', '/property/page/'],
    },
    'demos-2000': {
        'catalog': ['https://demos2000.com/imot/'],
        'sitemaps': ['https://demos2000.com/property-sitemap.xml'],
        'include': [r're:/imot/[^/]+'],
        'drop': ['/imot/page/'],
    },
    'sam-home': {
        'sitemaps': ['https://samhome.bg/sitemap.xml'],
        'include': [r're:/bg/imoti/[^/]+'],
        'drop': ['/en/', '/ru/', '/de/'],
    },
}

# Catalogue URLs verified to 404 or to paginate invisibly. Recorded so the next
# person does not re-guess them: the first mapping run uses sitemaps, and these
# are the gap to close before switching to daily catalogue walks.
CATALOG_TODO = {
    'home2u': 'https://home2u.bg/prodazhbi/ → 404. Real catalogue URL unknown.',
    'sam-home': 'https://samhome.bg/bg/imoti → 404. Real catalogue URL unknown.',
    'titan-properties': '/bg/prodazhbi loads 10 listings and links no page 2 '
                        '— pagination is probably scripted.',
    'ekip-sart': '/property/ loads 8 listings and links no page 2.',
}

# Reachable, but no listing pattern we are willing to act on yet. Kept visible
# rather than forgotten -- each line is a piece of work, not a dead end.
NO_INDEX = {
    'bulgarian-properties':
        'Публикува /Varna_property/*/index.html, но само 4 URL-а бяха потвърдени. '
        'Сайтът, на който предишен scraper в това семейство беше написан срещу '
        '404 страници — не се пипа без ръчна проверка.',
    'yavlena':
        'Next.js; /en/rentals/* дава 59 865 URL-а за цяла България, не само Варна. '
        'Нужна е отделна рекогносцировка за филтър по град.',
    'votchina': 'Няма sitemap; обявите са зад търсачка на PHP.',
    'ekipat': 'Sitemap-ът дава категорийни страници (/prodava/*/varna), не обяви.',
    'matex': 'Няма sitemap; обявите се стигат само през adv_search.php.',
    'imoti-premier':
        'WP REST съобщава 11 973 обекта, но не бе потвърден шаблон за обява. '
        'Най-обещаващата следваща цел.',
    'topimmo': 'Намерени са само категорийни страници.',
    'express-imoti': 'Няма открит шаблон на обява.',
    'imotmedia': 'Няма открит шаблон на обява.',
    'invest-time': 'Sitemap-ът дава таксономии (/tip/*), не обяви.',
    'remax-active': 'Няма открит шаблон на обява.',
    'remax-dream': 'Няма открит шаблон на обява.',
    'imoten-centar': 'Домейнът не отговаря (DNS/TLS).',
}

# Sites that answer automated requests with a block page. Listed rather than
# worked around: the right next step is a phone call, not a cleverer crawler.
BLOCKED = {
    'adres': 'HTTP 403 на всяка заявка — блокира автоматичен достъп на ръба.',
    'imoteka': 'HTTP 403 на всяка заявка — блокира автоматичен достъп на ръба.',
}

# The main photo. og:image is tried first for every site and is usually right --
# it is what the agency itself nominates as the picture of this listing, which
# is exactly what "main image" means. These are per-site fallbacks.
IMAGE_HINTS = {
    'sam-home': [r'<img[^>]+class="[^"]*main-photo[^"]*"[^>]+src="([^"]+)"'],
    'titan-properties': [r'<img[^>]+id="main-image"[^>]+src="([^"]+)"'],
}
