# CLAUDE.md

Project instructions for Claude Code. Read this before writing any code.

## Project Overview

An event ticketing marketplace (Tickify-model): organizers list events with
flexible ticket tiers, buyers browse/filter and purchase via local payment
methods, and tickets are delivered as e-mail/PDF plus an in-app QR pass
scanned at the door. This is a two-sided marketplace with checkout and
ticket-validation — not a landing-page builder.

Build in the phase order below. Do not start Phase 2 UI work before the
Phase 1 data model is in place and migrated. Do not build payment
integrations before Order/Ticket entities exist to attach them to.

## Suggested Stack (adjust to your own preference, but keep these properties)

- Backend: server-rendered web framework with a mature batteries-included
  auth package (e.g. Django + django-allauth, or Rails + Devise). Avoid
  hand-rolling auth.
- Database: Postgres.
- Object storage: S3-compatible bucket (S3, Cloudflare R2, Tigris, etc.)
  for all uploaded media — banners, logos, QR images. Never write uploads
  to local app-server disk.
- Background jobs: a queue (Celery/Sidekiq/etc.) for ticket-PDF
  generation, email/WhatsApp delivery, and payment webhook processing —
  these should never block the request/response cycle.
- Frontend: server-rendered templates for v1. Do not reach for a full SPA
  framework until the core catalog/checkout loop is validated.

## Phase 1 — Core Data Model

Build these entities first, migrate them, and write model-level tests
before any UI exists.

**User**
- Roles: `buyer`, `organizer` (a user can hold both).
- Organizer accounts carry `status`: `pending_review` / `approved` / `rejected`.
- Standard email/password auth to start; social login is optional/later.

**Event**
- Belongs to an `Organizer` (User with organizer role).
- `status`: `draft` / `on_sale` / `coming_soon` / `sold_out` / `ended`.
- Many-to-many with `Category` — **do not** model this as a single
  category foreign key; events can and should carry multiple tags.
- Own rich-text `terms_and_conditions` field, separate from the
  platform-wide Terms of Service.
- `featured: boolean` — independent of `status`, used for editorial
  promotion (e.g. a homepage carousel), not tied to live/ended state.

**Category**
- Fixed, admin-managed list (not freeform organizer-created tags).
- Display live counts per category on the catalog/filter UI, including
  categories that currently have zero events.

**TicketType** (belongs to `Event`, one-to-many)
- `name`, `price`, `description`, `stock` / `is_available`.
- Availability is tracked **per TicketType**, not per Event — one segment
  can sell out while others on the same event stay open.
- Must support two shapes on the same schema:
  - flat: a single TicketType per event (concerts, screenings, etc.)
  - multi-segment: several TicketTypes per event — e.g. a base "Entry"
    tier, multiple "Entry + [specific activity]" combo tiers, and one
    all-inclusive bundle tier (competitions, festivals with activities).

**Order**
- Belongs to a `User`. **Do not build guest checkout** — require an
  account before or at the point of payment.
- One Order can contain multiple `TicketType` line items (a buyer may
  purchase more than one ticket type for the same event in one checkout).
- Uniqueness constraint: one identity (email/phone) cannot purchase the
  same `TicketType` more than once for a given event, **unless** that
  TicketType has an explicit `allow_quantity: boolean` override enabled
  by the organizer.

**Ticket** (generated per purchased unit, on successful payment)
- Unique, hard-to-forge scannable token (signed, not a sequential ID).
- `status`: `valid` / `redeemed` / `refunded`.
- Generate once; render on demand into three delivery forms: emailed
  PDF, WhatsApp-shareable link/image, in-app QR view. Do not regenerate
  per channel — one canonical record, multiple renderers.

## Phase 2 — Buyer-Side Functionality

- **Catalog page**: filter by category (multi-select) AND status
  (All / Live / Upcoming) simultaneously; paginate results. Both filters
  must be combinable in a single query — don't pre-bake per-category pages.
- **Event detail page**: description, event-specific T&Cs, every
  TicketType with price + availability + its own independent purchase
  action, an organizer contact block, social share buttons, "Add to
  Calendar" link.
- **Checkout**: account required; support multiple TicketTypes in one
  order. Cart vs. direct-buy UX is your call (not resolved by the
  reference research — decide based on your own UX testing).
- **Post-purchase**: the confirmation screen determines which email
  address tickets are sent to; tickets must always be re-downloadable
  from the buyer's profile even if that inbox becomes inaccessible later.
- **Buyer profile / wallet**: list of owned tickets, each openable as a
  QR view for gate entry.

## Phase 3 — Payments

