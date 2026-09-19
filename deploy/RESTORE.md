# Restoring the bundle on the server

## ⚠️ Read this before loading the database

**If the server has been crawling, this dump will destroy what it learned.**

`first_seen`, the price history in `offer_history`, and every change the server
recorded while the laptop was not looking live only in the server's own
database. Loading a laptop dump over it replaces all of that silently — the
row counts afterwards look healthy, and the history is gone.

So:

- **Server has never crawled** → load the dump. Nothing to lose.
- **Server has been crawling** → do not load it. Pull the server's data *down*
  instead, or merge deliberately. A one-way copy is only safe in one direction,
  and it is not this one.

Check before deciding:

```bash
psql -d varna_market -tAc \
  "SELECT min(first_seen)::date, max(last_seen)::date, count(*) FROM sourcing_offer;"
```

If that returns rows with dates the laptop has never seen, stop.

## Restore

```bash
cd /srv/varna-market

# 1. Database
createdb varna_market                      # first time only
pg_restore --no-owner --no-privileges -d varna_market incoming/varna_market-*.dump

# 2. Photos — content-hashed filenames, so this never overwrites a good file
tar -xzf incoming/images-*.tar.gz -C data/

# 3. Page snapshots, if they were included
tar -xzf incoming/runs-*.tar.gz -C data/ 2>/dev/null || true

# 4. Schema up to date with the code
./.venv/bin/python manage.py migrate
```

## Verify

```bash
./.venv/bin/python manage.py vendor_check          # vendored copy intact
./.venv/bin/python manage.py test                  # 90 tests
./.venv/bin/python manage.py repair_images --check-only
```

`repair_images --check-only` reads each stored file's **magic bytes**, not its
extension. That distinction matters: 1 499 images were once stored corrupt
under a `.webp` name, and not one of them was a webp.

## Serve

```bash
./.venv/bin/pip install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
./.venv/bin/python manage.py collectstatic --noinput
```

nginx serves `staticfiles/` and `data/` (as `/media/`); gunicorn runs
`config.wsgi`. The nightly crawl is a systemd timer running:

```bash
./.venv/bin/python manage.py crawl_live      # hand-written sources
./.venv/bin/python manage.py crawl_auto      # probe-derived sources
```

Crawl only overnight, and keep `CRAWL_HOST_DELAY` at 2s or higher. Politeness
here is self-interest, not courtesy: a banned IP yields nothing at all. See
`docs/CRAWL-POLICY.md`.
