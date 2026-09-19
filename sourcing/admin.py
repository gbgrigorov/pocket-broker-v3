# -*- coding: utf-8 -*-
from django.contrib import admin
from django.utils.html import format_html

from sourcing.models import (Agency, CrawlRun, Offer, OfferHistory, OfferImage,
                             SheetSnapshot)


@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'source_kind', 'site_link', 'offer_count',
                    'contact_name', 'crawl_opt_out', 'last_fetch')
    list_filter = ('source_kind', 'crawl_opt_out', 'source_status')
    search_fields = ('name', 'slug', 'contact_name', 'email', 'website')
    list_editable = ('crawl_opt_out',)
    readonly_fields = ('last_fetch', 'last_change', 'created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('name', 'slug', 'site_no', 'notes')}),
        ('Контакти', {'fields': ('contact_name', 'phones', 'email', 'website')}),
        ('Източник на офертите', {'fields': ('source_url', 'source_kind', 'doc_id', 'gid',
                                             'duplicate_of', 'source_status')}),
        ('Обхождане', {'fields': ('crawl_opt_out', 'last_fetch', 'last_change')}),
    )

    @admin.display(description='оферти', ordering='offers__count')
    def offer_count(self, obj):
        return obj.offers.filter(is_active=True).count()

    @admin.display(description='сайт')
    def site_link(self, obj):
        if not obj.website:
            return '—'
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>',
                           obj.website, obj.website[:34])


class OfferImageInline(admin.TabularInline):
    model = OfferImage
    extra = 0
    fields = ('preview', 'local_path', 'source_url')
    readonly_fields = ('preview', 'local_path', 'source_url')
    can_delete = False

    @admin.display(description='снимка')
    def preview(self, obj):
        return format_html('<img src="/media/{}" style="height:70px;border-radius:4px">',
                           obj.local_path)


class OfferHistoryInline(admin.TabularInline):
    model = OfferHistory
    extra = 0
    fields = ('changed_on', 'event', 'field', 'old_value', 'new_value')
    readonly_fields = fields
    can_delete = False
    ordering = ('-changed_on', '-id')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ('title_short', 'agency', 'location', 'price_display', 'bedrooms',
                    'area_m2', 'floor', 'source', 'status', 'is_active', 'last_seen')
    list_filter = ('is_active', 'source', 'deal_type', 'property_kind', 'status',
                   'location', 'location_salvaged', 'agency')
    search_fields = ('title', 'ref', 'location', 'location_raw', 'notes', 'fingerprint')
    date_hierarchy = 'last_seen'
    list_select_related = ('agency',)
    inlines = (OfferImageInline, OfferHistoryInline)
    readonly_fields = ('fingerprint', 'weak_core', 'dup_group', 'dedup_key', 'title_norm',
                       'identity_strength', 'features', 'data_flags', 'raw', 'evidence',
                       'first_seen', 'last_seen', 'last_changed', 'times_seen',
                       'created_at', 'updated_at')
    list_per_page = 40

    @admin.display(description='комплекс', ordering='title')
    def title_short(self, obj):
        return (obj.title or obj.ref or '—')[:46]

    @admin.display(description='цена', ordering='price_eur')
    def price_display(self, obj):
        if obj.price_eur is None:
            return '—'
        text = f'{obj.price_eur:,.0f} €'.replace(',', ' ')
        if obj.price_dropped:
            return format_html('<span style="color:#1a7f37">▼ {}</span>', text)
        return text


@admin.register(CrawlRun)
class CrawlRunAdmin(admin.ModelAdmin):
    list_display = ('run_date', 'status', 'sources_ok', 'sources_dead', 'sources_skipped',
                    'offers_total', 'offers_new', 'offers_changed', 'offers_gone',
                    'finished_at')
    list_filter = ('status',)
    date_hierarchy = 'run_date'
    readonly_fields = [f.name for f in CrawlRun._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(SheetSnapshot)
class SheetSnapshotAdmin(admin.ModelAdmin):
    list_display = ('agency', 'run', 'changed', 'offers_count', 'sha_short', 'error')
    list_filter = ('changed', 'run__run_date')
    search_fields = ('agency__name', 'agency__slug')
    list_select_related = ('agency', 'run')

    @admin.display(description='контролна сума')
    def sha_short(self, obj):
        return (obj.sha256 or '')[:12] or '—'
