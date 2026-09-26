# -*- coding: utf-8 -*-
"""Our own models. Vendored ones live in sourcing/ and crm/.

Geography surrounds the vendored Offer without rewriting its identity. SiteProbe
retains reconnaissance evidence. Physical Unit and buyer/partner models remain
future phases.
"""
from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator


class Country(models.Model):
    code = models.CharField(max_length=2, unique=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class City(models.Model):
    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name='cities')
    slug = models.SlugField(max_length=80, unique=True)
    name_bg = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name_bg']

    def __str__(self):
        return self.name_bg


class Neighbourhood(models.Model):
    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name='neighbourhoods')
    slug = models.SlugField(max_length=100)
    name_bg = models.CharField(max_length=100)
    name_en = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name_bg']
        constraints = [models.UniqueConstraint(fields=['city', 'slug'], name='neighbourhood_city_slug')]

    def __str__(self):
        return f'{self.city}: {self.name_bg}'


class NeighbourhoodAlias(models.Model):
    neighbourhood = models.ForeignKey(Neighbourhood, on_delete=models.CASCADE, related_name='aliases')
    alias = models.CharField(max_length=160)
    normalized_alias = models.CharField(max_length=160, db_index=True, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['neighbourhood', 'normalized_alias'], name='neighbourhood_alias_unique')]

    def save(self, *args, **kwargs):
        from market.geography_seed_v1 import normalize
        self.normalized_alias = normalize(self.alias)
        if kwargs.get('update_fields') is not None:
            kwargs['update_fields'] = set(kwargs['update_fields']) | {'normalized_alias'}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.alias


class OfferGeo(models.Model):
    offer = models.OneToOneField('sourcing.Offer', on_delete=models.CASCADE, related_name='geo')
    city = models.ForeignKey(City, null=True, blank=True, on_delete=models.PROTECT, related_name='offer_geographies')
    neighbourhood = models.ForeignKey(Neighbourhood, null=True, blank=True, on_delete=models.PROTECT, related_name='offer_geographies')
    raw_location = models.TextField(blank=True)
    normalized_location = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    confidence = models.DecimalField(max_digits=3, decimal_places=2, default=0,
                                     validators=[MinValueValidator(0), MaxValueValidator(1)])
    matched_by = models.CharField(max_length=40, default='unresolved')

    class Meta:
        indexes = [models.Index(fields=['city', 'neighbourhood'], name='offer_geo_city_neigh_idx')]
        constraints = [
            models.CheckConstraint(condition=models.Q(confidence__gte=0, confidence__lte=1), name='offer_geo_confidence_range'),
            models.CheckConstraint(condition=models.Q(neighbourhood__isnull=True) | models.Q(city__isnull=False), name='offer_geo_neigh_has_city'),
        ]

    def clean(self):
        if self.neighbourhood_id and self.neighbourhood.city_id != self.city_id:
            raise ValidationError({'neighbourhood': 'Neighbourhood must belong to the selected city.'})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.offer_id}: {self.city or "unresolved"}'


class SiteProbe(models.Model):
    """What one reconnaissance pass found on one agency's website.

    Kept as a row rather than a note in a file because it is evidence with a
    date on it: sites are redesigned, sitemaps move, and a recipe that stops
    working should be diffable against the last time the site was understood.
    """
    STATUS = [
        ('ok', 'ok'),                  # reachable and understood
        ('unreachable', 'unreachable'),  # DNS, TLS or timeout
        ('http_error', 'http error'),   # answered, but not 2xx
        ('blocked', 'blocked'),         # 403/429/503, or a challenge page
        ('captcha', 'captcha'),         # explicit refusal; never worked around
        ('no_listings', 'no listings'),  # reachable, but no catalogue found
    ]
    city = models.ForeignKey(City, null=True, blank=True, on_delete=models.PROTECT,
                             related_name='site_probes')
    strategy = models.JSONField(default=dict, blank=True)

    # Which sweep this row belongs to, and when that sweep STARTED.
    #
    # Selecting "the latest probe" by row timestamp is wrong, and was wrong
    # here: a superseded sweep launched earlier but finishing later wrote its
    # rows last and silently reinstated results a bug fix had already removed.
    # Two agencies went back to "no listings" without anything appearing to
    # fail. Crawl rule 8 -- every run gets its own identity -- exists for
    # exactly this, and applies to reconnaissance as much as to crawling.
    #
    # run_started is the ordering key, so a late-landing stale run stays stale.
    run_id = models.CharField(max_length=12, db_index=True, default='legacy')
    run_started = models.DateTimeField(null=True, blank=True, db_index=True)

    agency_slug = models.SlugField(max_length=64, db_index=True)
    agency_name = models.CharField(max_length=160)
    website = models.URLField(max_length=300, blank=True)

    probed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=16, choices=STATUS, default='ok')
    http_status = models.IntegerField(null=True, blank=True)
    final_url = models.URLField(max_length=400, blank=True)
    note = models.TextField(blank=True)

    platform = models.CharField(max_length=120, blank=True)
    server = models.CharField(max_length=120, blank=True)
    meta_charset = models.CharField(max_length=32, blank=True)
    header_charset = models.CharField(max_length=32, blank=True)

    # robots.txt is recorded on every probe regardless of CRAWL_RESPECT_ROBOTS.
    # It is evidence, and it is the API-negotiation call sheet -- an agency that
    # disallowed crawling is the first call to make. See docs/CRAWL-POLICY.md.
    robots_found = models.BooleanField(default=False)
    robots_disallow = models.JSONField(default=list, blank=True)
    robots_blocks_listings = models.BooleanField(default=False)

    sitemaps = models.JSONField(default=list, blank=True)
    sitemap_url_count = models.IntegerField(null=True, blank=True)
    url_shapes = models.JSONField(default=list, blank=True)
    listing_pattern = models.CharField(max_length=200, blank=True)
    # Index pages: what the crawler walks, as opposed to what it stores. A
    # recipe needs both, and mistaking one for the other produces a crawl that
    # fetches listing indexes forever and ingests nothing.
    catalogue_patterns = models.JSONField(default=list, blank=True)
    listing_count = models.IntegerField(null=True, blank=True)

    wp_types = models.JSONField(default=dict, blank=True)
    has_project_pages = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ['agency_slug', '-run_started', '-probed_at']
        get_latest_by = 'run_started'
        indexes = [models.Index(fields=['-run_started', 'agency_slug'])]

    def __str__(self):
        return f'{self.agency_slug} @ {self.probed_at:%Y-%m-%d} [{self.status}]'

    @classmethod
    def for_city(cls, city='varna'):
        # Legacy probes describe the original Varna registry. A new Sofia probe
        # must never replace the strategy used by the existing Varna commands.
        scope = models.Q(city__slug=city)
        if city == 'varna':
            scope |= models.Q(city__isnull=True)
        return cls.objects.filter(scope)

    @classmethod
    def current_run(cls, city='varna'):
        """The most recently STARTED sweep, which is the only current one."""
        row = cls.for_city(city).order_by('-run_started').first()
        return row.run_id if row else None

    @classmethod
    def latest(cls, city='varna'):
        """One probe per agency, from the newest sweep, older runs filling gaps.

        Gap-filling matters because a sweep may skip an agency (--agency) and
        that agency's last known state is still the best we have.
        """
        out = {}
        for probe in cls.for_city(city).order_by('run_started', 'probed_at'):
            out[probe.agency_slug] = probe
        return out

    @property
    def crawlable(self):
        return self.status == 'ok' and bool(self.listing_pattern)
