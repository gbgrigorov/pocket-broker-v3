# -*- coding: utf-8 -*-
"""Repair offers whose €/m² quote was stored as the asking price."""
from django.core.management.base import BaseCommand
from django.db import transaction

from market import prices
from sourcing.models import Offer


class Command(BaseCommand):
    help = 'Reinterpret per-square-metre quotes as price_per_m2 plus a derived total.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        rows = Offer.objects.exclude(price_raw='').filter(price_eur__isnull=False)
        fixed = no_area = 0
        with transaction.atomic():
            for offer in rows.iterator(chunk_size=500):
                if not prices.is_per_m2(offer.price_raw):
                    continue
                total, per_m2 = prices.normalise(
                    float(offer.price_eur), float(offer.area_m2) if offer.area_m2 else None,
                    offer.price_raw)
                if options['dry_run']:
                    self.stdout.write(
                        f'  {offer.price_eur} ({offer.price_raw}) × {offer.area_m2} m² '
                        f'-> total {total}, per m² {per_m2}')
                    fixed += 1
                    continue
                offer.price_per_m2 = per_m2
                offer.price_eur = total
                if total is None:
                    no_area += 1
                offer.notes = ((offer.notes or '') +
                               f' [Price quoted per m² ({offer.price_raw}); '
                               f'stored as price_per_m2'
                               + (f', total derived from {offer.area_m2} m².'
                                  if total else ', total unknown without an area.')
                               + ']')[:4000]
                offer.save(update_fields=['price_eur', 'price_per_m2', 'notes'])
                fixed += 1
            if options['dry_run']:
                transaction.set_rollback(True)

        self.stdout.write(self.style.SUCCESS(
            f'{fixed} offers reinterpreted'
            + (f'; {no_area} left without a total (no area published)' if no_area else '')
            + (' [dry run]' if options['dry_run'] else '')))
