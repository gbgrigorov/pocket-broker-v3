from django.db import migrations


def seed_and_backfill(apps, schema_editor):
    from market.geography_seed_v1 import seed, backfill
    seed(apps, schema_editor.connection.alias)
    backfill(apps, schema_editor.connection.alias)


class Migration(migrations.Migration):
    dependencies = [('market', '0005_geography')]
    operations = [migrations.RunPython(seed_and_backfill, migrations.RunPython.noop)]
