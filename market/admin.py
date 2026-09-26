from django.contrib import admin

from market.models import City, Country, Neighbourhood, NeighbourhoodAlias, OfferGeo, SiteProbe


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ('code', 'name')


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ('name_bg', 'slug', 'country', 'active')
    list_filter = ('country', 'active')
    search_fields = ('name_bg', 'name_en', 'slug')


class AliasInline(admin.TabularInline):
    model = NeighbourhoodAlias
    extra = 0


@admin.register(Neighbourhood)
class NeighbourhoodAdmin(admin.ModelAdmin):
    list_display = ('name_bg', 'city', 'slug', 'active')
    list_filter = ('city', 'active')
    search_fields = ('name_bg', 'name_en', 'slug')
    inlines = (AliasInline,)


@admin.register(OfferGeo)
class OfferGeoAdmin(admin.ModelAdmin):
    list_display = ('offer_id', 'city', 'neighbourhood', 'confidence', 'matched_by')
    list_filter = ('city', 'neighbourhood', 'matched_by', 'offer__agency', 'offer__is_active')
    search_fields = ('raw_location', 'offer__title', 'offer__fingerprint')
    raw_id_fields = ('offer',)
    list_select_related = ('city', 'neighbourhood')
    readonly_fields = ('raw_location', 'normalized_location', 'matched_by')

    def save_model(self, request, obj, form, change):
        obj.matched_by = 'manual'
        super().save_model(request, obj, form, change)


@admin.register(SiteProbe)
class SiteProbeAdmin(admin.ModelAdmin):
    list_display = ('agency_slug', 'city', 'status', 'run_id', 'probed_at')
    list_filter = ('city', 'status', 'run_id')
    search_fields = ('agency_slug', 'website')
