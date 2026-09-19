# -*- coding: utf-8 -*-
"""Getting a page, politely, and keeping a copy of what we got.

One request per second per host, a user agent that names us and links somewhere
a webmaster can complain, and gzipped snapshots on disk. The snapshot is not
bureaucracy: it is what lets the extractor be improved and re-run over last
night's crawl without touching anybody's server again.
"""
import gzip
import hashlib
import subprocess
import threading
import time
from urllib.parse import urlsplit

from django.conf import settings

# DIVERGENCE from broker-crm. Upstream hardcodes
#   'BrokerCRM/1.0 (+https://bg-apartment.com)'
# which names a different project and points any webmaster who wants to
# complain at somebody else's website. Identifying our crawler as someone
# else's is not a cosmetic difference, so this reads the setting instead.
from django.conf import settings as _settings

USER_AGENT = getattr(_settings, 'CRAWL_USER_AGENT_BOT',
                     'VarnaMarketBot/0.1 (+https://github.com/gbgrigorov/varna-market)')
DELAY_SECONDS = float(getattr(_settings, 'CRAWL_HOST_DELAY', 2.0))
MAX_BYTES = 1_500_000

_locks = {}
_last = {}
_guard = threading.Lock()


def _host(url):
    return (urlsplit(url).hostname or '').lower()


def _wait(host):
    """Never two requests to one host inside DELAY_SECONDS."""
    with _guard:
        lock = _locks.setdefault(host, threading.Lock())
    with lock:
        gap = time.monotonic() - _last.get(host, 0.0)
        if gap < DELAY_SECONDS:
            time.sleep(DELAY_SECONDS - gap)
        _last[host] = time.monotonic()


def get(url, timeout=30, polite=True):
    """Fetch one URL. Returns {status, body, size, final_url}."""
    if polite:
        _wait(_host(url))
    result = subprocess.run(
        ['curl', '-sSL', '-A', USER_AGENT, '--max-time', str(timeout), '--compressed',
         '--max-filesize', str(MAX_BYTES),
         '-w', '\n@@%{http_code}@@%{size_download}@@%{url_effective}', url],
        capture_output=True, text=True, errors='replace')
    body, sep, meta = result.stdout.rpartition('\n@@')
    if not sep:
        return {'status': 0, 'body': '', 'size': 0, 'final_url': url,
                'error': (result.stderr or 'няма отговор').strip()[:200]}
    status, size, final = (meta.split('@@') + ['', '', ''])[:3]
    return {'status': int(status or 0), 'body': body[:MAX_BYTES],
            'size': int(size or 0), 'final_url': final or url, 'error': ''}


def snapshot_path(run_id, agency_slug, url):
    digest = hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]
    return (settings.RUNS_DIR / str(run_id) / 'pages' / agency_slug / f'{digest}.html.gz')


def save_snapshot(run_id, agency_slug, url, html):
    """Store the page we read, compressed. Returns a BASE_DIR-relative path."""
    path = snapshot_path(run_id, agency_slug, url)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wt', encoding='utf-8') as handle:
        handle.write(html)
    return str(path.relative_to(settings.BASE_DIR))


def read_snapshot(relative_path):
    """Read a saved page, compressed or not.

    Channel B's agent-driven ingest writes plain .html; this crawler gzips. Both
    are snapshots of a page somebody read, and both must stay readable.
    """
    path = settings.BASE_DIR / relative_path
    with open(path, 'rb') as handle:
        head = handle.read(2)
    if head == b'\x1f\x8b':
        with gzip.open(path, 'rt', encoding='utf-8', errors='replace') as handle:
            return handle.read()
    return path.read_text(encoding='utf-8', errors='replace')
