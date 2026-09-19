# -*- coding: utf-8 -*-
"""Where each agency's LIVE stock comes from, and how fresh it is.

Sitemaps are archives and this project stopped using them. Measured on 18.09.2026:

    titan-properties   6 707 sitemap URLs  ->    85 live Varna properties
    home2u             9 927 sitemap URLs  ->  the first 136 in order were all dead
    nov-dom-1            960 sitemap URLs  ->  2 683 in the live API

The sitemap is not a smaller version of the catalogue, it is a different thing:
everything the site ever published, with no way to tell live from sold short of
downloading it. Crawling one means fetching thousands of dead pages from
somebody else's server to learn they are dead. The catalogue is what the agency
is advertising right now, and the agency keeps it accurate for free.

Each agency gets the cheapest source that is actually live, in this order:

    json    a private API returning structured records -- one request, no HTML
    wp      WordPress REST, paginated, orderable by date
    html    the agency's own catalogue pages, walked with their pagination

`newest_first` records whether that source can be asked for the newest listings
first. Where it is true, checking for new stock costs one request instead of a
full walk -- which is how this stays cheap once the first pass is done.
"""

SOURCES = {
    # One GET returns every property as JSON: price, area, floor, district,
    # dates and the main photo. cities_id=2 is Varna (verified by district
    # names in the payload). No per-listing fetch needed at all.
    'titan-properties': {
        'kind': 'json',
        'url': 'https://titanproperties.bg/ajax/search_properties.php'
               '?lg=bg&limit=0&salesorrent_id={deal}',
        'deals': {1: 'sale', 2: 'rent'},
        'city_field': 'cities_id',
        'city_value': 2,
        'newest_first': True,
        'date_field': 'date_activation',
        'detail_url': 'https://titanproperties.bg/bg/imot/{slug}?id={id}',
        'image_field': 'pic',
        # The API returns bare filenames. /og/ is the large rendition, /sm/ the
        # thumbnail; read off a live detail page, not guessed.
        'image_base': 'https://titanproperties.bg/pic/properties/og/',
        'note': '1 864 records nationwide, 85 of them Varna. Sitemap claimed 6 707.',
    },
    # WordPress REST. orderby=date&order=desc gives newest first; X-WP-TotalPages
    # paginates. Varna is filtered after the fetch, on the location text.
    'nov-dom-1': {
        'kind': 'wp',
        'base': 'https://novdom1.bg',
        'rest_base': 'imot',
        'newest_first': True,
        'note': 'REST reports 2 683 items against 960 in the sitemap.',
    },
    'demos-2000': {
        'kind': 'wp',
        'base': 'https://demos2000.com',
        'rest_base': 'properties',
        'newest_first': True,
        'note': 'Houzez. 102 items.',
    },
    # Catalogue walks: the agency's own index, with its own pagination.
    'roneva': {
        'kind': 'html',
        'catalog': 'https://www.roneva.bg/properties/',
        'page_param': '?p={n}',
        'max_page': 40,
        'include': '/property/',
        'newest_first': False,
        'note': 'Pagination linked up to page 40.',
    },
    'ekip-sart': {
        'kind': 'html',
        'catalog': 'https://ekipsart.com/property/',
        'page_param': 'page/{n}/',
        'max_page': 30,
        'include': '/property/',
        'newest_first': False,
        'note': '/page/N/ verified to return different listings.',
    },
    'sam-home': {
        'kind': 'html',
        'catalog': 'https://samhome.bg/bg/prodajbi',
        'page_param': '/page/{n}/',
        'max_page': 20,
        'include': '/bg/imoti/',
        'newest_first': False,
        'note': 'Pagination only partly confirmed; walk stops when nothing new.',
    },
    # The largest Varna source found so far, and the one this project was
    # warned about: a previous scraper in this family was written against
    # /realestates/newdev, which 404s, and shipped nothing. Every URL below was
    # read off a live page instead.
    #
    # Listings carry an unmistakable marker -- AD<digits>BG_ -- and the two
    # Varna catalogues paginate as index<N>.html: /Varna_property/ to page 14,
    # /Varna_city_property/ to page 159. At ~30 a page that is roughly 4 700
    # Varna listings.
    'bulgarian-properties': {
        'kind': 'html',
        'catalog': 'https://www.bulgarianproperties.com/Varna_city_property/',
        'extra_catalogs': ['https://www.bulgarianproperties.com/Varna_property/'],
        'page_param': 'index{n}.html',
        'max_page': 160,
        'include': 'AD',
        'include_re': r'AD\d+BG_',
        'newest_first': False,
        'note': 'Two Varna catalogues; listings live under other category paths '
                'but always carry AD<digits>BG_ in the filename.',
    },
}

# Still needs work before it can be crawled live.
PENDING = {
    'home2u':
        'Has a Varna-only catalogue at /nedvizhimi-imoti-varna/ but it renders '
        'through admin-ajax.php and no pagination parameter moved it. The AJAX '
        'action name still has to be read off the page. Its sitemap holds 9 927 '
        'URLs whose head is entirely dead, so it is not a substitute.',
}


def newest_first_agencies():
    """Sources that can be polled cheaply for new stock."""
    return sorted(s for s, cfg in SOURCES.items() if cfg.get('newest_first'))
