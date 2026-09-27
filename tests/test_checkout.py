from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.utils import timezone

from apps.cms.models import SiteSettings
from apps.events.models import Event, TicketType
from apps.orders.models import Order, PurchaseClaim
from apps.orders.services import CheckoutError, calculate_fees, expire_stale_orders, start_checkout
from apps.payments.models import PaymentAttempt, Provider, Refund
from apps.payments.services import mark_succeeded, new_attempt
from apps.tickets.models import Ticket

from .conftest import checkout_kwargs
from .factories import TicketTypeFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_checkout_holds_stock(buyer, event, ticket_type):
    order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
    ticket_type.refresh_from_db()
    assert order.status == Order.Status.PENDING_PAYMENT
    assert ticket_type.held_count == 1 and ticket_type.sold_count == 0
    assert order.total == Decimal("500.00")
    assert order.expires_at > timezone.now()


def test_multiple_ticket_types_in_one_order(buyer, event):
    entry = TicketTypeFactory(event=event, price=Decimal("120"))
    dance = TicketTypeFactory(event=event, price=Decimal("200"))
    order = start_checkout(**checkout_kwargs(buyer, event, {entry.pk: 1, dance.pk: 1}))
    assert order.items.count() == 2
    assert order.subtotal == Decimal("320.00")


def test_rejects_sold_out(buyer, event):
    tt = TicketTypeFactory(event=event, stock=1)
    TicketType.objects.filter(pk=tt.pk).update(sold_count=1)
    with pytest.raises(CheckoutError, match="sold out"):
        start_checkout(**checkout_kwargs(buyer, event, {tt.pk: 1}))


def test_rejects_when_event_not_on_sale(buyer, event, ticket_type):
    Event.objects.filter(pk=event.pk).update(status=Event.Status.COMING_SOON)
    event.refresh_from_db()
    with pytest.raises(CheckoutError):
        start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))


def test_quantity_requires_allow_quantity(buyer, event, ticket_type):
    with pytest.raises(CheckoutError, match="at most 1"):
        start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 2}))
    TicketType.objects.filter(pk=ticket_type.pk).update(allow_quantity=True, max_per_order=4)
    order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 3}))
    assert order.ticket_count == 3


def test_one_identity_one_ticket_type(buyer, event, ticket_type):
    order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
    mark_succeeded(new_attempt(order, Provider.MOCK), "TX1")
    with pytest.raises(CheckoutError, match="already have a ticket"):
        start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))


def test_same_phone_on_another_account_is_blocked(event, ticket_type):
    first = UserFactory()
    start_checkout(**checkout_kwargs(first, event, {ticket_type.pk: 1}))
    second = UserFactory()
    with pytest.raises(CheckoutError, match="already have a ticket"):
        start_checkout(**checkout_kwargs(second, event, {ticket_type.pk: 1}, buyer_phone=first.phone))


def test_allow_quantity_bypasses_identity_rule(buyer, event):
    tt = TicketTypeFactory(event=event, allow_quantity=True)
    order = start_checkout(**checkout_kwargs(buyer, event, {tt.pk: 1}))
    mark_succeeded(new_attempt(order, Provider.MOCK), "TX1")
    start_checkout(**checkout_kwargs(buyer, event, {tt.pk: 1}))  # no error


def test_retry_replaces_own_pending_order(buyer, event, ticket_type):
    first = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
    second = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
    first.refresh_from_db()
    ticket_type.refresh_from_db()
    assert first.status == Order.Status.CANCELLED
    assert second.status == Order.Status.PENDING_PAYMENT
    assert ticket_type.held_count == 1


def test_expired_holds_are_released(buyer, event, ticket_type):
    order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
    Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    assert expire_stale_orders() == 1
    order.refresh_from_db()
    ticket_type.refresh_from_db()
    assert order.status == Order.Status.EXPIRED
    assert ticket_type.held_count == 0
    assert not PurchaseClaim.objects.filter(order=order).exists()


def test_payment_success_issues_tickets_and_emails_pdf(buyer, event):
    tt = TicketTypeFactory(event=event, allow_quantity=True)
    order = start_checkout(**checkout_kwargs(buyer, event, {tt.pk: 2}))
    with pytest.MonkeyPatch.context() as mp:
        from django.db import transaction

        mp.setattr(transaction, "on_commit", lambda fn, *a, **k: fn())
        mark_succeeded(new_attempt(order, Provider.BKASH), "TRX-9")
    order.refresh_from_db()
    tt.refresh_from_db()
    assert order.status == Order.Status.PAID
    assert order.payment_method == "bkash"
    assert tt.sold_count == 2 and tt.held_count == 0
    assert Ticket.objects.filter(order=order).count() == 2
    assert len(mail.outbox) == 1
    attachment = mail.outbox[0].attachments[0]
    assert attachment[0].endswith(".pdf") and attachment[1][:4] == b"%PDF"


