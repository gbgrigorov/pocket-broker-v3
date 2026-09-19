# -*- coding: utf-8 -*-
"""Is the vendored copy still what we recorded -- and what moved upstream?"""
from django.core.management.base import BaseCommand

from market import upstream


class Command(BaseCommand):
    help = 'Verify the vendored copy against docs/VENDOR-MANIFEST.md.'

    def add_arguments(self, parser):
        parser.add_argument('--upstream', action='store_true',
                            help='also report what broker-crm changed since we copied')

    def handle(self, *args, **options):
        drifted, missing, unrecorded = upstream.compare()

        for path in drifted:
            self.stdout.write(self.style.ERROR(f'  drifted     {path}'))
        for path in missing:
            self.stdout.write(self.style.ERROR(f'  missing     {path}'))
        for path in unrecorded:
            self.stdout.write(self.style.WARNING(f'  unrecorded  {path}'))

        if drifted or missing:
            self.stdout.write(self.style.ERROR(
                '\nThe copy no longer matches the manifest. Either revert the edit, '
                'or declare it in market/upstream.py::DIVERGENCES and re-run '
                'vendor_record.'))
        elif unrecorded:
            self.stdout.write(self.style.WARNING(
                '\nNew files are present but unrecorded. Run vendor_record.'))
        else:
            self.stdout.write(self.style.SUCCESS('Vendored copy matches the manifest.'))

        if options['upstream']:
            drift = upstream.upstream_drift()
            self.stdout.write('\nUpstream since we copied:')
            if not drift:
                self.stdout.write('  broker-crm is unchanged in the vendored paths.')
            for path, why in drift:
                self.stdout.write(f'  {why:16} {path}')
