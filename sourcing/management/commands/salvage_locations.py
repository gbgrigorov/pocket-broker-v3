# -*- coding: utf-8 -*-
"""Second-pass location recovery, over the whole corpus rather than one row.

Runs after a crawl because it needs every agency's data at once: the evidence
that fills in an unlocated "Grand Village Park" is the eight located ones
another agency published.
"""
from django.core.management.base import BaseCommand
from django.db import connection

from sourcing import salvage
from sourcing.models import Offer


class Command(BaseCommand):
    help = 'Възстановява липсващи населени места по данни от целия масив.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        unlocated = Offer.objects.filter(is_active=True, location='')
        before = unlocated.count()

        if options['dry_run']:
            would = []
            with connection.cursor() as cursor:
                for offer in unlocated:
                    found = salvage.infer_location_from_corpus(cursor, offer.title_norm)
                    source = 'корпус'
                    if not found:
                        found = salvage.resolve_location(salvage.defang_homoglyphs(
                            f'{offer.location_raw} {offer.title}'))
                        source = 'изписване'
                    if not found:
                        found = salvage.resolve_location(offer.source_tab)
                        source = 'име на таб'
                    if found:
                        would.append((offer.title[:40], found, source))
            for title, location, source in would:
                self.stdout.write(f'  {title:42} → {location}   ({source})')
            self.stdout.write(self.style.WARNING(
                f'Пробно: {len(would)} от {before} биха били възстановени.'))
            return

        recovered, details = salvage.salvage_corpus(unlocated)
        for title, location, source in details[:25]:
            self.stdout.write(f'  {title:42} → {location}   ({source})')
        remaining = Offer.objects.filter(is_active=True, location='').count()
        self.stdout.write(self.style.SUCCESS(
            f'Възстановени {recovered} от {before} · остават без локация: {remaining}'))
