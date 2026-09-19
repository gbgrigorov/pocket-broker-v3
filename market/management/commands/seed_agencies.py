# -*- coding: utf-8 -*-
"""Create Agency rows from the admitted registry and the latest probes.

The registry (market/agencies_varna.py) says who we index and on what evidence.
The probe says what their site actually looks like. This joins the two, and
refuses to mark an agency crawlable on anything but a verified listing pattern.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from market import agencies_varna
from market.models import SiteProbe
from sourcing.models import Agency


class Command(BaseCommand):
    help = 'Seed Agency rows for the admitted Varna agencies.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        probes = SiteProbe.latest()

        created = updated = 0
        for row in agencies_varna.rows():
            probe = probes.get(row['slug'])
            # `notes` carries the admission basis so the reason an agency is in
            # the index travels with the row, not just with the source file.
            notes = [f'Admitted: {row["admission_basis"]}.']
            if row['since']:
                notes.append(f'Trading since {row["since"]}.')
            if row['note']:
                notes.append(row['note'])
            if probe:
                notes.append(f'Probed {probe.probed_at:%d.%m.%Y}: {probe.status}'
                             + (f', pattern {probe.listing_pattern}' if probe.listing_pattern else '')
                             + '.')

            defaults = {
                'name': row['name'],
                'website': row['website'] or '',
                'source_kind': 'none',      # web channel only; no price sheets here
                'website_source': 'registry',
                'notes': ' '.join(notes),
                'listing_url_patterns': (
                    [probe.listing_pattern] if probe and probe.listing_pattern else []),
                'source_status': probe.status if probe else 'unprobed',
            }
            if options['dry_run']:
                self.stdout.write(f'  would seed {row["slug"]:24} {defaults["source_status"]}')
                continue
            _obj, was_created = Agency.objects.update_or_create(
                slug=row['slug'], defaults=defaults)
            created += was_created
            updated += (not was_created)

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('Dry run; nothing written.'))
            return

        crawlable = Agency.objects.exclude(listing_url_patterns=[]).count()
        self.stdout.write(self.style.SUCCESS(
            f'{created} created, {updated} updated. '
            f'{crawlable} have a verified listing pattern.'))
        for slug, reason in agencies_varna.EXCLUDED.items():
            self.stdout.write(f'  excluded: {slug} — {reason[:70]}...')
