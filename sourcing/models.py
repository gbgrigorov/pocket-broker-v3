# -*- coding: utf-8 -*-
"""The offer store: agencies, their price-sheet snapshots, and the offers.

Field names follow the record dict the vendored normaliser emits, so its output
drops in without a translation layer. Everything beyond that -- `source`,
`title_norm`, `dedup_key`, `features` -- is ours.

`Offer.source` is why there is no second table for web finds: a listing an AI
agent reads off an agency's own website is an offer like any other, with
`source='web'` and an `evidence` blob. Candidates therefore point at exactly one
table with a real foreign key.
"""
from django.contrib.postgres.indexes import GinIndex
from django.db import models


class DealType(models.TextChoices):
    SALE = 'sale', 'продажба'
    RENT = 'rent', 'наем'


class OfferSource(models.TextChoices):
    SHEET = 'sheet', 'ценова таблица'
    WEB = 'web', 'сайт на агенция'
    MANUAL = 'manual', 'ръчно въведена'


class SourceKind(models.TextChoices):
    GSHEET = 'gsheet', 'Google Sheet'
    GDRIVE_FILE = 'gdrive_file', 'Google Drive файл'
    DROPBOX = 'dropbox', 'Dropbox'
    YANDEX = 'yandex', 'Yandex Disk'
    NONE = 'none', 'няма таблица'


