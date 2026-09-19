# -*- coding: utf-8 -*-
"""The whole morning job: registry, sheets, sites, locations, re-match.

One entry point so a scheduler and a person run exactly the same steps.
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Пълно обхождане: регистър, таблици, локации и повторно търсене.'

    def add_arguments(self, parser):
        parser.add_argument('--offline', action='store_true',
                            help='Без сваляне — използва последните локални файлове.')
        parser.add_argument('--skip-rematch', action='store_true')
        parser.add_argument('--skip-sites', action='store_true',
                            help='Без обхождане на сайтовете на агенциите.')

    def handle(self, *args, **options):
        steps = [
            ('Регистър на агенциите', 'crawl_registry', {}),
            ('Ценови таблици', 'crawl_sheets', {'offline': options['offline']}),
        ]
        # The sites are the other half of the market. Sheets first, because they
        # are the partner data and they are cheap; sites second, because a
        # sitemap pass only fetches what moved overnight.
        if not options['offline'] and not options['skip_sites']:
            steps.append(('Сайтове на агенциите', 'crawl_sites', {'workers': 9}))
        steps.append(('Възстановяване на локации', 'salvage_locations', {}))
        if not options['skip_rematch']:
            steps.append(('Повторно търсене за чакащите клиенти', 'rematch_standing', {}))

        for index, (label, command, kwargs) in enumerate(steps, 1):
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'[{index}/{len(steps)}] {label}'))
            call_command(command, **kwargs)
