# -*- coding: utf-8 -*-
"""The main photo of a listing -- one per offer, not the whole gallery.

Why only one. A gallery is twenty to forty files per listing, which across
11 000 listings is a quarter of a million requests against agencies we have no
relationship with, for pictures we do not have the right to republish anyway.
One photo is enough for what the product actually needs:

  * a thumbnail on a result card, shown with attribution and a link back to
    the agency, which is the copyright posture in docs/CRAWL-POLICY.md;
  * a sha256 that phase 5b can cluster on. Developers hand every agency the
    same render pack, so one shared cover image is decisive evidence that two
    differently-named listings are the same building.

`og:image` is tried first everywhere. It is not a guess: it is the picture the
agency itself nominates as representing this listing, which is the definition
of "main image". Per-site regexes in sites_varna.IMAGE_HINTS are fallbacks.
"""
import hashlib
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from django.conf import settings

from market import sites_varna
from sourcing.web import fetch

OG_IMAGE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:image(?::url)?["\'][^>]+content=["\']([^"\']+)["\']',
    re.I)
OG_IMAGE_REVERSED = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image(?::url)?["\']',
    re.I)
TWITTER_IMAGE = re.compile(
    r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']', re.I)
LD_IMAGE = re.compile(r'"image"\s*:\s*(?:\[\s*)?["\']([^"\']+)["\']', re.I)

# Sprites, logos, placeholders and tracking pixels. A listing whose "main
# image" is the agency's own logo is worse than no image: it would cluster
# every listing on that site into one building.
JUNK = re.compile(r'(logo|placeholder|no[-_]?photo|no[-_]?image|default|sprite|'
                  r'avatar|favicon|watermark|blank|pixel|loading|spinner)', re.I)
IMAGE_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif')
MIN_BYTES = 3_000          # below this it is an icon, not a photograph


def candidates(html, page_url, agency_slug=''):
    """Main-image URLs for this page, best first."""
    out = []
    for pattern in (OG_IMAGE, OG_IMAGE_REVERSED, TWITTER_IMAGE, LD_IMAGE):
        out.extend(pattern.findall(html))
    for pattern in sites_varna.IMAGE_HINTS.get(agency_slug, ()):
        out.extend(re.findall(pattern, html, re.I))

    seen, kept = set(), []
    for raw in out:
        url = urljoin(page_url, raw.strip().replace('&amp;', '&'))
        if url in seen or JUNK.search(url):
            continue
        path = urlsplit(url).path.lower()
        if not path.endswith(IMAGE_EXT) and 'image' not in url.lower():
            continue
        seen.add(url)
        kept.append(url)
    return kept


def store_dir(agency_slug):
    return Path(settings.IMAGES_DIR) / agency_slug


def fetch_main(html, page_url, agency_slug):
    """Download the one main photo. Returns a dict, or None with a reason.

    Never raises: a missing photo must not cost us the listing it belongs to.
    """
    urls = candidates(html, page_url, agency_slug)
    if not urls:
        return None, 'no candidate'

    for url in urls[:3]:
        blob = fetch_bytes(url)
        if blob is None or len(blob) < MIN_BYTES:
            continue
        if not looks_like_image(blob):
            continue
        digest = hashlib.sha256(blob).hexdigest()
        suffix = extension_for(blob, url)
        folder = store_dir(agency_slug)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'{digest[:24]}{suffix}'
        if not path.exists():
            path.write_bytes(blob)
        return {
            'source_url': url,
            'local_path': str(path.relative_to(settings.DATA_DIR)),
            'sha256': digest,
            'bytes': len(blob),
        }, ''
    return None, f'{len(urls)} candidates, none fetched'


def fetch_bytes(url, timeout=45):
    """Download binary, as binary.

    The first version of this routed images through the crawler's fetch.get,
    which decodes responses to text. Every byte that is not valid UTF-8 became
    U+FFFD on the way in and was dropped again on the way out, so 816 stored
    "images" were corrupt files with a mangled RIFF header that no browser
    would render. A text pipe cannot carry a JPEG. curl writes to disk instead.
    """
    from django.conf import settings as _s
    host_wait(url)
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        path = handle.name
    try:
        proc = subprocess.run(
            ['curl', '-sSL', '-A', getattr(_s, 'CRAWL_USER_AGENT_BOT', 'VarnaMarketBot/0.1'),
             '--max-time', str(timeout), '--max-filesize', '8000000',
             '-o', path, '-w', '%{http_code}', url],
            capture_output=True, text=True)
        if (proc.stdout or '').strip() != '200':
            return None
        return Path(path).read_bytes()
    except OSError:
        return None
    finally:
        Path(path).unlink(missing_ok=True)


def host_wait(url):
    """Reuse the crawler's own per-host rate limiter, so images do not become
    a second, unthrottled stream of requests at the same site."""
    try:
        fetch._wait(urlsplit(url).hostname or '')
    except Exception:                                              # noqa: BLE001
        pass


MAGIC = (
    (b'\xff\xd8\xff', 'jpg'),
    (b'\x89PNG\r\n\x1a\n', 'png'),
    (b'GIF8', 'gif'),
)


def looks_like_image(blob):
    """Check the file's own header. The stored extension proved nothing: the
    corrupt files all ended in .webp and none of them were webp."""
    if any(blob.startswith(sig) for sig, _ext in MAGIC):
        return True
    return blob[:4] == b'RIFF' and blob[8:12] == b'WEBP'


def extension_for(blob, url):
    for sig, ext in MAGIC:
        if blob.startswith(sig):
            return '.' + ext
    if blob[:4] == b'RIFF' and blob[8:12] == b'WEBP':
        return '.webp'
    return next((e for e in IMAGE_EXT if urlsplit(url).path.lower().endswith(e)), '.jpg')
