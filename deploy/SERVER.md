# Pocket Broker v3 on the server — deployment contract

Written 2026-09-25, when v3 went live at **https://pb3.avaflow.xyz** (Let's
Encrypt cert to 2026-12-24, auto-renewing; HTTP 301s to HTTPS).
This is the live-truth document for how v3 runs on this box. `docs/OPERATIONS.md`
covers release *procedure*; this file covers the *shape* it releases into.

## The one thing to know first

**v3 runs side by side with the live Varna Market app. It does not replace it.**

| | live Varna Market | Pocket Broker v3 |
| --- | --- | --- |
| checkout | `/home/mvp/projects/varna-market` | `/home/mvp/projects/pocket-broker-v3` |
| hostname | `varna.avaflow.xyz` | `pb3.avaflow.xyz` |
| gunicorn | `127.0.0.1:8500` | `127.0.0.1:8501` |
| PM2 process | `varna` | `pb3` |
| webroot | `/var/www/varna` | `/var/www/pb3` |
| **database** | **`varna_market`** | **`pocket_broker_v3_phase1`** |
| migrations | market 0004 | market 0007 |

Both apps use the same PostgreSQL role (`varna_market`, which owns both
databases) and both read the same photo corpus. They do **not** share a
database, and that is deliberate.

## Why v3 has its own database

v3 carries migrations `0005_geography`, `0006_seed_geography_backfill` and
`0007_siteprobe_city_strategy`, which the live app has never seen. Running them
against `varna_market` would mutate the database that `varna.avaflow.xyz`
serves to users. `pocket_broker_v3_phase1` is the restored, checksum-verified
copy that Phase 1 validation already created and migrated (see
`docs/CURRENT-STATE.md` for the restore evidence and row checksums), so v3 was
simply pointed at it. Current contents: 2,572 offers (1,779 active), 139
agencies, 2,429 images, OfferGeo fully backfilled.

**Consequence to design around:** the two datasets drift apart from now on. A
crawl under v3 does not appear on `varna.avaflow.xyz`, and vice versa. That is
the intended trade for being able to migrate and experiment freely.

**Before ever repointing `DB_NAME` at `varna_market`:** take a fresh verified
`pg_dump -Fc` per `docs/OPERATIONS.md`, and understand that the live app will
then be running old code against a newer schema. The project's own position is
that the new tables are additive and old code ignores them — that is probably
true, but it has not been tested with both apps live at once.

## Configuration

`.env` is a **symlink** to `/home/mvp/secrets/pocket-broker-v3.env` (mode 600,
outside the repo, never in Git). It is the same pattern every project on this
box uses. What differs from `.env.example`:

    DJANGO_DEBUG=False
    DJANGO_ALLOWED_HOSTS=pb3.avaflow.xyz,127.0.0.1,localhost
    DJANGO_CSRF_ORIGINS=https://pb3.avaflow.xyz
    DJANGO_BEHIND_PROXY=True          # nginx terminates TLS; without this
                                      # Django marks session/CSRF cookies insecure
    DB_NAME=pocket_broker_v3_phase1   # NOT varna_market — see above
    DB_USER=varna_market

`DEBUG=False` matters for more than error pages: `config/urls.py` only serves
`MEDIA_URL` through Django when `DEBUG` is on, so in production **nginx is the
only thing serving photos**. If images vanish, check nginx, not Django.

## Static files and photos

`/home/mvp` is `drwxr-x---`, so `www-data` cannot traverse into the project at
all. Nothing under the repo is web-reachable; two trees are published out:

- **`/var/www/pb3/static/`** — `rsync -a --delete` of `staticfiles/` on every
  deploy. Holds Django admin CSS plus the built Vue bundle, which
  `vite.config.js` pins to `base:'/static/'`.
- **`/var/www/pb3/media/images/`** — the repo's `data/images` is a **symlink**
  here, so a photo a crawl writes tonight is served immediately, with no deploy
  and no copy.

Photos resolve through **two** trees, in this order:

1. `/var/www/pb3/media/images/` — v3's own downloads.
2. `/var/www/varna/media/images/` — the inherited 762MB corpus (nginx named
   location `@inherited_images`).

