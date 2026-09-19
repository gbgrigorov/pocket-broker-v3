# -*- coding: utf-8 -*-
"""Which Varna agencies we index, and on what evidence.

Admission is not a judgement call made per agency. It is one rule applied to
public evidence, so the list can be defended to an agency that asks why it is
not on it -- and published, which is the point.

ADMITTED when either holds:
  * a Google rating >= 4.0 with a review history behind it, or
  * membership of НСНИ (Национално сдружение Недвижими имоти), whose members
    accept a code of ethics and can be expelled under it.

EXCLUDED with the reason recorded. The exclusion list is part of the product:
"we left this one out, here is why" is the claim the whole thing rests on.

Ratings are a 2026 snapshot of Google review aggregates and are evidence for
admission, not a score we publish or rank by. `stock_hint` is a rough order of
magnitude from the agency's own portal pages, used only to notice when a crawl
returns far less than the site advertises.
"""

# name, slug, site, rating, reviews, nsni, since, note
AGENCIES = [
    # -- both signals: rating and НСНИ --------------------------------------
    ('RE/MAX Active', 'remax-active', 'https://active.remax.bg', 4.95, 91, True, None,
     'Албека ЕООД. RE/MAX franchise compliance on top of НСНИ.'),

    # -- strong rating, long record ----------------------------------------
    ('Матекс Имоти', 'matex', 'https://matex.bg', 4.85, 160, False, 2006,
     'Imoti.net „Агенция на годината“ 2019 -- the only BG award judging correctness.'),
    ('Ронева', 'roneva', 'https://www.roneva.bg', 5.00, 447, False, 2004,
     'ЕИК 202435373. Highest rating with real review volume behind it.'),
    ('Титан Пропъртис', 'titan-properties', 'https://titanproperties.bg', 4.90, 711, False, None,
     'Largest credible review base in the city. Varna office, national network.'),
    ('TOPIMMO', 'topimmo', 'https://topimmo.bg', 4.90, 156, False, None,
     'Publishes its fee schedule openly -- rare here, and a real trust signal.'),
    ('Home2U', 'home2u', 'https://home2u.bg', 4.70, 312, False, None, ''),
    ('Адрес', 'adres', 'https://address.bg', 4.70, 270, False, None,
     'National network, several Varna offices; best of them rate 4.7-5.0.'),
    ('Купи в България', 'kupi-v-bulgaria', 'https://kupiv.bg', 4.70, 226, False, None,
     'Strong with foreign buyers and coastal stock.'),
    ('Имотека', 'imoteka', 'https://imoteka.bg', 4.80, 188, False, None,
     'National network, standardised contracts.'),
    ('Експрес Имоти', 'express-imoti', 'https://www.expressimoti.bg', 4.95, 74, False, None, ''),
    ('Имотен център Варна', 'imoten-centar', 'https://icentervarna.bg', 4.90, 75, False, None, ''),
    ('АН Вотчина', 'votchina', 'https://votchina.eu', 5.00, 69, False, None,
     '15 years; reputation with international buyers on legal diligence.'),
    ('Арена Консулт', 'arena-konsult', None, 4.90, 100, False, None, ''),
    ('Bulgaria Avenue', 'bulgaria-avenue', None, 5.00, 154, False, None, ''),
    ('Admiral Real Estate', 'admiral', None, 4.60, 321, False, None,
     'Office and commercial rentals rather than residential sale.'),
    ('Home Place Properties', 'home-place', None, 4.60, 127, False, None, ''),
    ('XNVD', 'xnvd', None, 4.50, 130, False, None, ''),
    ('Нов Дом 1', 'nov-dom-1', 'https://novdom1.bg', 4.20, 130, True, 2011,
     'НСНИ member. Two Varna offices; ~440 sale listings on its portal page.'),
    ('Явлена', 'yavlena', 'https://yavlena.com', 4.00, 105, False, None,
     'Large national brand; the weakest local rating we admit.'),

    # -- НСНИ members, thin public review history --------------------------
    ('Сам Хоум', 'sam-home', 'https://samhome.bg', None, None, True, None, ''),
    ('RE/MAX Ideal', 'remax-ideal', None, None, None, True, None, ''),
    ('RE/MAX Dream', 'remax-dream', 'https://dream.remax.bg', None, None, True, None, ''),
    ('Темпо Естейт', 'tempo-estate', None, None, None, True, 2019,
     'НСНИ member since 2019. No website of its own found -- lists via portals only.'),
    ('Екип SART', 'ekip-sart', 'https://ekipsart.com', None, None, True, None,
     'Свилен Пропъртис ЕООД.'),
    ('Имотмедия', 'imotmedia', 'https://imotmedia.bg', None, None, True, None, ''),
    ('Имоти Дар', 'imoti-dar', None, None, None, True, None, ''),

    # -- long record, admitted on tenure -----------------------------------
    ('Демос-2000', 'demos-2000', 'https://demos2000.com', None, None, False, 1993,
     'Longest continuous operation in Varna; founder has traded through every crash.'),
    ('Invest Time', 'invest-time', 'https://investtime.bg', None, None, False, 1995,
     '30 years in the Varna market.'),
    ('Екипът', 'ekipat', 'https://ekipat.bg', None, None, False, None, ''),
    ('Имоти Премиер', 'imoti-premier', 'https://imotipremier.com', None, None, False, None, ''),

    # -- national, deep Varna coverage -------------------------------------
    ('Bulgarian Properties', 'bulgarian-properties', 'https://www.bulgarianproperties.com',
     None, None, False, None,
     'National. Publishes project-level pages, so a first-class source for '
     'project clustering. See the rule-7 warning in docs/crawl-map.md before '
     'writing a single line of parser for this site.'),
]

# slug -> why we do not index it. Published.
EXCLUDED = {
    'revolution-estate':
        'Google 2.95 across 2 644 reviews, and listed on the brokers\' blacklist '
        'for false advertisements, unanswered calls, callbacks from unlisted '
        'numbers and undisclosed commissions. The most visible agency in Varna '
        'and the least trustworthy -- marketing volume is not a trust signal.',
}


def rows():
    """The registry as dicts, admission rule applied and recorded."""
    out = []
    for name, slug, site, rating, reviews, nsni, since, note in AGENCIES:
        if nsni:
            basis = 'НСНИ member'
        elif rating is not None:
            basis = f'Google {rating:.2f} ({reviews} reviews)'
        elif since:
            basis = f'trading since {since}'
        else:
            basis = 'unverified'
        out.append({
            'name': name, 'slug': slug, 'website': site,
            'rating': rating, 'reviews': reviews, 'nsni': nsni,
            'since': since, 'note': note, 'admission_basis': basis,
        })
    return out


def unverified():
    """Admitted agencies whose website we have not yet found."""
    return [r for r in rows() if not r['website']]
