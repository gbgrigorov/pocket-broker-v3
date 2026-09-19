# -*- coding: utf-8 -*-
from django.apps import AppConfig


class MarketConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'market'
    verbose_name = 'Пазар'

    def ready(self):
        """Merge the Varna recipes into the vendored crawler's registry.

        sourcing/web/sites.py belongs to broker-crm and describes its client's
        Burgas partners. Editing it to add Varna agencies would fork a vendored
        file for what is really our own data, so the recipes live in
        market/sites_varna.py and are merged here instead. Everything in the
        crawler reads them through sites.recipe(slug), so one merge covers it.
        """
        from sourcing.web import sites
        from market import sites_varna

        sites.RECIPES.update(sites_varna.RECIPES)
        sites.NO_INDEX.update(sites_varna.NO_INDEX)
        sites.BLOCKED.update(sites_varna.BLOCKED)
