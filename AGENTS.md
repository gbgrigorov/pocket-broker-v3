# Notes for coding agents working in this checkout

**This checkout is deployed and live.** It serves https://pb3.avaflow.xyz from
this directory — there is no separate release copy. A broken commit here is a
broken website as soon as `deploy.sh` runs, and an edit to `data/` or the
database is visible immediately, with no deploy at all.

Read **`deploy/SERVER.md`** before changing anything about configuration,
process supervision, static files, media paths or the database. The five facts
that catch people out:

1. **This app is not the only one using its code.** `/home/mvp/projects/varna-market`
   is the *older live deployment* of the same project, serving
   `varna.avaflow.xyz` on port 8500 from database `varna_market`. v3 runs
   alongside it on port **8501** from database **`pocket_broker_v3_phase1`**.
   Do not "consolidate" them without reading `deploy/SERVER.md` — the split is
   what keeps v3's migrations 0005–0007 off live user-facing data.

2. **`.env` is a symlink** to `/home/mvp/secrets/pocket-broker-v3.env`. Never
   commit it, never `cat` it into output, never replace the symlink with a file.
   Add a new setting by editing the secrets file *and* `.env.example`.

3. **`data/images` is a symlink** to `/var/www/pb3/media/images`, because
   `/home/mvp` is `drwxr-x---` and nginx cannot read into this directory.
   Photos are served by nginx, never by Django — `config/urls.py` only routes
   `MEDIA_URL` when `DEBUG=True`, and production runs `DEBUG=False`.

4. **Migrations run against real inherited data**, not a fresh database. 2,572
   offers, 139 agencies and a checksum-verified restore lineage
   (`docs/CURRENT-STATE.md`). Take a `pg_dump -Fc` first — `docs/OPERATIONS.md`
   has the backup-and-verify sequence — and never reverse a schema migration on
   this database without arranging to preserve curator geography edits.

5. **The frontend must be built for a change to be visible.** Django serves
   `frontend/dist` through `collectstatic`, and `vite.config.js` pins
   `base:'/static/'`. `npm run build` alone is not enough on the server;
   `deploy.sh` also runs `collectstatic` and rsyncs to `/var/www/pb3/static/`.

## Before you hand work back

```bash
./.venv/bin/python manage.py check
./.venv/bin/python manage.py makemigrations --check --dry-run
./.venv/bin/python manage.py test
./.venv/bin/python manage.py vendor_check
( cd frontend && npm run build )
```

`manage.py test` needs `CREATEDB` on the `varna_market` role; it has it. The
suite is 231 tests with three expected skips (absent sheet snapshots in
`data/raw`).

## Deploying

`bash deploy.sh` — pull, deps, frontend build, vendor check, migrate,
collectstatic, rsync, `pm2 restart pb3`. It never touches nginx.

nginx and certbot need the user's `sudo` password, so an agent cannot apply
them: hand the command over instead. The block source of truth is
`/home/mvp/nginx-mvp.conf` (copy in `deploy/nginx-pb3.conf`), applied with
`sudo cp … /etc/nginx/sites-available/mvp && sudo nginx -t && sudo systemctl reload nginx`.

## Things the vendored half will punish you for

`sourcing/` is a vendored copy of `~/Dev/broker-crm`. A silent local edit there
is what makes a fix stop moving between the two projects — `manage.py
vendor_check` exists to catch exactly that, and `docs/VENDORING.md` describes
how divergence is meant to be recorded. `requirements.txt` is pinned
line-for-line to that project for the same reason; server-only additions go in
`requirements-server.txt`.

Crawler behaviour is a **documented decision, not an oversight**:
`CRAWL_RESPECT_ROBOTS=False`, with hard limits (no logins, no paywalls, no
CAPTCHA solving, no credential reuse, blocked hosts recorded and skipped).
Read `docs/CRAWL-POLICY.md` before touching anything under `sourcing/` or
`market/management/commands/crawl_*`.
