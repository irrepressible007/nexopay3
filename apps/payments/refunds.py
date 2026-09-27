"""
Platform-level refunds. Buyers never negotiate refunds with organizers
off-platform: an admin (or an organizer with permission) issues them here,
through the provider's refund API when it has one, or records a manual refund.
"""
import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.events.models import Event, TicketType
from apps.orders.models import Order, PurchaseClaim
from apps.tickets.models import Ticket

from .models import PaymentAttempt, Provider, Refund
from .registry import get_provider
from .services import PaymentError

logger = logging.getLogger("apps.payments")
NO_MONEY_PROVIDERS = (Provider.FREE, Provider.MOCK)


class RefundError(Exception):
    pass


def paid_attempt(order: Order) -> PaymentAttempt | None:
    return order.payment_attempts.filter(status=PaymentAttempt.Status.SUCCEEDED).order_by("completed_at").first()


@transaction.atomic
def request_refund(*, order: Order, reason: str, by=None, tickets=None, approve=False) -> Refund:
    """Create a refund for some or all of an order's valid tickets."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status not in (Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED):
        raise RefundError("Only paid orders can be refunded.")
    valid = order.tickets.select_related("order_item").filter(status=Ticket.Status.VALID)
    if tickets is not None:
        valid = valid.filter(pk__in=[t.pk for t in tickets])
    selected = list(valid)
    if not selected:
        raise RefundError("There are no refundable (unused) tickets in this order.")
    already_pending = Refund.objects.filter(
        order=order, status__in=(Refund.Status.REQUESTED, Refund.Status.APPROVED), tickets__in=selected
    ).exists()
    if already_pending:
        raise RefundError("A refund for these tickets is already in progress.")

    amount = sum((t.order_item.unit_price for t in selected), Decimal("0"))
    remaining_valid = order.tickets.filter(status=Ticket.Status.VALID).count()
    if len(selected) == remaining_valid:
        amount += order.buyer_fee  # refunding everything that's left: include the service fee
    refund = Refund.objects.create(
        order=order,
        attempt=paid_attempt(order),
        amount=amount,
        reason=reason,
        requested_by=by,
        status=Refund.Status.APPROVED if approve else Refund.Status.REQUESTED,
        approved_by=by if approve else None,
    )
    refund.tickets.set(selected)
    return refund


def process_refund(refund: Refund, by=None) -> Refund:
    """Approve (if needed) and try to send the money back through the provider API."""
    with transaction.atomic():
        refund = Refund.objects.select_for_update().select_related("attempt", "order").get(pk=refund.pk)
        if refund.status not in (Refund.Status.REQUESTED, Refund.Status.APPROVED):
            return refund
        if refund.status == Refund.Status.REQUESTED:
            refund.status = Refund.Status.APPROVED
            refund.approved_by = by
            refund.save(update_fields=["status", "approved_by", "updated_at"])

    attempt = refund.attempt
    if attempt is None or attempt.provider in NO_MONEY_PROVIDERS or refund.amount == 0:
        return _finalize(refund, provider_refund_id="", payload={"note": "no money to return"})

    provider = get_provider(attempt.provider, require_enabled=False)
    if provider is None or not provider.supports_refund_api:
        logger.info("Refund %s needs manual processing (%s has no refund API)", refund.pk, attempt.provider)
        return refund
    try:
        result = provider.refund(attempt, refund.amount, refund.reason)
    except PaymentError as exc:
        Refund.objects.filter(pk=refund.pk).update(raw={"error": str(exc)})
        logger.warning("Refund %s API call failed: %s", refund.pk, exc)
        return refund
    if not result.ok:
        Refund.objects.filter(pk=refund.pk).update(raw={"response": result.payload, "message": result.message})
        return refund
    return _finalize(refund, provider_refund_id=result.provider_refund_id, payload=result.payload)


def mark_refunded_manually(refund: Refund, reference: str, by=None) -> Refund:
    """Record a refund that was sent outside the API (e.g. from the Nagad merchant portal)."""
    if refund.status == Refund.Status.REQUESTED:
        refund.status = Refund.Status.APPROVED
        refund.approved_by = by
        refund.save(update_fields=["status", "approved_by", "updated_at"])
    Refund.objects.filter(pk=refund.pk).update(manual_reference=reference)
    refund.manual_reference = reference
    return _finalize(refund, provider_refund_id="", payload={"manual_reference": reference})


@transaction.atomic
def _finalize(refund: Refund, *, provider_refund_id: str, payload) -> Refund:
    refund = Refund.objects.select_for_update().get(pk=refund.pk)
    if refund.status == Refund.Status.SUCCEEDED:
        return refund
    refund.status = Refund.Status.SUCCEEDED
    refund.provider_refund_id = provider_refund_id
    refund.completed_at = timezone.now()
    refund.raw = {**(refund.raw or {}), "result": payload}
    refund.save()

    tickets = list(refund.tickets.select_related("ticket_type", "event").select_for_update())
    if not tickets:
        return refund  # money-only refund (duplicate / late payment)

    order = Order.objects.select_for_update().get(pk=refund.order_id)
    Ticket.objects.filter(pk__in=[t.pk for t in tickets]).update(status=Ticket.Status.REFUNDED)

    event = order.event
    release_stock = event.status in (Event.Status.ON_SALE, Event.Status.SOLD_OUT, Event.Status.COMING_SOON)
    per_type: dict[int, int] = {}
    for t in tickets:
        per_type[t.ticket_type_id] = per_type.get(t.ticket_type_id, 0) + 1
    for tt_id, count in per_type.items():
        if release_stock:
            TicketType.objects.filter(pk=tt_id).update(sold_count=F("sold_count") - count)
        if not order.tickets.filter(ticket_type_id=tt_id, status=Ticket.Status.VALID).exists():
            PurchaseClaim.objects.filter(order=order, ticket_type_id=tt_id).delete()

    still_valid = order.tickets.exclude(status=Ticket.Status.REFUNDED).exists()
    order.status = Order.Status.PARTIALLY_REFUNDED if still_valid else Order.Status.REFUNDED
    order.save(update_fields=["status", "updated_at"])
    if release_stock:
        event.refresh_sold_out_status()

    from .tasks import notify_refund

    refund_pk = refund.pk
    transaction.on_commit(lambda: notify_refund.enqueue(refund_pk))
    return refund


def cancel_event(event: Event, *, reason: str, by=None) -> int:
    """Cancel an event and refund every paid order in full. Returns the number of refunds created."""
    Event.objects.filter(pk=event.pk).update(status=Event.Status.CANCELLED)
    created = 0
    for order in Order.objects.filter(event=event, status__in=(Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED)):
        try:
            refund = request_refund(order=order, reason=reason, by=by, approve=True)
        except RefundError:
            continue
        process_refund(refund, by=by)
        created += 1
    return created
