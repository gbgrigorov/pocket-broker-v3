# -*- coding: utf-8 -*-
"""Our own models. Vendored ones live in sourcing/ and crm/.

Project / ProjectAlias / Unit / ProjectMembership (phase 5) and BuyerProfile
(phase 6) arrive once the crawl has produced data to shape them against.
SiteProbe comes first because nothing can be crawled before it is understood.
"""
from django.db import models


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

    @staticmethod
    def current_run():
        """The most recently STARTED sweep, which is the only current one."""
        row = SiteProbe.objects.order_by('-run_started').first()
        return row.run_id if row else None

    @classmethod
    def latest(cls):
        """One probe per agency, from the newest sweep, older runs filling gaps.

        Gap-filling matters because a sweep may skip an agency (--agency) and
        that agency's last known state is still the best we have.
        """
        out = {}
        for probe in cls.objects.order_by('run_started', 'probed_at'):
            out[probe.agency_slug] = probe
        return out

    @property
    def crawlable(self):
        return self.status == 'ok' and bool(self.listing_pattern)