Build a payment **abstraction layer** behind a single internal interface
(e.g. `PaymentProvider.charge(order)` / a shared webhook handler) — do not
hard-wire UI or Order-creation logic to any one provider's SDK.

- Integrate each major local mobile wallet directly (separate merchant
  API per wallet — budget for 3-4 independent integrations, each with
  its own auth, callback format, and reconciliation quirks).
- Route card payments (Visa/Mastercard) through one payment aggregator
  rather than integrating card acquiring directly — this offloads
  PCI-DSS compliance to the aggregator.
- All providers must funnel into the same "payment succeeded" webhook
  contract, which triggers Order confirmation + Ticket generation
  identically regardless of which method was used.

## Phase 4 — Organizer-Side Functionality

- Organizer signup lands in `pending_review`. Build an admin review
  queue for approving/rejecting new organizers — **do not** make listing
  self-serve/instant in v1.
- Organizer dashboard: sales report by event, attendance/check-in log
  (fed by Phase 5's scanning tool).
- Event creation form: name, description, category tags, banner image
  upload (to object storage), one or more TicketTypes, custom
  event-level T&Cs text.
- Refund tooling: build refund issuance as a **platform-level**
  capability (admin or organizer-with-permission triggers it through the
  system), not an off-platform negotiation between buyer and organizer.

## Phase 5 — Entry / Scanning

- A scanning tool (a mobile-optimized web view is sufficient for v1;
  no native app required) that reads a Ticket's QR token and calls a
  `redeem_ticket` endpoint.
- `redeem_ticket` must be **idempotent and reject already-redeemed
  tickets** — this is the control that prevents a screenshotted/forwarded
  QR code from being used twice. Write a test specifically for the
  double-redemption case.

## Phase 6 — Support & Ops (cheap — do this early, not last)

- Contact form with a categorized reason dropdown (Payment Issue,
  Ticket Issue, Account Management, List an Event / Event Promotion,
  Technical Assistance, Feedback) that routes to separate queues/inboxes
  from day one.

## Deferred / Not Needed for MVP

- White-label subdomains for flagship/premium organizers
  (`artistname.yourdomain.com`). Valuable once you're landing large
  accounts; do not build this before the core catalog → checkout →
  ticket → scan loop is proven end-to-end.
- Native mobile apps — a responsive web app covers both buyer and
  scanning use cases for v1.

## Engineering Conventions

- Every new entity above needs a migration + a factory/fixture for tests
  before any view/controller is written against it.
- Payment webhook handlers must be idempotent (a provider may retry
  delivery) — dedupe on the provider's transaction ID before creating an
  Order.
- Ticket tokens must never be sequential or guessable — use a signed
  token or UUID plus a server-side signature, not an incrementing ID.
- Treat "available" as a derived/locked value at checkout time
  (re-check stock inside the same DB transaction that creates the
  Order) to avoid overselling a limited TicketType under concurrent
  purchases.
- Object storage keys for uploads should be namespaced by
  organizer/event ID, not by original filename, to avoid collisions.

## Open Decisions (flag to the user, don't silently assume)

- Cart-based vs. direct-buy checkout flow.
- Exact refund automation level and timeframe.
- Whether white-label subdomains (when eventually built) are a paid tier
  or unlocked by event size/organizer tier.

## Decisions Made (2026-09-27, by the project owner)

- **Brand**: Nexopay, nexopay.com.bd. Dark & vibrant look; colours/logo are
  admin-editable (SiteSettings) — final logo still to be supplied.
- **Hosting**: everything on the existing cPanel shared account for now
  (Passenger + MySQL/MariaDB — no Postgres, no Redis, no long-running
  workers). Background jobs therefore run via `manage.py nexopay_cron`
  from a single cron line. Keep code portable to a VPS (settings via env).
- **Media**: Cloudflare R2 + Cloudflare CDN (satisfies "never local disk").
- **Checkout**: per-event selection (several ticket types of one event in one
  order); no cross-event cart. (Resolves the cart vs direct-buy question.)
- **Payments**: direct bKash, Nagad, Upay, Pathao Pay + SSLCommerz for cards.
  Upay/Pathao Pay implementations must be verified against the merchant docs
  received at onboarding (Pathao Pay is a stub until then).
- **Fees**: per-organizer commission % and buyer service fee, platform default
  in SiteSettings; snapshotted on each Order.
- **Refunds (default until the owner decides otherwise)**: admin-approved,
  sent through the provider API when available, otherwise recorded manually;
  organizers may request, or issue directly when `can_issue_refunds` is set.
- **Languages**: English + Bangla toggle (`/bn/` prefix); content fields are
  translated per field (`*_en`/`*_bn`).
- **Email**: cPanel SMTP now, switchable to a transactional provider via env.
