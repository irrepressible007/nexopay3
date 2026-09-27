# Deploying Nexopay on cPanel (nexopay.com.bd)

Target: the existing cPanel account (`/home/nexopayc`, CloudLinux, Setup Python App, MySQL, SSH).
Do **staging first** (`staging.nexopay.com.bd`), then production with the same steps.

## 0. One-time accounts (outside cPanel)

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
EMAIL_HOST=mail.nexopay.com.bd  EMAIL_HOST_USER=tickets@nexopay.com.bd  EMAIL_HOST_PASSWORD=…
CACHE_DIR=/home/nexopayc/nexopay/.cache
```

The `.env` file is read by the web app *and* by cron, so keep secrets there (not only in the cPanel UI).
On **staging only**, add `ALLOW_MOCK_PAYMENTS=True` if you want the test gateway.

## 3. Cron (cPanel › Cron Jobs)

Paste the lines from `deploy/crontab.txt` (adjust `3.12`). The every-minute job releases expired ticket
holds, opens/closes event sales, reconciles payments and sends ticket emails. Check `logs/cron.log`.

## 4. Admin configuration (https://nexopay.com.bd/<ADMIN_URL>)

1. **Site settings**: upload the logo (+ a light version for emails/PDFs), favicon, brand colours, contact info,
   social links, default fees (commission % / buyer fee).
2. **Payment methods**: for each provider with credentials in `.env`, tick *Enabled*; keep *Sandbox* ticked until
   live credentials are in place. Never enable "Test payment" in production.
3. **Homepage sections / Hero slides / Pages / FAQ**: arrange the homepage and edit About, Terms, Privacy, Refund policy
   (English + Bangla fields).
4. **Support routes**: confirm which inbox receives each contact-form reason.

## 5. Cloudflare caching (after the site works)

Rules › Cache Rules → *Eligible for cache*, respect origin `Cache-Control`, for requests where
URI path does **not** start with `/control-room`, `/account`, `/checkout`, `/orders`, `/payments`, `/scan`,
`/organizers`, `/accounts`, `/t/`, `/_/`. Public pages send `s-maxage=60`, so Cloudflare absorbs traffic spikes
when a big event goes on sale — that is what keeps us inside the 20-entry-process limit.
Also: Speed › Optimization → enable Brotli; Caching › Configuration → Browser cache TTL "Respect existing headers".

## 6. Updating

```bash
bash ~/nexopay/deploy/deploy.sh      # pull, install, migrate, collectstatic, check, restart
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
