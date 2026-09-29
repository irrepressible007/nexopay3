# Deploying Nexopay on cPanel (nexopay.com.bd)

Target: the existing cPanel account (`/home/nexopayc`, CloudLinux, Setup Python App, MySQL, SSH).
Do **staging first** (`staging.nexopay.com.bd`), then production with the same steps.

**Minimum to go live on cPanel alone:** sections 1–4. Cloudflare (DNS/CDN) and R2 (media storage) are
optional upgrades (sections 0 and 5): without R2, uploads are stored in `public_html/media` and served by
Apache directly, and CSS/JS are served from `public_html/static` — neither uses a Python process.

## 0. Accounts outside cPanel (can come later)

1. **Cloudflare** (free): add `nexopay.com.bd`, then at your registrar point the nameservers to Cloudflare.
   Copy over *every* existing DNS record first — especially **MX, SPF (TXT), DKIM (TXT)** so cPanel email keeps working.
   - `A  @` and `A www` → `103.174.50.7` (proxied / orange cloud)
   - SSL/TLS mode: **Full (strict)** (cPanel already has a valid certificate)
2. **Cloudflare R2**: create buckets `nexopay-media` (public) and `nexopay-private` (private).
   Connect a custom domain `media.nexopay.com.bd` to `nexopay-media`. Create an R2 API token (Object Read & Write)
   → gives `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and the endpoint `https://<account-id>.r2.cloudflarestorage.com`.
3. **Payment merchants** — apply now (trade license needed, approval takes weeks):
   SSLCommerz, bKash (Tokenized Checkout), Nagad, Upay, Pathao Pay. Ask each for **sandbox** credentials first.
   Some providers whitelist server IPs — give them `103.174.50.7` (shared IP; ask your host about a dedicated IP if a provider refuses shared IPs).

## 1. cPanel setup

1. **MySQL® Databases**: create database `nexopayc_main`, user `nexopayc_app` with a strong password, add the user
   to the database with **ALL PRIVILEGES**. (Staging: `nexopayc_staging` / `nexopayc_stg`.)
2. **Email Accounts**: create `tickets@nexopay.com.bd` (sender) plus inboxes or **Forwarders** for
   `support@`, `payments@`, `organizers@`, `hello@`. Then **Email Deliverability** → make sure SPF and DKIM are valid
   (copy the suggested records into Cloudflare DNS if DNS moved there).
3. **Setup Python App** → Create application:
   - Python version: newest offered (3.12 ideal; ≥ 3.10 required)
   - Application root: `nexopay`  ·  Application URL: `nexopay.com.bd`
   - Application startup file: `passenger_wsgi.py`  ·  Entry point: `application`
   - Create. Note the "Enter to the virtual environment" command shown at the top.

## 2. Code & configuration (cPanel › Terminal)

```bash
cd ~
git clone <your-repo-url> nexopay          # or upload via cPanel Git Version Control
cd nexopay
cp .env.example .env && chmod 600 .env
nano .env                                  # fill in every value (see below)
mkdir -p ~/public_html/static ~/public_html/media   # Apache serves these directly
source ~/virtualenv/nexopay/3.12/bin/activate
pip install -r requirements.txt            # if mysqlclient fails: pip install PyMySQL (auto-detected)
python manage.py migrate
python manage.py createsuperuser
python manage.py collectstatic --noinput
mkdir -p tmp logs && touch tmp/restart.txt
```

Key `.env` values (full list in `.env.example`):

```
DJANGO_SETTINGS_MODULE=nexopay.settings.production
SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(50))">
ALLOWED_HOSTS=nexopay.com.bd,www.nexopay.com.bd
CSRF_TRUSTED_ORIGINS=https://nexopay.com.bd,https://www.nexopay.com.bd
SITE_URL=https://nexopay.com.bd
ADMIN_URL=<something-unguessable>/
DATABASE_URL=mysql://nexopayc_app:<password>@localhost:3306/nexopayc_main
R2_… / MEDIA_URL=https://media.nexopay.com.bd/
# Email + payment credentials are entered in the admin (encrypted). EMAIL_* / <PROVIDER>_* env vars are optional fallbacks.
CACHE_DIR=/home/nexopayc/nexopay/.cache
```

The `.env` file is read by the web app *and* by cron, so keep secrets there (not only in the cPanel UI).
On **staging only**, add `ALLOW_MOCK_PAYMENTS=True` if you want the test gateway.

### If the app can't start: `lswsgi: No such file or directory` in `stderr.log`

