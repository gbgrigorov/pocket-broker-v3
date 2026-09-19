# -*- coding: utf-8 -*-
"""Load the client's master agency registry into the database.

The parsing itself is the vendored upstream module, called unmodified: it knows
how to dig real hyperlink targets out of the workbook's relationship XML and how
to unwrap the l.facebook.com/l.php redirects half the links are wrapped in.
This command only moves its output into Postgres.
"""
import json

from django.core.management.base import BaseCommand
from django.db import transaction

from sourcing.models import Agency
from sourcing import vendor  # noqa: F401  (puts vendor/ on sys.path)

import parse_registry  # noqa: E402  (resolved via the vendor package)

FIELDS = ('name', 'site_no', 'source_url', 'source_kind', 'doc_id', 'gid',
          'contact_name', 'phones', 'website', 'email')


class Command(BaseCommand):
    help = 'Прочита регистъра на агенциите (xlsx) и го записва в базата.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Само показва какво би се променило.')

    @transaction.atomic
    def handle(self, *args, **options):
        parse_registry.main()
        rows = json.loads(parse_registry.OUT.read_text(encoding='utf-8'))

        created = updated = 0
        seen = []
        for row in rows:
            values = {f: (row.get(f) or ('' if f != 'phones' else [])) for f in FIELDS}
            # A few registry rows carry a bare domain; the model wants a URL.
            if values['website'] and not values['website'].startswith('http'):
                values['website'] = 'https://' + values['website']
            if options['dry_run']:
                exists = Agency.objects.filter(slug=row['slug']).exists()
                self.stdout.write(f"  {'update' if exists else 'create'}  {row['slug']}")
                continue
            agency, was_created = Agency.objects.update_or_create(slug=row['slug'],
                                                                  defaults=values)
            created += was_created
            updated += not was_created
            seen.append((agency, row.get('duplicate_of')))

        if options['dry_run']:
            self.stdout.write(self.style.WARNING('Пробно изпълнение — нищо не е записано.'))
            return

        # Resolved in a second pass: the primary may appear after its alias.
        aliased = 0
        for agency, duplicate_of in seen:
            target = Agency.objects.filter(slug=duplicate_of).first() if duplicate_of else None
            if agency.duplicate_of_id != (target.pk if target else None):
                agency.duplicate_of = target
                agency.save(update_fields=['duplicate_of'])
            aliased += bool(target)

        crawlable = Agency.objects.filter(website__gt='', crawl_opt_out=False,
                                          duplicate_of__isnull=True).count()
        with_sheet = Agency.objects.filter(doc_id__gt='', duplicate_of__isnull=True).count()
        self.stdout.write(self.style.SUCCESS(
            f'Агенции: {created} нови, {updated} обновени, {aliased} дубликати.'))
        self.stdout.write(f'  с таблица за сваляне : {with_sheet}')
        self.stdout.write(f'  със сайт за обхождане: {crawlable}')
