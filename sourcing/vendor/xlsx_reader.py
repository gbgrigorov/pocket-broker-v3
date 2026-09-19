"""Dependency-free .xlsx reader (zipfile + ElementTree).

Returns, per worksheet: the cell grid, the hyperlink map, and any embedded
media, so the pipeline never needs openpyxl/pandas installed on this machine.
"""
import re, zipfile
from xml.etree import ElementTree as ET

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
RNS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def col_to_idx(ref):
    n = 0
    for c in re.match(r'([A-Z]*)', ref).group(1):
        n = n * 26 + (ord(c) - 64)
    return n - 1


def idx_to_col(i):
    s = ''
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _shared_strings(z):
    out = []
    if 'xl/sharedStrings.xml' in z.namelist():
        for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall(NS + 'si'):
            out.append(''.join(t.text or '' for t in si.iter(NS + 't')))
    return out


def _date_styles(z):
    """Style indexes whose number format is a date/time, so serials can be
    turned back into dates instead of showing up as 45810."""
    if 'xl/styles.xml' not in z.namelist():
        return set()
    root = ET.fromstring(z.read('xl/styles.xml'))
    date_fmt_ids = {14, 15, 16, 17, 22, 27, 30, 36, 45, 46, 47, 50, 57, 58}
    for nf in root.iter(NS + 'numFmt'):
        code = (nf.get('formatCode') or '').lower()
        if re.search(r'(yy|dd|mm)', code) and '\\' not in code[:2]:
            date_fmt_ids.add(int(nf.get('numFmtId')))
    styles = set()
    cellxfs = root.find(NS + 'cellXfs')
    if cellxfs is not None:
        for i, xf in enumerate(cellxfs):
            if int(xf.get('numFmtId', 0)) in date_fmt_ids:
                styles.add(i)
    return styles


def _serial_to_date(v):
    from datetime import datetime, timedelta
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not 1 < f < 60000:
        return None
    return (datetime(1899, 12, 30) + timedelta(days=f)).date().isoformat()


def read_workbook(path, max_rows=100000):
    z = zipfile.ZipFile(path)
    shared = _shared_strings(z)
    datestyles = _date_styles(z)
    names = z.namelist()

    wb = ET.fromstring(z.read('xl/workbook.xml'))
    rels = {r.get('Id'): r.get('Target')
            for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}

    sheets = []
    for sh in wb.find(NS + 'sheets'):
        tgt = rels.get(sh.get(RNS + 'id'), '')
        if not tgt:
            continue
        if not tgt.startswith('xl/'):
            tgt = 'xl/' + tgt.lstrip('/')
        if tgt not in names:
            continue
        sheets.append({'name': sh.get('name'), 'path': tgt,
                       'hidden': sh.get('state') in ('hidden', 'veryHidden')})

    out = []
    for s in sheets:
        root = ET.fromstring(z.read(s['path']))
        grid = []
        for row in root.iter(NS + 'row'):
            cells = {}
            for c in row.findall(NS + 'c'):
                t, sidx = c.get('t'), c.get('s')
                v, isel = c.find(NS + 'v'), c.find(NS + 'is')
                if t == 's' and v is not None:
                    val = shared[int(v.text)]
                elif t == 'inlineStr' and isel is not None:
                    val = ''.join(x.text or '' for x in isel.iter(NS + 't'))
                elif v is not None:
                    val = v.text
                    if sidx and int(sidx) in datestyles:
                        val = _serial_to_date(val) or val
                else:
                    val = None
                if val is not None and str(val).strip():
                    cells[col_to_idx(c.get('r') or '')] = str(val).strip()
            grid.append([cells.get(i, '') for i in range(max(cells) + 1)] if cells else [])
            if len(grid) >= max_rows:
                break

        relpath = s['path'].replace('xl/worksheets/', 'xl/worksheets/_rels/') + '.rels'
        relmap = {}
        if relpath in names:
            for r in ET.fromstring(z.read(relpath)):
                relmap[r.get('Id')] = r.get('Target')
        links = {}
        hl = root.find(NS + 'hyperlinks')
        if hl is not None:
            for h in hl:
                tgt = relmap.get(h.get(RNS + 'id')) or h.get('location') or ''
                for ref in _expand(h.get('ref')):
                    links[ref] = tgt
        out.append({**s, 'grid': grid, 'links': links})

    media = [n for n in names if n.startswith('xl/media/')]
    return {'sheets': out, 'media': media, 'zip': z}


def _expand(ref):
    """'B2' -> ['B2'];  'B2:B5' -> ['B2','B3','B4','B5']"""
    if ':' not in ref:
        return [ref]
    a, b = ref.split(':')
    m1, m2 = re.match(r'([A-Z]+)(\d+)', a), re.match(r'([A-Z]+)(\d+)', b)
    if not (m1 and m2):
        return [a]
    out = []
    for ci in range(col_to_idx(m1.group(1)), col_to_idx(m2.group(1)) + 1):
        for ri in range(int(m1.group(2)), min(int(m2.group(2)), int(m1.group(2)) + 2000) + 1):
            out.append(f'{idx_to_col(ci)}{ri}')
    return out
