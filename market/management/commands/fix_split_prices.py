# -*- coding: utf-8 -*-
"""Repair prices that were read across a line break.

"Възраждане 4" above "185 000 €" was parsed as 4 185 000 €. The line carrying
the currency marker is the price; the other line is the building's name.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from market import prices
from sourcing.models import Offer


class Command(BaseCommand):
    help = 'Re-read multi-line price blocks and correct the stored price.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        rows = Offer.objects.exclude(price_raw='').filter(price_eur__isnull=False)
        changed = 0
        with transaction.atomic():
            for offer in rows.iterator(chunk_size=500):
                line = prices.price_line(offer.price_raw)
                if not line:
                    continue
                value = prices.value_of(line)
                if not value or value >= float(offer.price_eur):
                    continue
                per_m2 = (round(value / float(offer.area_m2), 2)
                          if offer.area_m2 else None)
                self.stdout.write(
                    f'  {offer.price_eur} -> {value}   ({offer.price_raw!r})')
                if options['dry_run']:
                    changed += 1
                    continue
                offer.notes = ((offer.notes or '') +
                               f' [Price re-read from a multi-line block: '
                               f'{offer.price_eur} was the building name glued to '
                               f'the price; corrected to {value}.]')[:4000]
                offer.price_eur = value
                offer.price_per_m2 = per_m2
                offer.save(update_fields=['price_eur', 'price_per_m2', 'notes'])
                changed += 1
            if options['dry_run']:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(
            f'{changed} prices corrected' + (' [dry run]' if options['dry_run'] else '')))
