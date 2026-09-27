"""
Checkout: turns a buyer's ticket selection into a pending Order that *holds*
stock for a few minutes while they pay.

Concurrency rules (see claude.md "Engineering Conventions"):
- Availability is re-checked inside the same transaction that creates the
  Order, with the TicketType rows locked (SELECT … FOR UPDATE), always in
  primary-key order so two checkouts can never deadlock each other.
- The one-per-identity rule is backed by a unique constraint (PurchaseClaim).
"""
import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.utils import normalize_phone
from apps.events.models import Event, TicketType

from .models import Order, OrderItem, PurchaseClaim

logger = logging.getLogger(__name__)
CENT = Decimal("0.01")


class CheckoutError(Exception):
    """A user-facing reason the checkout could not start."""


@dataclass(frozen=True)
class FeeBreakdown:
    subtotal: Decimal
    buyer_fee: Decimal
    total: Decimal
    commission_amount: Decimal
    organizer_net: Decimal
    commission_pct: Decimal
    buyer_fee_pct: Decimal
    buyer_fee_flat: Decimal


def fee_rates(organizer) -> tuple[Decimal, Decimal, Decimal]:
    """(commission %, buyer fee %, buyer flat fee) — organizer override or platform default."""
    from apps.cms.models import SiteSettings

    site = SiteSettings.load()

    def pick(override, default):
        return override if override is not None else default

    return (
        pick(organizer.commission_pct, site.default_commission_pct),
        pick(organizer.buyer_fee_pct, site.default_buyer_fee_pct),
        pick(organizer.buyer_fee_flat, site.default_buyer_fee_flat),
    )


def calculate_fees(subtotal: Decimal, organizer) -> FeeBreakdown:
    commission_pct, buyer_fee_pct, buyer_fee_flat = fee_rates(organizer)
    if subtotal <= 0:  # free tickets never carry fees
        zero = Decimal("0.00")
        return FeeBreakdown(zero, zero, zero, zero, zero, commission_pct, buyer_fee_pct, buyer_fee_flat)
    buyer_fee = (subtotal * buyer_fee_pct / 100 + buyer_fee_flat).quantize(CENT, ROUND_HALF_UP)
    commission = (subtotal * commission_pct / 100).quantize(CENT, ROUND_HALF_UP)
    return FeeBreakdown(
        subtotal=subtotal.quantize(CENT),
        buyer_fee=buyer_fee,
        total=(subtotal + buyer_fee).quantize(CENT),
        commission_amount=commission,
        organizer_net=(subtotal - commission).quantize(CENT),
        commission_pct=commission_pct,
        buyer_fee_pct=buyer_fee_pct,
        buyer_fee_flat=buyer_fee_flat,
    )


def _hold_minutes() -> int:
    from apps.cms.models import SiteSettings

    return SiteSettings.load().hold_minutes or settings.NEXOPAY["HOLD_MINUTES"]


def identities_for(user, phone: str) -> list[str]:
    ids = {f"email:{user.email.lower()}", f"phone:{normalize_phone(phone)}"}
    if user.phone:
        ids.add(f"phone:{user.phone}")
    return sorted(ids)


def _lock_ticket_types(ids) -> dict[int, TicketType]:
    rows = TicketType.objects.select_for_update().filter(pk__in=ids).order_by("pk")
    return {t.pk: t for t in rows}


def release_order(order: Order, new_status: str) -> None:
    """Give an unpaid order's held stock and identity claims back. Caller holds the order lock."""
    if order.status != Order.Status.PENDING_PAYMENT:
        return
    items = list(order.items.all())
    _lock_ticket_types([i.ticket_type_id for i in items])
    for item in items:
        TicketType.objects.filter(pk=item.ticket_type_id).update(held_count=F("held_count") - item.quantity)
    PurchaseClaim.objects.filter(order=order).delete()
    order.status = new_status
    order.save(update_fields=["status", "updated_at"])


