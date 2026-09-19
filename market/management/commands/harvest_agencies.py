# -*- coding: utf-8 -*-
"""Enumerate every agency advertising in Varna, from a public agency directory.

Why this exists. The original registry was built from a "most trustworthy
agencies" research pass -- НСНИ membership or a Google rating above 4.0. That
is a quality filter applied at the discovery stage, and it optimises for an
index you can defend rather than one that is complete. Measured against this
directory it was holding 6% of the market, and the three largest agencies in
Varna -- 5 457 listings between them -- were not contributing a single row.

The rule is now: admit broadly, rank by trust. A listing earns its place by
being traceable to a named source the reader can click through to; trust is a
badge on the card and a sort order, not a gate at the door.

A directory page is not an advertisement. This reads the list of agencies and
their own published contact details, and nothing else -- no listings, no
portal ads. What it produces is a work list of sites to probe.
"""
import re

from django.core.management.base import BaseCommand

from market.models import SiteProbe   # noqa: F401  (imported for --report)
from sourcing.models import Agency

SOURCE = 'https://www.alo.bg/agency/?region_id=3'

BLOCK = re.compile(r'<div class="agency_div"\s*>(.*?)(?=<div class="agency_div"|\Z)', re.S)
NAME = re.compile(r'<h2>(.*?)</h2>', re.S)
COUNT = re.compile(r'<b>([\d\s]+)</b>\s*Имоти', re.I)
SITE = re.compile(r'class="sites"[^>]*>\s*(https?://[^\s<]+)', re.I)
PHONE = re.compile(r'class="phone"[^>]*href="tel:([^"]+)"', re.I)

# Hosts that are never an agency's own site.
NOT_A_SITE = ('alo.bg', 'imot.bg', 'imoti.net', 'facebook', 'instagram',
              'olx.', 'bazar.bg', 'youtube', 'google.')


def slugify(name):
    """A stable slug from a Bulgarian agency name."""
    table = str.maketrans({
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ж': 'zh',
        'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n',
        'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f',
        'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sht', 'ъ': 'a',
        'ь': '', 'ю': 'yu', 'я': 'ya',
    })
    out = name.lower().translate(table)
    out = re.sub(r'[^a-z0-9]+', '-', out).strip('-')
    return out[:70] or 'agency'


class Command(BaseCommand):
    help = 'Harvest Varna agencies and their own websites from a public directory.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--min-listings', type=int, default=0,
                            help='skip agencies advertising fewer than this')

    def handle(self, *args, **options):
        from market import recon
        res = recon.get(SOURCE)
        if not res['ok']:
            self.stdout.write(self.style.ERROR(f'directory unreachable: {res["status"]}'))
            return

        rows, seen = [], set()
        for block in BLOCK.findall(res['body']):
            name_match = NAME.search(block)
            if not name_match:
                continue
            name = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', name_match.group(1))).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            count = COUNT.search(block)
            site = SITE.search(block)
            phone = PHONE.search(block)
            website = site.group(1).rstrip('/,.') if site else ''
            if website and any(bad in website.lower() for bad in NOT_A_SITE):
                website = ''
            rows.append({
                'name': name,
                'slug': slugify(name),
                'listings': int(count.group(1).replace(' ', '')) if count else 0,
                'website': website,
                'phone': phone.group(1) if phone else '',
            })

        rows.sort(key=lambda r: -r['listings'])
        kept = [r for r in rows if r['listings'] >= options['min_listings']]
        total = sum(r['listings'] for r in rows)
        with_site = [r for r in kept if r['website']]

        self.stdout.write(
            f'{len(rows)} agencies in the directory · {total:,} listings advertised\n'
            f'{len(kept)} above the threshold · {len(with_site)} publish their own site\n')

        if options['dry_run']:
            for r in kept[:40]:
                self.stdout.write(f'  {r["listings"]:6}  {r["name"][:34]:36} {r["website"][:40]}')
            self.stdout.write(self.style.WARNING('\nDry run; nothing written.'))
            return

        created = updated = 0
        for row in kept:
            existing = (Agency.objects.filter(website__icontains=_host(row['website'])).first()
                        if row['website'] else None)
            existing = existing or Agency.objects.filter(slug=row['slug']).first()
            note = (f'Directory: advertises {row["listings"]} listings in the Varna '
                    f'region (alo.bg agency directory).')
            if existing:
                existing.notes = _merge_note(existing.notes, note)
                if row['website'] and not existing.website:
                    existing.website = row['website']
                existing.save(update_fields=['notes', 'website'])
                updated += 1
                continue
            Agency.objects.create(
                slug=row['slug'], name=row['name'], website=row['website'],
                source_kind='none', website_source='directory',
                phones=[row['phone']] if row['phone'] else [],
                notes=note + ' Admitted under the open rule: indexed and ranked by '
                             'trust rather than gated on it.')
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f'{created} new agencies · {updated} existing updated'))
        self.stdout.write('Next: python manage.py probe_agencies --deep')


def _host(url):
    return re.sub(r'^https?://(www\.)?', '', url or '').split('/')[0]


def _merge_note(existing, note):
    existing = existing or ''
    if 'Directory:' in existing:
        existing = re.sub(r'Directory:[^.]*\.', note, existing, count=1)
        return existing[:4000]
    return (existing + ' ' + note).strip()[:4000]
