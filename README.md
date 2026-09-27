# Nexopay

Event-ticketing marketplace for Bangladesh. Organizers are vetted, then list events with flat or
multi-segment ticket tiers. Buyers pay with bKash, Nagad, Upay, Pathao Pay or card (via SSLCommerz)
and get a PDF by email, a WhatsApp-shareable link and an in-app QR pass. Gate staff scan passes from
any phone. English + Bangla throughout.

Product rules live in `claude.md`; the market research is in `Tickify_Event_Category_Report.docx`.
Deployment to cPanel is in [`DEPLOY.md`](DEPLOY.md).

## Stack

| Layer | Choice | Why |
|---|---|---|
| Web | Django 5.2 LTS behind Passenger (cPanel "Setup Python App") | Batteries-included auth/admin/i18n; runs on shared hosting |
| DB | MySQL / MariaDB (utf8mb4, READ COMMITTED) | What cPanel provides; row locks prevent overselling |
| Background jobs | `django-tasks` DB backend, run by one cron line | No long-running workers allowed on shared hosting |
| Media | Cloudflare R2 (S3 API) + Cloudflare CDN | Uploads never touch the app server |
| Frontend | Server-rendered templates + HTMX + Alpine.js + Tailwind v4 | ~30 KB JS, fast on 4G, edge-cacheable HTML |
| Admin | django-unfold | Modern admin: homepage builder, branding, refunds, vetting |
| PDFs | fpdf2 + HarfBuzz shaping + Hind Siliguri | Correct Bangla conjuncts without system libraries |

## Project layout

```
apps/
  accounts/     users (email login, BD phone), My tickets / orders / profile
  organizers/   application + vetting, dashboard, event builder, reports, scanner staff, refunds
  events/       Category (18 seeded), Event (M2M categories, status machine), TicketType (per-type stock)
  orders/       Order, OrderItem, PurchaseClaim; checkout service with stock holds
  tickets/      Ticket (signed QR token), PDF/QR renderers, redeem service, gate scanner
  payments/     provider abstraction: sslcommerz, bkash, nagad, upay, pathaopay, mock; refunds; reconciliation
  cms/          SiteSettings (branding/colours/fees), homepage sections, hero slides, pages, FAQ
  support/      contact form routed to per-reason inboxes
  core/         cache/HTTP helpers, template tags, cron + backup + demo-data commands
templates/  static/src/app.css (Tailwind source)  locale/ (Bangla)  deploy/  tests/
```

## Local development (Windows / macOS / Linux)

```bash
python -m venv .venv && .venv/Scripts/activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
docker run -d --name nexopay-mysql -e MYSQL_ROOT_PASSWORD=nexopay -e MYSQL_DATABASE=nexopay \
  -e MYSQL_USER=nexopay -e MYSQL_PASSWORD=nexopay -p 3307:3306 mariadb:10.6 \
  --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
```

`.env` for local work:

```
DEBUG=True
DATABASE_URL=mysql://nexopay:nexopay@127.0.0.1:3307/nexopay
TEST_DATABASE_URL=mysql://root:nexopay@127.0.0.1:3307/nexopay
ACCOUNT_EMAIL_VERIFICATION=optional
```

```bash
python manage.py migrate
python manage.py seed_demo            # demo organizer + 11 events (incl. multi-segment Kpop Fiesta), enables test payments
python manage.py createsuperuser
python manage.py runserver            # admin at /control-room/
python manage.py nexopay_cron         # run periodic jobs once (sends queued ticket emails → logs/emails/)
```

**CSS** — after editing templates, rebuild with the Tailwind standalone CLI (no Node needed):

```bash
bin/tailwindcss.exe -i static/src/app.css -o static/css/app.css --minify     # add --watch while developing
```

Download the CLI for your OS from https://github.com/tailwindlabs/tailwindcss/releases (v4) into `bin/`.
The built `static/css/app.css` is committed, so the server never needs to build CSS.

