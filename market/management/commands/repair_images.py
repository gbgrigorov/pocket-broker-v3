# -*- coding: utf-8 -*-
"""Re-download images whose stored file is not actually an image.

816 of them were not. They were fetched through a text-decoding HTTP helper,
so every byte that was not valid UTF-8 was replaced on the way in and dropped
on the way out; the files kept a .webp name and a mangled RIFF header, and no
browser would render one. The extension proved nothing, which is why this
checks each file's own magic bytes rather than its name.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from market import images
from sourcing.models import OfferImage


class Command(BaseCommand):
    help = 'Verify stored images and re-download the broken ones.'

    def add_arguments(self, parser):
        parser.add_argument('--check-only', action='store_true')
        parser.add_argument('--limit', type=int)
        parser.add_argument('--drop-unfixable', action='store_true',
                            help='remove rows whose source no longer serves an image')

    def handle(self, *args, **options):
        rows = OfferImage.objects.select_related('offer__agency').order_by('id')
        broken = []
        for row in rows:
            path = Path(settings.DATA_DIR) / row.local_path
            if not path.exists():
                broken.append((row, 'missing'))
                continue
            if not images.looks_like_image(path.read_bytes()[:16]):
                broken.append((row, 'corrupt'))

        self.stdout.write(f'{rows.count()} stored · {len(broken)} unusable')
        if options['check_only']:
            return
        if options['limit']:
            broken = broken[:options['limit']]

        fixed = dropped = 0
        for row, why in broken:
            blob = images.fetch_bytes(row.source_url) if row.source_url else None
            if not blob or not images.looks_like_image(blob):
                # The row promises a picture the source will not give us. Left
                # in place unless explicitly asked to drop it -- the card hides
                # a broken image either way, and deleting rows is not something
                # a repair job should decide on its own.
                dropped += 1
                continue
            import hashlib
            digest = hashlib.sha256(blob).hexdigest()
            folder = images.store_dir(row.offer.agency.slug)
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f'{digest[:24]}{images.extension_for(blob, row.source_url)}'
            path.write_bytes(blob)
            row.local_path = str(path.relative_to(settings.DATA_DIR))
            row.sha256 = digest
            row.save(update_fields=['local_path', 'sha256'])
            fixed += 1
            if fixed % 50 == 0:
                self.stdout.write(f'  repaired {fixed}…')

        if options['drop_unfixable'] and dropped:
            for row, _why in broken:
                path = Path(settings.DATA_DIR) / row.local_path
                if not path.exists() or not images.looks_like_image(path.read_bytes()[:16]):
                    row.delete()
        self.stdout.write(self.style.SUCCESS(
            f'{fixed} repaired · {dropped} still unusable'
            + (' (removed)' if options['drop_unfixable'] else ' (kept; pass --drop-unfixable to remove)')))