Some hosts' LiteSpeed lacks its Python connector, so *Setup Python App* can't run any app. Serve the site
through `deploy/cgi_bridge.sh` instead (it only edits the block it adds to the domain's `.htaccess`):

1. cPanel › Setup Python App › the app › **Stop app** (never *Destroy*, never *Save* — Save rewrites
   `passenger_wsgi.py`). Keep the app: its virtualenv is what the bridge runs.
2. `bash ~/nexopay3/deploy/cgi_bridge.sh fast` — a tiny CGI forwarder relays each request to an always-on
   app server (gunicorn, `deploy/appserver.sh`) on a private socket: pages in tens of milliseconds. It also adds
   one keep-alive line to your crontab (only its own line, tagged `# nexopay-appserver`) that restarts the app
   server within a minute if it ever stops; until then pages are served the slow way, never an error.
   `deploy.sh` reloads the app server without dropping requests. Log: `logs/appserver.log`.
3. Or `bash ~/nexopay3/deploy/cgi_bridge.sh on` — plain CGI, nothing running in the background, ~1 s per page.

`cgi_bridge.sh status` shows the mode; `cgi_bridge.sh off` removes the bridge (then *Start app* again).
`bash ~/nexopay3/deploy/speedtest.sh` times each layer (Cloudflare, web server, PHP, CGI, app server) to show
where page time goes.

## 3. Cron (cPanel › Cron Jobs)

Paste the lines from `deploy/crontab.txt` (adjust `3.12`). The every-minute job releases expired ticket
holds, opens/closes event sales, reconciles payments and sends ticket emails. Check `logs/cron.log`.

## 4. Admin configuration (https://nexopay.com.bd/<ADMIN_URL>)

1. **Site settings**: logo (the bundled Nexopay logo is used until you upload one), favicon, brand colours,
   contact info, social links, reservation time, default fees, and **Outgoing email** (the cPanel mailbox
   `tickets@…`, host `mail.nexopay.com.bd`, port 465 + SSL, its password).
2. **Payment methods**: open each provider, paste the merchant credentials from its merchant panel (stored
   encrypted), tick *Enabled*; keep *Sandbox* ticked until live credentials are in. The list shows
   "Complete ✓" or which credentials are missing. Never enable "Test payment" in production.
3. **Site texts**: reword any button/label/message in English or Bangla; filter by page.
4. **Homepage sections / Hero slides / Header menu / Footer columns / Pages / FAQ**: arrange the homepage and
   menus; write About, Terms, Privacy and Refund policy (they start empty).
5. **Support routes**: confirm which inbox receives each contact-form reason.

## 5. Cloudflare caching (after the site works)

Rules › Cache Rules → *Eligible for cache*, respect origin `Cache-Control`, for requests where
URI path does **not** start with `/control-room`, `/account`, `/checkout`, `/orders`, `/payments`, `/scan`,
`/organizers`, `/accounts`, `/t/`, `/_/`. Public pages send `s-maxage=60`, so Cloudflare absorbs traffic spikes
when a big event goes on sale — that is what keeps us inside the 20-entry-process limit.
Also: Speed › Optimization → enable Brotli; Caching › Configuration → Browser cache TTL "Respect existing headers".

## 6. Updating

```bash
bash ~/nexopay3/deploy/deploy.sh     # pull, install, migrate, collectstatic, check, restart
```

## 7. Going live checklist

- [ ] `python manage.py check --deploy` clean; `DEBUG=False`; admin URL changed; strong superuser password
- [ ] Sandbox purchase with every enabled provider on staging → email + PDF arrive, QR shows in My tickets,
      scan green, re-scan red, refund works
- [ ] Live credentials in `.env`, *Sandbox* unticked, a real ৳10 test purchase + refund per provider
- [ ] Cron running (`logs/cron.log`), nightly backup appearing in R2 `private/backups/db/`
- [ ] SPF/DKIM pass (send a ticket email to Gmail, "Show original")
- [ ] If cPanel's hourly email limit is hit: switch `EMAIL_BACKEND` to an anymail provider (Brevo/SES) in `.env`

## Regenerating translations on Windows (no gettext)

```bash
docker run --rm -v "%cd%:/app" -w /app python:3.12-slim sh -c \
 "apt-get update -qq && apt-get install -y -qq gettext && pip install -q -r requirements.txt PyMySQL && \
  DATABASE_URL=sqlite:////tmp/x.db python manage.py makemessages -l bn --ignore=.venv --ignore=bin --ignore=static --no-obsolete"
python manage.py fill_translations
```
