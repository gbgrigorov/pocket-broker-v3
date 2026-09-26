from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from market.geography_seed_v1 import seed, backfill
from market.models import City, Neighbourhood, OfferGeo


class Command(BaseCommand):
    help = 'Seed Bulgarian geography and backfill missing OfferGeo rows without changing offers.'

    def add_arguments(self, parser):
        parser.add_argument('--resolve', action='store_true', help='Re-resolve nonmanual geography after alias curation.')

    @transaction.atomic
    def handle(self, *args, **options):
        seed(apps)
        visited = backfill(apps, resolve=options['resolve'])
        self.stdout.write(f'Cities: {City.objects.count()}; neighbourhoods: {Neighbourhood.objects.count()}; '
                          f'geography rows: {OfferGeo.objects.count()}; processed: {visited}; '
                          f'unresolved cities: {OfferGeo.objects.filter(city__isnull=True).count()}')
