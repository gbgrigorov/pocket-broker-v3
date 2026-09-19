# -*- coding: utf-8 -*-
"""Enumerate the НСНИ members trading in Varna, from the association itself.

Why the association and not a portal. An agency directory on an aggregator
ranks agencies by how many adverts they run there, which is precisely the
metric a fake-heavy agency maximises -- it rewards the behaviour this product
exists to filter out. НСНИ members accept a code of ethics and can be expelled
under it, and the list is published by the body that enforces it.

The membership page renders client-side, so the category's WordPress RSS feed
is used instead: same data, complete, and machine-readable without a browser.

An earlier pass took 8 Varna members off the rendered page. The feed lists
roughly four times that -- ФОРОС, МИРЕЛА 5, ЛОГОС, СТЕФАНОВ ИНВЕСТ, ЕРА
МАКСИМА and two dozen more were simply never seen.
"""
import html as html_lib
import re

from django.core.management.base import BaseCommand

from market import recon
from sourcing.models import Agency

FEED = 'https://nsni.bg/members_category/varna/feed/'

ITEM = re.compile(r'<item>(.*?)</item>', re.S)
TITLE = re.compile(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', re.S)
LINK = re.compile(r'<link>(.*?)</link>', re.S)

# On a member's own page the site is a plain outbound link or bare text.
SITE = re.compile(r'(?:https?://)?(?:www\.)?([a-z0-9][a-z0-9-]{2,}\.(?:bg|com|eu|net|org))',
                  re.I)
EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')
# Plugin and platform domains that appear on every WordPress page. yoast.com in
# particular is emitted by the SEO plugin's JSON-LD on every single member page,
# and the first version of this handed it back as all 45 agencies' website.
NOT_A_SITE = ('nsni.bg', 'facebook', 'instagram', 'youtube', 'google.', 'gravatar',
              'w3.org', 'schema.org', 'gmail.com', 'abv.bg', 'mail.bg', 'twitter',
              'linkedin', 'wordpress', 'jquery', 'bootstrapcdn', 'alo.bg',
              'imot.bg', 'imoti.net', 'yoast.com', 'wp.com', 'gstatic',
              'googleapis', 'cloudflare', 'jsdelivr', 'unpkg', 'fontawesome',
              'gmpg.org', 'creativecommons')


def clean(text):
    return re.sub(r'\s+', ' ', html_lib.unescape(re.sub(r'<[^>]+>', '', text))).strip()


def slugify(name):
    table = str.maketrans({
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ж': 'zh',
        'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n',
        'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f',
        'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sht', 'ъ': 'a',
        'ь': '', 'ю': 'yu', 'я': 'ya',
    })
    out = name.lower().translate(table)
    out = re.sub(r'\b(eood|ood|ad|et|ltd)\b', '', out)
    out = re.sub(r'[^a-z0-9]+', '-', out).strip('-')
    return out[:70] or 'agency'


class Command(BaseCommand):
    help = 'Seed Varna agencies from the НСНИ member register.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--no-detail', action='store_true',
                            help='skip fetching each member page for its website')

    def handle(self, *args, **options):
        members = self._feed()
        self.stdout.write(f'{len(members)} НСНИ members listed for Varna\n')

        rows = []
        for name, link in sorted(members.items()):
            website = email = ''
            if link and not options['no_detail']:
                website, email = self._detail(link)
            rows.append({'name': name, 'slug': slugify(name), 'link': link,
                         'website': website, 'email': email})
            mark = '✓' if website else '·'
            self.stdout.write(f'  {mark} {name[:44]:46} {website[:40]}')

        with_site = [r for r in rows if r['website']]
        self.stdout.write(f'\n{len(with_site)}/{len(rows)} publish a website')
        if options['dry_run']:
            self.stdout.write(self.style.WARNING('Dry run; nothing written.'))
            return

        created = updated = 0
        for row in rows:
            existing = None
            if row['website']:
                existing = Agency.objects.filter(
                    website__icontains=_host(row['website'])).first()
            existing = existing or Agency.objects.filter(slug=row['slug']).first()
            note = (f'НСНИ member (Varna regional structure): {row["link"]}. '
                    f'Admitted on association membership — a code of ethics with '
                    f'expulsion behind it, not an advert count.')
            if existing:
                existing.notes = _merge(existing.notes, note)
                if row['website'] and not existing.website:
                    existing.website = row['website']
                if row['email'] and not existing.email:
                    existing.email = row['email'][:254]
                existing.website_source = 'nsni'
                existing.crawl_opt_out = False
                existing.save()
                updated += 1
                continue
            Agency.objects.create(
                slug=row['slug'], name=row['name'][:200], website=row['website'],
                email=row['email'][:254], source_kind='none', website_source='nsni',
                notes=note)
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f'{created} new · {updated} updated. Next: probe_agencies --only-new --deep'))

    def _feed(self):
        seen = {}
        for page in range(1, 10):
            url = FEED if page == 1 else f'{FEED}?paged={page}'
            res = recon.get(url)
            if not res['ok'] or '<item' not in res['body']:
                break
            fresh = 0
            for item in ITEM.findall(res['body']):
                title = TITLE.search(item)
                if not title:
                    continue
                name = clean(title.group(1))
                if not name or name in seen:
                    continue
                link = LINK.search(item)
                seen[name] = clean(link.group(1)) if link else ''
                fresh += 1
            if not fresh:
                break
        return seen

    def _detail(self, url):
        """The member's own website and email, off their НСНИ page."""
        res = recon.get(url)
        if not res['ok']:
            return '', ''
        body = res['body']
        email = ''
        for candidate in EMAIL.findall(body):
            if 'nsni' not in candidate.lower() and 'sentry' not in candidate.lower():
                email = candidate
                break
        # Only the part of the page describing this member, so the site-wide
        # footer does not donate a domain to every agency.
        # Only the member's own block. Site-wide chrome and plugin JSON-LD
        # otherwise donate a domain to every agency alike.
        chunk = body
        anchor = body.lower().find('class="entry-content')
        if anchor < 0:
            anchor = body.lower().find('single-members')
        if anchor > 0:
            chunk = body[anchor:anchor + 9000]
        chunk = re.sub(r'<script.*?</script>', ' ', chunk, flags=re.S | re.I)
        for host in SITE.findall(chunk):
            host = host.lower()
            if any(bad in host for bad in NOT_A_SITE):
                continue
            return f'https://{host}', email
        return '', email


def _host(url):
    return re.sub(r'^https?://(www\.)?', '', url or '').split('/')[0]


def _merge(existing, note):
    existing = existing or ''
    if 'НСНИ member' in existing:
        return existing[:4000]
    return (existing + ' ' + note).strip()[:4000]
