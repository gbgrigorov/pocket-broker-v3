"""Small conservative HTTP client for verified public source adapters.

Keeps original bytes for charset decoding. One synchronous request at a time;
stops the source at the first block/rate-limit/challenge, without retry tricks.
"""
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from sourcing.web import fetch


class SourceBlocked(RuntimeError):
    pass


def decode_html(blob, content_type=''):
    head = blob[:8192].decode('ascii', errors='ignore')
    match = re.search(r'charset\s*=\s*["\']?([\w-]+)', content_type, re.I)
    match = match or re.search(r'charset\s*=\s*["\']?([\w-]+)', head, re.I)
    encoding = match.group(1).lower() if match else 'utf-8'
    # HTML interprets the legacy Latin-1 label as Windows-1252 (smart punctuation).
    if encoding in ('iso-8859-1', 'latin1', 'latin-1'):
        encoding = 'cp1252'
    try:
        return blob.decode(encoding, errors='replace'), encoding
    except LookupError:
        return blob.decode('utf-8', errors='replace'), 'utf-8'


class SourceClient:
    def __init__(self, hosts):
        self.hosts = set(hosts)
        self.blocked = False
        self.responses = []

    def check_url(self, url):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in self.hosts
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise ValueError('Source URL outside verified HTTPS hosts')

    def get(self, url, *, binary=False):
        if self.blocked:
            raise SourceBlocked('Source stopped after an earlier block')
        self.check_url(url)
        for _ in range(4):
            fetch._wait(urlsplit(url).hostname)
            with tempfile.TemporaryDirectory(prefix='pocket-source-') as folder:
                body_path, headers_path = Path(folder) / 'body', Path(folder) / 'headers'
                proc = subprocess.run([
                    'curl', '-sS', '--compressed', '--proto', '=https',
                    '--max-time', str(getattr(settings, 'CRAWL_TIMEOUT', 90)),
                    '--max-filesize', '3000000', '-A', settings.CRAWL_USER_AGENT_BOT,
                    '-D', str(headers_path), '-o', str(body_path), '-w', '%{http_code}', url,
                ], capture_output=True)
                blob = body_path.read_bytes() if body_path.exists() else b''
                headers = {}
                if headers_path.exists():
                    for line in headers_path.read_text(encoding='latin-1').splitlines():
                        key, separator, value = line.partition(':')
                        if separator:
                            headers[key.lower().strip()] = value.strip()
                status = int(proc.stdout.strip() or 0)
                body, encoding = decode_html(blob, headers.get('content-type', ''))
                response = {'url': url, 'final_url': url, 'status': status, 'body': body,
                            'encoding': encoding, 'bytes': len(blob), 'headers': headers,
                            'ok': status == 200 and proc.returncode == 0,
                            'error': proc.stderr.decode(errors='replace')[:200] if proc.returncode else ''}
                if binary:
                    response['blob'] = blob
                self.responses.append({k: response[k] for k in ('url', 'status', 'encoding', 'bytes', 'error')})
                challenge = re.search(
                    r'<title[^>]*>\s*(?:just a moment|access denied|attention required|'
                    r'verify (?:that )?you are human|security (?:check|verification)|captcha)'
                    r'|/cdn-cgi/challenge-platform/|\bid=["\']cf-chl-', body, re.I)
                if status in (401, 403, 429, 503) or challenge:
                    self.blocked = True
                    raise SourceBlocked(f'HTTP {status}: source stopped at {url}')
                if status in (301, 302, 303, 307, 308) and headers.get('location'):
                    url = urljoin(url, headers['location'])
                    self.check_url(url)
                    continue
                return response
        raise ValueError('Too many source redirects')