@transaction.atomic
def start_checkout(
    *,
    user,
    event: Event,
    quantities: dict[int, int],
    buyer_name: str,
    buyer_phone: str,
    delivery_email: str,
    language: str = "en",
) -> Order:
    quantities = {int(k): int(v) for k, v in quantities.items() if int(v) > 0}
    if not quantities:
        raise CheckoutError(_("Choose at least one ticket."))

    event = Event.objects.select_related("organizer").get(pk=event.pk)
    if not event.is_purchasable:
        raise CheckoutError(_("Tickets for this event are not on sale right now."))
    if sum(quantities.values()) > event.max_tickets_per_order:
        raise CheckoutError(
            _("You can buy at most %(n)s tickets in one order.") % {"n": event.max_tickets_per_order}
        )
    phone = normalize_phone(buyer_phone)

    # A buyer retrying checkout replaces their own unpaid order for this event,
    # so their earlier hold never blocks them.
    for stale in Order.objects.select_for_update().filter(
        user=user, event=event, status=Order.Status.PENDING_PAYMENT
    ):
        release_order(stale, Order.Status.CANCELLED)

    locked = _lock_ticket_types(quantities.keys())
    if len(locked) != len(quantities) or any(t.event_id != event.pk for t in locked.values()):
        raise CheckoutError(_("One of the selected tickets is no longer available."))

    subtotal = Decimal("0")
    for tt_id, qty in quantities.items():
        tt = locked[tt_id]
        if not tt.is_on_sale_now:
            raise CheckoutError(_("“%(name)s” is not on sale right now.") % {"name": tt.name})
        if qty > tt.effective_max_per_order:
            raise CheckoutError(
                _("You can buy at most %(n)s of “%(name)s”.") % {"n": tt.effective_max_per_order, "name": tt.name}
            )
        if tt.remaining < qty:
            if tt.remaining == 0:
                raise CheckoutError(_("“%(name)s” is sold out.") % {"name": tt.name})
            raise CheckoutError(_("Only %(n)s left of “%(name)s”.") % {"n": tt.remaining, "name": tt.name})
        subtotal += tt.price * qty

    fees = calculate_fees(subtotal, event.organizer)
    order = Order.objects.create(
        user=user,
        event=event,
        buyer_name=buyer_name.strip(),
        buyer_phone=phone,
        delivery_email=delivery_email.strip().lower(),
        language=language,
        expires_at=timezone.now() + timedelta(minutes=_hold_minutes()),
        subtotal=fees.subtotal,
        buyer_fee=fees.buyer_fee,
        total=fees.total,
        commission_amount=fees.commission_amount,
        organizer_net=fees.organizer_net,
        commission_pct=fees.commission_pct,
        buyer_fee_pct=fees.buyer_fee_pct,
        buyer_fee_flat=fees.buyer_fee_flat,
    )

    identities = identities_for(user, phone)
    claims = []
    for tt_id, qty in quantities.items():
        tt = locked[tt_id]
        OrderItem.objects.create(order=order, ticket_type=tt, quantity=qty, unit_price=tt.price)
        TicketType.objects.filter(pk=tt_id).update(held_count=F("held_count") + qty)
        if not tt.allow_quantity:
            claims.extend(PurchaseClaim(ticket_type=tt, identity=i, order=order) for i in identities)

    if claims:
        taken = PurchaseClaim.objects.filter(
            ticket_type_id__in={c.ticket_type_id for c in claims}, identity__in=identities
        ).select_related("ticket_type")
        if taken:
            raise CheckoutError(
                _("You already have a ticket for “%(name)s”. Each person can buy it only once.")
                % {"name": taken[0].ticket_type.name}
            )
        try:
            with transaction.atomic():
                PurchaseClaim.objects.bulk_create(claims)
        except IntegrityError:
            # Lost a race with a concurrent checkout for the same identity.
            raise CheckoutError(_("You already have a ticket for this event. Each person can buy it only once."))

    if order.is_free:
        from apps.payments.services import fulfill_free_order

        fulfill_free_order(order)
    return order


def expire_stale_orders(limit: int = 500) -> int:
    """Release holds of orders whose payment window has passed. Run from cron."""
    now = timezone.now()
    ids = list(
        Order.objects.filter(status=Order.Status.PENDING_PAYMENT, expires_at__lt=now).values_list("pk", flat=True)[
            :limit
        ]
    )
    expired = 0
    for pk in ids:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=pk)
            if order.status == Order.Status.PENDING_PAYMENT and order.expires_at < now:
                release_order(order, Order.Status.EXPIRED)
                expired += 1
    if expired:
        logger.info("Expired %s unpaid orders", expired)
    return expired
