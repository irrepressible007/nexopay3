"""
The single "payment succeeded" contract every provider funnels into.

Whether money arrived through bKash, Nagad, Upay, Pathao Pay, SSLCommerz or a
free checkout, confirmation and ticket generation happen here — identically,
idempotently, and inside one transaction.
"""
import logging

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.events.models import TicketType
from apps.orders.models import Order, PurchaseClaim
from apps.orders.services import identities_for
from apps.tickets.models import Ticket

from .models import PaymentAttempt, Provider, Refund

logger = logging.getLogger(__name__)


class PaymentError(Exception):
    """A provider call failed in a way the buyer should be told about."""


def new_attempt(order: Order, provider: str) -> PaymentAttempt:
    n = order.payment_attempts.count() + 1
    return PaymentAttempt.objects.create(
        order=order, provider=provider, tran_id=f"{order.reference}-{n}", amount=order.total
    )


@transaction.atomic
def mark_succeeded(attempt: PaymentAttempt, provider_txn_id: str, payload=None) -> Order:
    """
    Record a verified successful payment and fulfil its order.

    Safe to call any number of times for the same transaction (providers retry
    callbacks/IPNs, buyers refresh return pages) — the second call is a no-op.
    """
    attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
    order = Order.objects.select_for_update().get(pk=attempt.order_id)
    if attempt.status == PaymentAttempt.Status.SUCCEEDED:
        return order

    duplicate = (
        PaymentAttempt.objects.filter(provider=attempt.provider, provider_txn_id=provider_txn_id)
        .exclude(pk=attempt.pk)
        .exists()
    )
    if duplicate:
        logger.warning("Transaction %s already recorded on another attempt; ignoring", provider_txn_id)
        return order

    attempt.status = PaymentAttempt.Status.SUCCEEDED
    attempt.provider_txn_id = provider_txn_id
    attempt.completed_at = timezone.now()
    if payload is not None:
        attempt.log("success", payload)
    attempt.save()

    _fulfil(order, attempt)
    return order


@transaction.atomic
def mark_failed(attempt: PaymentAttempt, status=PaymentAttempt.Status.FAILED, payload=None) -> None:
    attempt = PaymentAttempt.objects.select_for_update().get(pk=attempt.pk)
    if attempt.status != PaymentAttempt.Status.INITIATED:
        return
    attempt.status = status
    attempt.completed_at = timezone.now()
    if payload is not None:
        attempt.log(status, payload)
    attempt.save()


@transaction.atomic
def fulfill_free_order(order: Order) -> Order:
    order = Order.objects.select_for_update().get(pk=order.pk)
    attempt = new_attempt(order, Provider.FREE)
    attempt.status = PaymentAttempt.Status.SUCCEEDED
    attempt.provider_txn_id = attempt.tran_id
    attempt.completed_at = timezone.now()
    attempt.save()
    _fulfil(order, attempt)
    return order


def _fulfil(order: Order, attempt: PaymentAttempt) -> None:
    """Convert holds to sales and issue tickets. Caller holds the order lock."""
    if order.status in (Order.Status.PAID, Order.Status.REFUNDED, Order.Status.PARTIALLY_REFUNDED):
        # The order was already paid through another attempt: the buyer paid twice.
        _auto_refund(order, attempt, "Duplicate payment for an order that was already paid.")
        return

    items = list(order.items.select_related("ticket_type"))
    locked = {
        t.pk: t
        for t in TicketType.objects.select_for_update().filter(pk__in=[i.ticket_type_id for i in items]).order_by("pk")
    }

    if order.status == Order.Status.PENDING_PAYMENT:
        for item in items:
            TicketType.objects.filter(pk=item.ticket_type_id).update(
                held_count=F("held_count") - item.quantity, sold_count=F("sold_count") + item.quantity
            )
    else:
        # Payment landed after the hold expired (or was replaced). Honour it if
        # stock and the one-per-person rule still allow, otherwise refund.
        if any(locked[i.ticket_type_id].remaining < i.quantity for i in items):
            _auto_refund(order, attempt, "Payment arrived after the ticket hold expired and the tickets sold out.")
            return
        try:
            with transaction.atomic():
                identities = identities_for(order.user, order.buyer_phone)
                PurchaseClaim.objects.bulk_create(
                    [
                        PurchaseClaim(ticket_type=i.ticket_type, identity=ident, order=order)
                        for i in items
                        if not i.ticket_type.allow_quantity
                        for ident in identities
                    ]
                )
        except IntegrityError:
            _auto_refund(order, attempt, "Payment arrived after the hold expired; buyer already holds this ticket.")
            return
        for item in items:
            TicketType.objects.filter(pk=item.ticket_type_id).update(sold_count=F("sold_count") + item.quantity)

    order.status = Order.Status.PAID
    order.paid_at = timezone.now()
    order.payment_method = attempt.provider
    order.save(update_fields=["status", "paid_at", "payment_method", "updated_at"])

    tickets = []
    for item in items:
        for _ in range(item.quantity):
            tickets.append(
                Ticket(
                    order=order,
                    order_item=item,
                    ticket_type=item.ticket_type,
                    event_id=order.event_id,
                    owner=order.user,
                    holder_name=order.buyer_name,
                )
            )
    Ticket.objects.bulk_create(tickets)
    order.event.refresh_sold_out_status()

    from apps.tickets.tasks import deliver_order_tickets

    order_pk = order.pk
    transaction.on_commit(lambda: deliver_order_tickets.enqueue(order_pk))
    logger.info("Order %s paid via %s (%s tickets)", order.reference, attempt.provider, len(tickets))


def _auto_refund(order: Order, attempt: PaymentAttempt, reason: str) -> None:
    logger.warning("Auto-refund queued for %s / %s: %s", order.reference, attempt.tran_id, reason)
    Refund.objects.create(
        order=order, attempt=attempt, amount=attempt.amount, reason=reason, status=Refund.Status.APPROVED
    )