class Agency(models.Model):
    """One of the 42 partner agencies from the client's own registry."""

    slug = models.SlugField(max_length=80, unique=True)
    name = models.CharField('име', max_length=200)
    site_no = models.CharField('№ в сайта', max_length=16, blank=True)

    source_url = models.URLField('връзка към таблицата', max_length=500, blank=True)
    source_kind = models.CharField('вид източник', max_length=20,
                                   choices=SourceKind.choices, default=SourceKind.NONE)
    doc_id = models.CharField(max_length=120, blank=True)
    gid = models.CharField(max_length=40, blank=True)

    website = models.URLField('сайт', max_length=300, blank=True)
    email = models.EmailField('имейл', blank=True)
    contact_name = models.CharField('лице за контакт', max_length=200, blank=True)
    phones = models.JSONField('телефони', default=list, blank=True)

    # Path fragments of real listing URLs seen in this agency's own sheet, e.g.
    # "/property/" or "/bulgarian_properties/". Harvested rather than guessed,
    # and handed to the web channel so it knows what a listing page looks like
    # on this particular site instead of crawling the whole thing.
    listing_url_patterns = models.JSONField('шаблони на обявите', default=list, blank=True)
    website_source = models.CharField(max_length=20, blank=True)

    duplicate_of = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='duplicates', verbose_name='дубликат на')
    # An agency that asks not to be crawled is skipped forever by Channel B.
    # Channel A is unaffected: those sheets are shared with us as partners.
    crawl_opt_out = models.BooleanField('без обхождане на сайта', default=False)

    last_fetch = models.DateTimeField(null=True, blank=True)
    last_change = models.DateTimeField(null=True, blank=True)
    source_status = models.CharField(max_length=20, blank=True)
    notes = models.TextField('бележки', blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'агенция'
        verbose_name_plural = 'агенции'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def has_crawlable_site(self):
        return bool(self.website) and not self.crawl_opt_out


class Offer(models.Model):
    """A single property. The integer primary key is the stable identity.

    `fingerprint` is the crawler's content-derived identity and is deliberately
    NOT the primary key: upstream rekeys it in place when a thin row is
    recognised as a repriced one it has seen before (151 of ~1,135 active offers
    carry the `weak` identity that does this). A candidate pointing at a
    fingerprint would silently dangle; pointing at the row id cannot.
    """

    source = models.CharField('източник', max_length=10,
                              choices=OfferSource.choices, default=OfferSource.SHEET,
                              db_index=True)
    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='offers',
                               verbose_name='агенция')

    # --- crawler identity -----------------------------------------------
    fingerprint = models.CharField(max_length=32, unique=True, db_index=True)
    weak_core = models.CharField(max_length=300, blank=True, db_index=True)
    dup_group = models.CharField(max_length=32, blank=True, db_index=True)
    identity_strength = models.CharField(max_length=20, blank=True)
    # Our own clustering key -- see crm/dedup.py. Broader than dup_group.
    dedup_key = models.CharField(max_length=32, blank=True, db_index=True)

    source_tab = models.CharField(max_length=120, blank=True)
    source_row = models.IntegerField(null=True, blank=True)
    source_url = models.URLField(max_length=700, blank=True)

    # --- what it is -----------------------------------------------------
    ref = models.CharField('реф. №', max_length=80, blank=True)
    title = models.CharField('комплекс / заглавие', max_length=400, blank=True)
    # Casefolded, unaccented, punctuation-stripped. Trigram-indexed: this is
    # what finds "Гранд Камелия" == "Grand Kamelia" across two agencies.
    title_norm = models.CharField(max_length=400, blank=True)

    location = models.CharField('населено място', max_length=120, blank=True, db_index=True)
    location_raw = models.CharField(max_length=300, blank=True)
    # True when `location` was recovered by salvage.py rather than parsed
    # directly, so match explanations can be honest about it.
    location_salvaged = models.BooleanField(default=False)

    deal_type = models.CharField('вид сделка', max_length=10,
                                 choices=DealType.choices, default=DealType.SALE, db_index=True)
    property_kind = models.CharField('вид имот', max_length=40, blank=True, db_index=True)
    type_raw = models.CharField(max_length=200, blank=True)

    # --- numbers --------------------------------------------------------
    price_eur = models.DecimalField('цена (EUR)', max_digits=12, decimal_places=2,
                                    null=True, blank=True, db_index=True)
    price_raw = models.CharField(max_length=120, blank=True)
    price_per_m2 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    prev_price_eur = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    bedrooms = models.IntegerField('спални', null=True, blank=True, db_index=True)
    area_m2 = models.DecimalField('площ (м²)', max_digits=8, decimal_places=2,
                                  null=True, blank=True, db_index=True)
    floor = models.IntegerField('етаж', null=True, blank=True)

    commission_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    commission_kind = models.CharField(max_length=20, blank=True)
    commission_raw = models.CharField(max_length=200, blank=True)
    commission_note = models.CharField(max_length=400, blank=True)

    maintenance_eur = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    maintenance_per_m2 = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    maintenance_raw = models.CharField(max_length=200, blank=True)

    # --- qualities ------------------------------------------------------
    view = models.CharField('гледка', max_length=300, blank=True)
    furnished = models.BooleanField('обзаведен', null=True, blank=True)
    documents = models.CharField(max_length=200, blank=True)
    status = models.CharField('статус', max_length=40, blank=True, db_index=True)
    ready_date = models.CharField(max_length=80, blank=True)
    notes = models.TextField('бележки', blank=True)

    listing_url = models.URLField(max_length=700, blank=True)
    photos_url = models.URLField(max_length=700, blank=True)
    video_url = models.URLField(max_length=700, blank=True)

    # Resolved feature tokens (sea_view, pool, act16, ...). True / False only --
    # a token the data does not settle is simply absent, which is what makes the
    # "unverified" band possible downstream.
    features = models.JSONField('характеристики', default=dict, blank=True)
    data_flags = models.JSONField(default=dict, blank=True)
    raw = models.JSONField(default=dict, blank=True)

    # Channel B only: how we know this listing exists. Never blank for web rows.
    evidence = models.JSONField(default=dict, blank=True)
    verified_by = models.ForeignKey('auth.User', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='verified_offers')
    verified_at = models.DateTimeField(null=True, blank=True)

    # --- lifecycle ------------------------------------------------------
    first_seen = models.DateField('първо видяна', db_index=True)
    last_seen = models.DateField('последно видяна', db_index=True)
    last_changed = models.DateField(null=True, blank=True)
    is_active = models.BooleanField('активна', default=True, db_index=True)
    times_seen = models.IntegerField(default=1)
    image_count = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'оферта'
        verbose_name_plural = 'оферти'
        ordering = ['-last_seen', 'price_eur']
        indexes = [
            # The Channel A hard filter runs over exactly these columns.
            models.Index(fields=['is_active', 'deal_type', 'property_kind', 'location'],
                         name='offer_channel_a_idx'),
            models.Index(fields=['is_active', 'price_eur'], name='offer_active_price_idx'),
            GinIndex(fields=['title_norm'], name='offer_title_trgm_idx',
                     opclasses=['gin_trgm_ops']),
            GinIndex(fields=['features'], name='offer_features_gin_idx'),
        ]

    def __str__(self):
        bits = [self.title or self.ref or 'оферта']
        if self.location:
            bits.append(self.location)
        if self.price_eur:
            bits.append(f'{self.price_eur:,.0f} €'.replace(',', ' '))
        return ' · '.join(bits)

    @property
    def price_dropped(self):
        return (self.prev_price_eur is not None and self.price_eur is not None
                and self.prev_price_eur > self.price_eur)

    @property
    def needs_verification(self):
        """A web find is hearsay until a human confirms it."""
        return self.source == OfferSource.WEB and self.verified_at is None