**Translations** — UI strings are extracted to `locale/bn/LC_MESSAGES/django.po`; Bangla text lives in
`locale/bn_translations.py`. After adding strings: run `makemessages -l bn` (needs GNU gettext — use the
Docker one-liner in DEPLOY.md on Windows), add the Bangla to `bn_translations.py`, then
`python manage.py fill_translations` (compiles `django.mo`, no gettext needed). Event/category/page content
is translated per-field in the admin (`*_en` / `*_bn`).

## Tests

```bash
pytest                  # 89 tests; uses MariaDB from TEST_DATABASE_URL (SQLite otherwise, skipping lock tests)
```

Covers the claude.md guarantees: no overselling under concurrent checkout (threads racing on real row
locks), double-redemption rejected (including concurrent gate scans), webhook/IPN replay idempotency,
one-identity-per-ticket-type rule, hold expiry, fee maths, provider flows with server-side verification
(SSLCommerz validation, bKash execute/query, Nagad RSA), refunds + stock release, event cancellation.

## Everything is editable in the admin (no code)

| What | Where in the admin |
|---|---|
| Every interface text (buttons, labels, messages, emails, PDF, login pages), English + Bangla | **Website content › Site texts**: filter by page, edit inline, "Reset to default" action |
| Logo, favicon, colours, tagline, announcement bar, contact & social, SEO, reservation time, default fees | **Website content › Site settings** |
| Outgoing email (SMTP mailbox + sender) | **Site settings › Outgoing email** |
| Header menu, footer columns and links | **Website content › Header menu / Footer columns** |
| Homepage sections (order, on/off, schedule), hero headline (`*word*` = gradient), hero slides | **Homepage sections / Hero slides** |
| About / Terms / Privacy / Refund pages, FAQ | **Pages / FAQ** (pages start empty and show "being updated" until written) |
| Categories (names, icon picker or uploaded icon, colour, hero quick links) | **Events › Categories** |
| Payment methods: on/off, sandbox/live, name, badge colour/logo, **merchant credentials** | **Payments › Payment methods** (credentials are encrypted and never shown back) |

Interface texts are mirrored from the code on every `migrate`. Placeholders such as `%(name)s` are
validated, so an admin can reword but not break a sentence. Secrets in the database are encrypted with a
key derived from `SECRET_KEY` (or `FIELD_ENCRYPTION_KEY` if set): changing it means re-entering secrets.

## Layout safety (any screen, any admin content)

```bash
python manage.py seed_stress        # DEV ONLY: worst-case content (huge titles, long Bangla words, 15 tiers…)
python tools/layout_audit.py --ids '{"tt": <ticket-type id>, "code": "<ticket code>", "order": "<order ref>"}'
python manage.py seed_stress --undo
```

The audit loads ~27 pages at 14 screen sizes (320px phones → 2560px monitors, incl. landscape) and fails on
anything that goes off-screen, spills out of its box, or squeezes a short label onto several lines.
Global CSS rules make this hold for new content automatically: text wraps instead of widening its
container, grid cells may shrink, prices/badges/buttons never split mid-word.

## How the key flows work

- **Checkout** (`apps/orders/services.py`): locks ticket-type rows in PK order, re-checks stock, writes
  `PurchaseClaim`s (unique per ticket type + email/phone), creates an Order holding stock for 15 min.
- **Payment** (`apps/payments/`): every provider implements `initiate / handle_return / handle_ipn / verify /
  refund`; all success paths call `services.mark_succeeded()`, which is idempotent and issues tickets.
  Cron reconciles stuck attempts by asking the provider.
- **Tickets**: one record per unit; QR = `uuid:HMAC`; PDF/share page/in-app QR are renderings of it.
- **Scanning**: `redeem_ticket` is a single conditional `UPDATE … WHERE status='valid'`.
- **Edge caching**: home/catalog/event HTML is identical for everyone (`public, s-maxage=60`); the account
  menu, flash messages and live ticket panel load as small uncached HTMX fragments.
