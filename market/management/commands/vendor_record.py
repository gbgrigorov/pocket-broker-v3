# -*- coding: utf-8 -*-
"""Re-record the hop-2 vendor manifest after a deliberate change."""
from django.core.management.base import BaseCommand

from market import upstream


class Command(BaseCommand):
    help = 'Regenerate docs/VENDOR-MANIFEST.md from the files on disk.'

    def handle(self, *args, **options):
        rows = upstream.build_rows()
        upstream.MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        upstream.MANIFEST.write_text(upstream.render_manifest(rows), encoding='utf-8')
        total = sum(r['lines'] for r in rows)
        self.stdout.write(self.style.SUCCESS(
            f'Recorded {len(rows)} files ({total:,} lines) -> {upstream.MANIFEST.name}'))