class OfferHistory(models.Model):
    """Field-level change log. Mirrors the crawler's TRACKED field list."""

    NEW, CHANGED, REMOVED, MERGED, RETURNED = 'new', 'changed', 'removed', 'merged', 'returned'
    EVENTS = [(NEW, 'нова'), (CHANGED, 'променена'), (REMOVED, 'премахната'),
              (MERGED, 'обединена'), (RETURNED, 'върната')]

    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name='history')
    event = models.CharField(max_length=20, choices=EVENTS)
    field = models.CharField(max_length=60, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    changed_on = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'промяна по оферта'
        verbose_name_plural = 'промени по офертите'
        ordering = ['-changed_on', '-id']

    def __str__(self):
        return f'{self.changed_on} {self.event} {self.field}'


class OfferImage(models.Model):
    offer = models.ForeignKey(Offer, on_delete=models.CASCADE, related_name='images')
    local_path = models.CharField(max_length=400)
    source_url = models.URLField(max_length=900, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    width = models.IntegerField(null=True, blank=True)
    height = models.IntegerField(null=True, blank=True)
    position = models.IntegerField(default=0)
    downloaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'снимка'
        verbose_name_plural = 'снимки'
        ordering = ['position', 'id']
        constraints = [models.UniqueConstraint(fields=['offer', 'sha256'],
                                               name='one_image_per_hash_per_offer')]

    def __str__(self):
        return self.local_path


class CrawlRun(models.Model):
    QUEUED, RUNNING, OK, PARTIAL, FAILED = 'queued', 'running', 'ok', 'partial', 'failed'
    STATUSES = [(QUEUED, 'в изчакване'), (RUNNING, 'тече'), (OK, 'успешно'),
                (PARTIAL, 'частично'), (FAILED, 'неуспешно')]

    # Two different crawls now write here, and they must not be mistaken for one
    # another: "the sheets are three days stale" is a real alarm, and a site
    # crawl finishing today must not silence it.
    SHEETS, SITES = 'sheets', 'sites'
    KINDS = [(SHEETS, 'ценови таблици'), (SITES, 'сайтове на агенциите')]

    kind = models.CharField('вид', max_length=10, choices=KINDS, default=SHEETS,
                            db_index=True)
    run_date = models.DateField(db_index=True)
    status = models.CharField(max_length=20, choices=STATUSES, default=QUEUED)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    sources_ok = models.IntegerField(default=0)
    sources_dead = models.IntegerField(default=0)
    sources_skipped = models.IntegerField(default=0)
    offers_total = models.IntegerField(default=0)
    offers_new = models.IntegerField(default=0)
    offers_changed = models.IntegerField(default=0)
    offers_gone = models.IntegerField(default=0)
    log = models.TextField(blank=True)

    class Meta:
        verbose_name = 'обхождане'
        verbose_name_plural = 'обхождания'
        ordering = ['-run_date', '-id']

    def __str__(self):
        return f'{self.run_date} ({self.get_status_display()})'


class SheetSnapshot(models.Model):
    """Per-agency content hash for one crawl.

    The hash covers the workbook's *contents*, not the downloaded bytes: Google
    re-zips on every export, so hashing the file reported 17 of 29 sources as
    changed on a morning when only 4 actually were.
    """

    run = models.ForeignKey(CrawlRun, on_delete=models.CASCADE, related_name='snapshots')
    agency = models.ForeignKey(Agency, on_delete=models.CASCADE, related_name='snapshots')
    sha256 = models.CharField(max_length=64, blank=True)
    changed = models.BooleanField(default=False)
    offers_count = models.IntegerField(default=0)
    http_status = models.IntegerField(null=True, blank=True)
    error = models.TextField(blank=True)
    file_path = models.CharField(max_length=400, blank=True)

    class Meta:
        verbose_name = 'снимка на таблица'
        verbose_name_plural = 'снимки на таблиците'
        constraints = [models.UniqueConstraint(fields=['run', 'agency'],
                                               name='one_snapshot_per_agency_per_run')]

    def __str__(self):
        return f'{self.agency.slug} @ {self.run.run_date}'
