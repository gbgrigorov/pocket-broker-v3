# -*- coding: utf-8 -*-
"""Import offer photos from a directory laid out as <fingerprint>/<file>.

A seeding tool, not a crawler: it moves files that are already on this machine
into this project's media directory and registers them. Downloading photos from
Google Drive and the agency sites is a separate job that belongs with Channel B.

It matches on fingerprint, which works because the identity function is the
vendored one -- the same input produces the same key on both sides.
"""
import hashlib
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from sourcing.models import Offer, OfferImage

SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp'}
MAX_PER_OFFER = 8


class Command(BaseCommand):
    help = 'Внася вече свалени снимки от папка <fingerprint>/<файл>.'

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='source', required=True)
        parser.add_argument('--limit', type=int, help='Само първите N оферти.')
        parser.add_argument('--link', action='store_true',
                            help='Създава твърди връзки вместо копия (пести място).')

    def handle(self, *args, **options):
        source = Path(options['source']).expanduser()
        if not source.is_dir():
            raise CommandError(f'Няма такава папка: {source}')

        destination_root = settings.IMAGES_DIR
        destination_root.mkdir(parents=True, exist_ok=True)

        fingerprints = dict(Offer.objects.filter(is_active=True)
                            .values_list('fingerprint', 'pk'))
        offers, files, skipped = 0, 0, 0

        for folder in sorted(source.iterdir()):
            if not folder.is_dir() or folder.name not in fingerprints:
                continue
            if options['limit'] and offers >= options['limit']:
                break
            added = self._import_one(folder, fingerprints[folder.name],
                                     destination_root, options['link'])
            if added:
                offers += 1
                files += added
            else:
                skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f'Внесени снимки за {offers} оферти ({files} файла). Пропуснати: {skipped}.'))
        with_photos = Offer.objects.filter(is_active=True, image_count__gt=0).count()
        total = Offer.objects.filter(is_active=True).count()
        self.stdout.write(f'Оферти със снимки: {with_photos} от {total} '
                          f'({100 * with_photos / total:.0f}%)')

    @transaction.atomic
    def _import_one(self, folder, offer_id, destination_root, link):
        offer = Offer.objects.get(pk=offer_id)
        destination = destination_root / offer.fingerprint
        destination.mkdir(parents=True, exist_ok=True)

        added = 0
        for index, path in enumerate(sorted(p for p in folder.iterdir()
                                            if p.suffix.lower() in SUFFIXES)):
            if index >= MAX_PER_OFFER:
                break
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if OfferImage.objects.filter(offer=offer, sha256=digest).exists():
                continue
            target = destination / path.name
            if not target.exists():
                if link:
                    try:
                        target.hardlink_to(path)
                    except OSError:
                        shutil.copy2(path, target)
                else:
                    shutil.copy2(path, target)
            OfferImage.objects.create(
                offer=offer, sha256=digest, position=index,
                local_path=str(target.relative_to(settings.MEDIA_ROOT)))
            added += 1

        if added:
            offer.image_count = offer.images.count()
            offer.save(update_fields=['image_count', 'updated_at'])
        return added
