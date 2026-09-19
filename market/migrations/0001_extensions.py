# -*- coding: utf-8 -*-
"""The three Postgres extensions the schema depends on.

Created here rather than by hand so a fresh database -- a new laptop, the VPS,
a CI run -- comes up complete from `migrate` alone. pg_trgm is load-bearing:
cross-agency dedupe matches "Гранд Камелия" to "Grand Kamelia" by trigram
similarity, and without the extension that index cannot be built at all.
"""
from django.contrib.postgres.operations import (
    BtreeGinExtension, TrigramExtension, UnaccentExtension,
)
from django.db import migrations


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    # sourcing.0001 builds a GIN trigram index and a jsonb GIN index, so the
    # extensions have to exist before it runs.
    run_before = [('sourcing', '0001_initial')]

    operations = [
        TrigramExtension(),
        UnaccentExtension(),
        BtreeGinExtension(),
    ]
