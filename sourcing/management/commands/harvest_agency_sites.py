# -*- coding: utf-8 -*-
"""Find each agency's own website in its own price sheet.

The client's registry lists a website for six agencies. The two with the most
stock -- 257 and 232 offers between them -- are not among them, which would
leave the web channel blind exactly where it matters most.

The sheets know, though: agencies put their site in the contact banner and link
straight to individual listings from the photo column. So the address is
harvested from the workbook rather than guessed, and the listing links come with
it -- which is how the web channel learns that this site's listings live under
`/property/` before it fetches a single page.
"""
import collections
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand

from sourcing.models import Agency, Offer
from sourcing import vendor  # noqa: F401

from xlsx_reader import read_workbook  # noqa: E402

# File lockers, social networks, messengers and mail hosts. A link to any of
# these is where an agency keeps its photos or its inbox, never its catalogue.
NOT_AN_AGENCY_SITE = (
    'google.', 'gstatic', 'googleusercontent', 'dropbox', 'yandex', 'disk.yandex',
    'facebook', 'fb.com', 'instagram', 'youtube', 'youtu.be', 'wa.me', 'whatsapp',
    't.me', 'telegram', 'viber', 'mail.ru', 'gmail', 'abv.bg', 'yahoo', 'outlook',
    'bit.ly', 'tinyurl', 'goo.gl', 'ow.ly', 'rb.gy', 'cutt.ly', 'is.gd', 'shorturl',
    'indomio', 'imot.bg', 'imoti.net', 'alo.bg', 'olx.',
    'booking.com', 'airbnb', 'tripadvisor', 'w3.org', 'schemas.',
)

URL_IN_TEXT = re.compile(r'(?:https?://|www\.)[^\s,;"\'<>()]+', re.I)
MIN_SEGMENT_LENGTH = 3


def registrable(host):
    """Good enough for our purposes: the last two labels, minus any 'www'."""
    host = (host or '').lower().lstrip('.')
    if host.startswith('www.'):
        host = host[4:]
    parts = host.split('.')
    return '.'.join(parts[-2:]) if len(parts) >= 2 else host


class Command(BaseCommand):
    help = 'Открива сайта на всяка агенция от собствената ѝ таблица.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--overwrite', action='store_true',
                            help='Заменя и вече попълнените сайтове.')

    def handle(self, *args, **options):
        updated = patterns_found = 0
        for agency in Agency.objects.filter(duplicate_of__isnull=True).order_by('slug'):
            urls = self._collect_urls(agency)
            if not urls:
                continue
            domain, listing_urls = self._pick_domain(agency, urls)
            if not domain:
                continue

            patterns = self._patterns(listing_urls, domain)
            website = f'https://{domain}/'
            keep_existing = agency.website and not options['overwrite']

            line = (f'  {agency.slug:28} {domain:26} '
                    f'{len(listing_urls):>3} обяви  {", ".join(patterns) or "—"}')
            if keep_existing and registrable(urlsplit(agency.website).hostname) == domain:
                line += '   (вече известен)'
            self.stdout.write(line)

            if options['dry_run']:
                continue
            changed = []
            if not keep_existing:
                agency.website = website
                agency.website_source = 'sheet'
                changed += ['website', 'website_source']
                updated += 1
            if patterns and patterns != agency.listing_url_patterns:
                agency.listing_url_patterns = patterns
                changed.append('listing_url_patterns')
                patterns_found += 1
            if changed:
                agency.save(update_fields=changed + ['updated_at'])

        total = Agency.objects.filter(duplicate_of__isnull=True).exclude(website='').count()
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Нови сайтове: {updated} · шаблони на обяви: {patterns_found} · '
            f'общо агенции със сайт: {total}'))

    # ------------------------------------------------------------------
    def _collect_urls(self, agency):
        """Every URL in the agency's latest sheet, plus any already on its offers."""
        urls = []
        folder = settings.RAW_DIR / agency.slug
        files = sorted(folder.glob('*.xlsx')) if folder.exists() else []
        if files:
            try:
                workbook = read_workbook(str(files[-1]))
            except Exception:                       # a PDF or a truncated download
                workbook = {'sheets': []}
            for sheet in workbook['sheets']:
                urls.extend(u for u in (sheet.get('links') or {}).values() if u)
                # grid is a list of rows, each a list of cell strings
                for row in (sheet.get('grid') or []):
                    for cell in (row or []):
                        if cell and ('http' in str(cell) or 'www.' in str(cell)):
                            urls.extend(URL_IN_TEXT.findall(str(cell)))

        urls.extend(Offer.objects.filter(agency=agency).exclude(listing_url='')
                    .values_list('listing_url', flat=True))
        if agency.website:
            urls.append(agency.website)
        if agency.email and '@' in agency.email:
            domain = agency.email.split('@')[1]
            if not any(bad in domain for bad in NOT_AN_AGENCY_SITE):
                urls.append(f'https://{domain}/')   # an own-domain mailbox is a strong hint
        return urls

    def _pick_domain(self, agency, urls):
        """The domain that appears most often and is not somebody else's service."""
        tally = collections.Counter()
        by_domain = collections.defaultdict(list)
        for url in urls:
            if url.lower().startswith('www.'):
                url = 'https://' + url
            host = urlsplit(url).hostname
            if not host or any(bad in host.lower() for bad in NOT_AN_AGENCY_SITE):
                continue
            domain = registrable(host)
            if not domain or '.' not in domain:
                continue
            tally[domain] += 1
            by_domain[domain].append(url)
        if not tally:
            return None, []
        domain, _count = tally.most_common(1)[0]
        return domain, by_domain[domain]

    def _patterns(self, urls, domain):
        """The first path segment shared by several listing URLs."""
        tally = collections.Counter()
        for url in urls:
            path = urlsplit(url).path
            segments = [s for s in path.split('/') if s]
            if len(segments) < 2:
                continue                            # a bare page, not a listing
            head = segments[0]
            if len(head) >= MIN_SEGMENT_LENGTH and not head.isdigit():
                tally[f'/{head}/'] += 1
        return [pattern for pattern, count in tally.most_common(3) if count >= 2]
