"""Parse the master agency registry (Морски фирми-1.xlsx) into agencies.json.

The xlsx is read with the standard library only (zipfile + ElementTree) so the
project has no third-party dependency just to bootstrap itself.
"""
import json, re, sys, zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs
from xml.etree import ElementTree as ET

import phones as phone_utils

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
RNS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

ROOT = Path(__file__).resolve().parent.parent
XLSX = ROOT / 'assets' / 'Морски фирми-1.xlsx'
OUT = ROOT / 'data' / 'agencies.json'


def _col(ref):
    n = 0
    for c in re.match(r'([A-Z]+)', ref).group(1):
        n = n * 26 + (ord(c) - 64)
    return n - 1


def read_sheet(path):
    z = zipfile.ZipFile(path)
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall(NS + 'si'):
            shared.append(''.join(t.text or '' for t in si.iter(NS + 't')))
    root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    rows = {}
    for row in root.iter(NS + 'row'):
        r = int(row.get('r'))
        cells = {}
        for c in row.findall(NS + 'c'):
            v, t = c.find(NS + 'v'), c.get('t')
            if t == 's' and v is not None:
                val = shared[int(v.text)]
            elif v is not None:
                val = v.text
            else:
                val = None
            if val and val.strip():
                cells[_col(c.get('r'))] = val.strip()
        if cells:
            rows[r] = cells
    relmap = {}
    relp = 'xl/worksheets/_rels/sheet1.xml.rels'
    if relp in z.namelist():
        for r in ET.fromstring(z.read(relp)):
            relmap[r.get('Id')] = r.get('Target')
    links = {}
    hl = root.find(NS + 'hyperlinks')
    if hl is not None:
        for h in hl:
            links[h.get('ref')] = relmap.get(h.get(RNS + 'id'), '')
    return rows, links


def unwrap(url):
    """Unwrap facebook l.php redirects and strip tracking noise."""
    if not url:
        return url
    if 'l.facebook.com/l.php' in url or 'lm.facebook.com/l.php' in url:
        q = parse_qs(urlparse(url).query)
        if q.get('u'):
            url = unquote(q['u'][0])
    return url.split('&fbclid=')[0].strip()


SHEET_ID = re.compile(r'/spreadsheets/d/([a-zA-Z0-9-_]+)')
FILE_ID = re.compile(r'/file/d/([a-zA-Z0-9-_]+)')


def classify(url):
    """Return (kind, doc_id, gid) for a source link."""
    if not url:
        return 'none', None, None
    m = SHEET_ID.search(url)
    if m:
        gid = parse_qs(urlparse(url).fragment or urlparse(url).query).get('gid', [None])[0]
        if gid is None and '#gid=' in url:
            gid = url.split('#gid=')[1].split('&')[0]
        return 'gsheet', m.group(1), gid
    m = FILE_ID.search(url)
    if m:
        return 'gdrive_file', m.group(1), None
    host = urlparse(url).netloc.lower()
    if 'dropbox' in host:
        return 'dropbox', None, None
    if 'yandex' in host:
        return 'yandex', None, None
    if 'drive.google.com' in host:
        return 'gdrive_folder', None, None
    return 'other', None, None


def mark_duplicate_sources(agencies):
    """Flag registry rows that point at one and the same document.

    The master file lists a few companies twice under slightly different names
    (Lodax / LODAX ESTATE). Crawling both means every one of their offers is
    stored, counted and shown twice. The first row wins; the rest keep their
    contact details but are never fetched or parsed.
    """
    primary, aliases = {}, []
    for a in agencies:
        if not a.get('doc_id'):
            continue
        key = (a['source_kind'], a['doc_id'])
        if key not in primary:
            primary[key] = a['slug']
        elif primary[key] != a['slug']:
            a['duplicate_of'] = primary[key]
            aliases.append((a['slug'], primary[key]))
        # Same company entered twice under the same name collapses on the slug
        # by itself - nothing to alias.
    return aliases


def main():
    rows, links = read_sheet(XLSX)
    agencies = []
    for rnum in sorted(rows):
        if rnum == 1:
            continue  # header
        c = rows[rnum]
        name = (c.get(1) or '').strip()
        if not name or name == 'Име на фирма':
            continue  # header row (the sheet's real header sits on row 2)
        raw_url = links.get(f'C{rnum}') or c.get(2) or ''
        url = unwrap(raw_url)
        kind, doc_id, gid = classify(url)
        site = unwrap(links.get(f'F{rnum}') or c.get(5) or '')
        email = (links.get(f'G{rnum}') or c.get(6) or '').replace('mailto:', '').strip()
        contact_raw = (c.get(3) or '').strip()
        phone_raw = (c.get(4) or '').strip()
        agencies.append({
            'site_no': (c.get(0) or '').strip(),
            'slug': re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-'),
            'name': re.sub(r'\s+', ' ', name),
            'source_url': url,
            'source_kind': kind,
            'doc_id': doc_id,
            'gid': gid,
            'contact_name': re.sub(r'\s+', ' ', contact_raw),
            'phones': phone_utils.extract(phone_raw, contact_raw),
            'phone_raw': re.sub(r'\s+', ' ', phone_raw),
            'website': site if site.startswith('http') else ('https://' + site.strip() if site.strip() else ''),
            'email': email,
            'row': rnum,
        })
    aliases = mark_duplicate_sources(agencies)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(agencies, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(agencies)} agencies -> {OUT}')
    for a, primary in aliases:
        print(f'  ALIAS: {a} -> {primary} (same source document)')
    kinds = {}
    for a in agencies:
        kinds[a['source_kind']] = kinds.get(a['source_kind'], 0) + 1
    print('source kinds:', kinds)


if __name__ == '__main__':
    main()
