# -*- coding: utf-8 -*-
"""URL map: a JSON API, the admin, and the built Vue app over everything else."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, re_path

from config import spa
from market import api
from market import buyer

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/offers/', api.offers),
    path('api/cities/', api.cities),
    path('api/neighbourhoods/', api.neighbourhoods),
    path('api/offers/<int:pk>/', api.offer_detail),
    path('api/facets/', api.facets),
    path('api/agencies/', api.agencies),
    path('api/stats/', api.stats),
    path('api/buyer/options/', buyer.options),
    path('api/buyer/matches/', buyer.matches),
    path('api/buyer/wishlist/', buyer.wishlist),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Last: everything the API and admin did not claim belongs to vue-router.
urlpatterns += [re_path(r'^(?!api/|admin/|static/|media/).*$', spa.index)]
