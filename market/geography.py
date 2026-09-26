"""Geography hooks and city-scoped property grouping, owned by this application."""
from django.apps import apps
from django.db.models.signals import post_save
from django.dispatch import receiver

from market.geography_seed_v1 import catalogue, resolve_values
from market.models import OfferGeo


@receiver(post_save, sender='sourcing.Offer', dispatch_uid='market.offer_geography')
def resolve_offer(sender, instance, raw=False, using='default', **kwargs):
    if raw:
        return
    cities, aliases = catalogue(apps, using)
    existing = OfferGeo.objects.using(using).filter(offer_id=instance.pk).first()
    if existing and existing.matched_by == 'manual':
        return
    values = resolve_values(instance, cities, aliases)
    OfferGeo.objects.using(using).update_or_create(offer_id=instance.pk, defaults=values)


def siblings_for(offer, queryset):
    geo = getattr(offer, 'geo', None)
    if not offer.dedup_key or not geo or not geo.city_id:
        return queryset.none()
    return queryset.filter(dedup_key=offer.dedup_key, geo__city_id=geo.city_id,
                           deal_type=offer.deal_type).exclude(pk=offer.pk)


def cluster_key(offer):
    geo = getattr(offer, 'geo', None)
    if not offer.dedup_key or not geo or not geo.city_id:
        return ''
    return f'{geo.city.slug}:{offer.deal_type}:{offer.dedup_key}'
