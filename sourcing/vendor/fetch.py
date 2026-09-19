"""Download a raw snapshot of every live agency source.

Snapshots land in data/raw/<slug>/<YYYY-MM-DD>.xlsx and are content-hashed, so
an unchanged sheet costs one request and zero extra disk. The hash is what the
daily diff is built on.

The hash is taken over the workbook's *contents*, never over the downloaded
file: Google rebuilds the .xlsx on every export with fresh zip timestamps, so
two byte-different downloads of an untouched sheet are routine. Hashing the
file made 17 of 29 sources report a change on a day when exactly one sheet had
actually been edited.
"""
import hashlib, json, shutil, subprocess, sys, zipfile
from datetime import date
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / 'data' / 'raw'
STATE = ROOT / 'data' / 'fetch_state.json'
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
TODAY = date.today().isoformat()


# Parts that describe the document rather than its data. Google stamps these
# per export, so they must not take part in the comparison.
VOLATILE = ('docProps/', 'xl/calcChain.xml', '_rels/', '[Content_Types].xml')


def content_sha256(path):
    """Hash what the workbook says, not the container it arrived in.

    Falls back to the raw bytes if the file is not a readable zip, so a PDF or
    a truncated download still gets a stable identity.
    """
    try:
        with zipfile.ZipFile(path) as z:
            parts = []
            for name in sorted(z.namelist()):
                if name.endswith('/') or name.startswith(VOLATILE):
                    continue
                parts.append(name.encode('utf-8'))
                parts.append(hashlib.sha256(z.read(name)).digest())
        return hashlib.sha256(b''.join(parts)).hexdigest()
    except (zipfile.BadZipFile, OSError):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def export_url(a):
    if a['source_kind'] == 'gsheet':
        return f"https://docs.google.com/spreadsheets/d/{a['doc_id']}/export?format=xlsx"
    if a['source_kind'] == 'gdrive_file':
        return f"https://drive.google.com/uc?export=download&id={a['doc_id']}"
    return None


def fetch_one(a):
    url = export_url(a)
    rec = {'slug': a['slug'], 'name': a['name'], 'date': TODAY, 'url': url}
    if a.get('duplicate_of'):
        return {**rec, 'status': 'alias', 'duplicate_of': a['duplicate_of'],
                'reason': f"same document as {a['duplicate_of']}"}
    if not url:
        return {**rec, 'status': 'skipped', 'reason': f"no export url ({a['source_kind']})"}
    dest_dir = RAW / a['slug']
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / f'.{TODAY}.part'
    try:
        r = subprocess.run(
            ['curl', '-sSL', '-A', UA, '--max-time', '90', '--retry', '2',
             '-o', str(tmp), '-w', '%{http_code}|%{content_type}', url],
            capture_output=True, text=True, timeout=180)
        code, ctype = r.stdout.split('|', 1)
    except Exception as e:
        return {**rec, 'status': 'error', 'reason': str(e)}
    if code != '200' or not ('spreadsheet' in ctype or 'octet-stream' in ctype or 'excel' in ctype):
        tmp.unlink(missing_ok=True)
        reason = 'deleted by owner' if code == '410' else f'http {code} ({ctype.split(";")[0]})'
        return {**rec, 'status': 'dead', 'reason': reason}
    dest = dest_dir / f'{TODAY}.xlsx'
    shutil.move(str(tmp), str(dest))
    digest = content_sha256(dest)
    return {**rec, 'status': 'ok', 'sha256': digest, 'bytes': dest.stat().st_size,
            'file_sha256': hashlib.sha256(dest.read_bytes()).hexdigest(),
            'path': str(dest.relative_to(ROOT))}


def main():
    agencies = json.loads((ROOT / 'data' / 'agencies.json').read_text(encoding='utf-8'))
    prev = json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(fetch_one, agencies))
    state, changed, dead = {}, [], []
    for r in results:
        if r['status'] == 'ok':
            was = prev.get(r['slug'], {}).get('sha256')
            r['changed'] = was != r['sha256']
            if r['changed']:
                changed.append(r['name'])
            state[r['slug']] = {'sha256': r['sha256'], 'date': TODAY, 'name': r['name']}
        elif r['status'] == 'dead':
            dead.append(f"{r['name']}: {r['reason']}")
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    (ROOT / 'data' / f'fetch_log_{TODAY}.json').write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    ok = sum(1 for r in results if r['status'] == 'ok')
    print(f'fetched {ok}/{len(results)}  changed={len(changed)}  dead={len(dead)}')
    for d in dead:
        print('  DEAD:', d)
    return results


if __name__ == '__main__':
    main()