The fallback exists because v3's database is a *copy* of varna's: every
`OfferImage` row it inherited names a file that only exists under
`/var/www/varna`. Serving v3's tree first means a v3 crawl can never overwrite
a live photo, while the inherited corpus still displays. `data/raw`,
`data/runs` and `data/recon` stay inside the home dir and are additionally
blocked by `location /media/ { return 404; }`.

## nginx

The block lives in the shared config `/etc/nginx/sites-available/mvp`, which
holds every vhost on the box. **Edit the source copy `/home/mvp/nginx-mvp.conf`,
never the live file**, then:

```bash
sudo cp /home/mvp/nginx-mvp.conf /etc/nginx/sites-available/mvp && \
  sudo nginx -t && sudo systemctl reload nginx
```

A copy of just v3's block is kept at `deploy/nginx-pb3.conf` for reference; the
authoritative version is the one in `nginx-mvp.conf`.

Two traps in that shared file:

- **Never put `default_server` on a project block.** Ports 80 and 443 already
  have dedicated catch-alls at the bottom of the file (an empty-body 404 and
  `ssl_reject_handshake`). A second default makes nginx refuse to start.
- **`certbot --nginx` edits the LIVE file in place.** After any certbot run,
  re-sync the source copy or the next `sudo cp` silently reverts HTTPS:
  `cp /etc/nginx/sites-available/mvp /home/mvp/nginx-mvp.conf`

DNS needs no change ever: `avaflow.xyz` has wildcard `A` records (`@` and `*`)
pointing at this host, so any new subdomain resolves and nginx decides what it
serves.

## Process supervision

PM2, as user `mvp`, persisted with `pm2 save`:

```bash
pm2 start .venv/bin/gunicorn --name pb3 --cwd <project> \
  --interpreter .venv/bin/python -- \
  config.wsgi:application --bind 127.0.0.1:8501 --workers 3 --timeout 120 \
  --access-logfile - --error-logfile -
```

⚠️ **`--interpreter` is load-bearing.** `.venv/bin/gunicorn` has no file
extension, so PM2 assumes Node and crash-loops with `SyntaxError: Unexpected
identifier 'gunicorn'` — while briefly reporting `online`. PM2 is not Node-only
on this box; `seaside` runs Python the same way.

Day to day: `pm2 logs pb3`, `pm2 restart pb3`, `pm2 describe pb3`.

## Deploying a change

```bash
bash /home/mvp/projects/pocket-broker-v3/deploy.sh
```

git pull → pip install → `npm ci && npm run build` → `vendor_check` → `migrate`
→ `collectstatic` → rsync to `/var/www/pb3/static/` → `pm2 restart pb3`.
It never touches the database beyond `migrate`, and never touches nginx.

Python is **3.12.3** on this box, not the 3.14 the README's development notes
mention. The venv at `.venv` is real (created 2026-09-25) and gitignored;
`requirements-server.txt` adds only `gunicorn==23.0.0` on top of
`requirements.txt`, which stays pinned line-for-line to `~/Dev/broker-crm`.

## Verifying it is actually up

```bash
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: pb3.avaflow.xyz' http://127.0.0.1:8501/
curl -s -H 'Host: pb3.avaflow.xyz' http://127.0.0.1:8501/api/stats/
curl -sI https://pb3.avaflow.xyz | head -1
```

Bypassing nginx with the `Host:` header is the useful half: it separates "the
app is broken" from "the vhost is broken". `ALLOWED_HOSTS` rejects a request
without that header once `DEBUG=False`.

## Open items

- **No crawl is scheduled for v3.** Manual Sofia imports began on 2026-09-26
  using five verified adapters; see `docs/sofia-crawl-map.md` for measured counts.
  The live app has no schedule either (`server.md`, Varna Market section).
- **`pb3.avaflow.xyz` is unauthenticated**, like `varna.avaflow.xyz`. Fine while
  it is a read-only public catalogue; revisit before the admin or any write path
  is exposed.
- The v3 repo does not contain the live app's deployment commits `2b01174` and
  `f1780a8`, which are local-only and unpushed in `projects/varna-market`.
