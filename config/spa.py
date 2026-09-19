# -*- coding: utf-8 -*-
"""Serve the built Vue app, and let its deep links survive a page reload.

vue-router owns /imot/123 and /agencii. Django knows nothing about them, so
without this a refresh on a listing page returns 404. Anything that is not the
API, the admin or a static file gets index.html and the router takes over.
"""
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse

INDEX = Path(settings.BASE_DIR) / 'frontend' / 'dist' / 'index.html'


def index(request):
    if not INDEX.exists():
        raise Http404('The frontend is not built. Run `npm run build` in frontend/.')
    # No rewriting here: vite.config.js sets base:'/static/', so the bundle
    # already asks for the right paths -- including the router's lazy chunks,
    # which are requested at runtime and never appear in this HTML.
    return HttpResponse(INDEX.read_text(encoding='utf-8'))