def test_webhook_replay_is_idempotent(buyer, event, ticket_type):
    order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
    attempt = new_attempt(order, Provider.SSLCOMMERZ)
    mark_succeeded(attempt, "BANK-TX-1")
    mark_succeeded(attempt, "BANK-TX-1")
    mark_succeeded(PaymentAttempt.objects.get(pk=attempt.pk), "BANK-TX-1")
    assert Ticket.objects.filter(order=order).count() == 1
    ticket_type.refresh_from_db()
    assert ticket_type.sold_count == 1


def test_second_successful_attempt_is_refunded(buyer, event, ticket_type):
    order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
    mark_succeeded(new_attempt(order, Provider.BKASH), "A")
    mark_succeeded(new_attempt(order, Provider.NAGAD), "B")
    assert Ticket.objects.filter(order=order).count() == 1
    assert Refund.objects.filter(order=order, status=Refund.Status.APPROVED).count() == 1


def test_late_payment_after_expiry_is_honoured_when_stock_remains(buyer, event, ticket_type):
    order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
    attempt = new_attempt(order, Provider.BKASH)
    Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    expire_stale_orders()
    mark_succeeded(attempt, "LATE-1")
    order.refresh_from_db()
    ticket_type.refresh_from_db()
    assert order.status == Order.Status.PAID
    assert ticket_type.sold_count == 1 and ticket_type.held_count == 0


def test_late_payment_after_sell_out_is_refunded(event):
    tt = TicketTypeFactory(event=event, stock=1)
    late, other = UserFactory(), UserFactory()
    order = start_checkout(**checkout_kwargs(late, event, {tt.pk: 1}))
    attempt = new_attempt(order, Provider.BKASH)
    Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    expire_stale_orders()
    other_order = start_checkout(**checkout_kwargs(other, event, {tt.pk: 1}))
    mark_succeeded(new_attempt(other_order, Provider.NAGAD), "OTHER")
    mark_succeeded(attempt, "LATE-2")
    order.refresh_from_db()
    assert order.status == Order.Status.EXPIRED
    assert Refund.objects.filter(order=order).exists()
    tt.refresh_from_db()
    assert tt.sold_count == 1


def test_event_flips_to_sold_out(buyer, event):
    tt = TicketTypeFactory(event=event, stock=1)
    order = start_checkout(**checkout_kwargs(buyer, event, {tt.pk: 1}))
    mark_succeeded(new_attempt(order, Provider.MOCK), "X")
    event.refresh_from_db()
    assert event.status == Event.Status.SOLD_OUT


def test_free_order_is_fulfilled_immediately(buyer, event):
    tt = TicketTypeFactory(event=event, price=Decimal("0"))
    order = start_checkout(**checkout_kwargs(buyer, event, {tt.pk: 1}))
    order.refresh_from_db()
    assert order.status == Order.Status.PAID
    assert order.total == 0
    assert order.tickets.count() == 1


class TestFees:
    def test_platform_defaults(self, organizer):
        site = SiteSettings.load()
        site.default_commission_pct = Decimal("5")
        site.default_buyer_fee_pct = Decimal("2")
        site.default_buyer_fee_flat = Decimal("10")
        site.save()
        fees = calculate_fees(Decimal("1000"), organizer)
        assert fees.buyer_fee == Decimal("30.00")
        assert fees.total == Decimal("1030.00")
        assert fees.commission_amount == Decimal("50.00")
        assert fees.organizer_net == Decimal("950.00")

    def test_organizer_override(self, organizer):
        organizer.commission_pct = Decimal("3.5")
        organizer.buyer_fee_pct = Decimal("0")
        organizer.buyer_fee_flat = Decimal("0")
        fees = calculate_fees(Decimal("999"), organizer)
        assert fees.commission_amount == Decimal("34.97")
        assert fees.total == Decimal("999.00")

    def test_free_orders_have_no_fees(self, organizer):
        organizer.buyer_fee_flat = Decimal("20")
        assert calculate_fees(Decimal("0"), organizer).total == 0
