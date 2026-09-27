import pytest

from apps.orders.services import start_checkout
from apps.payments.models import Provider
from apps.payments.services import mark_succeeded, new_attempt
from apps.tickets.models import ScanLog, Ticket
from apps.tickets.services import redeem_ticket

from .conftest import checkout_kwargs
from .factories import EventFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def ticket(buyer, event, ticket_type):
    order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
    mark_succeeded(new_attempt(order, Provider.MOCK), "T1")
    return order.tickets.get()


@pytest.fixture
def gate_staff(db):
    return UserFactory()


def test_first_scan_checks_in(ticket, event, gate_staff):
    result = redeem_ticket(raw=ticket.token, event=event, scanned_by=gate_staff)
    assert result.ok
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.REDEEMED
    assert ticket.redeemed_by == gate_staff


def test_double_redemption_is_rejected(ticket, event, gate_staff):
    """A screenshotted / forwarded QR must never get a second person in."""
    first = redeem_ticket(raw=ticket.token, event=event, scanned_by=gate_staff)
    ticket.refresh_from_db()
    first_redeemed_at = ticket.redeemed_at

    second = redeem_ticket(raw=ticket.token, event=event, scanned_by=UserFactory())
    third = redeem_ticket(raw=ticket.token, event=event, scanned_by=gate_staff)

    assert first.ok
    assert second.result == ScanLog.Result.ALREADY_REDEEMED and not second.ok
    assert third.result == ScanLog.Result.ALREADY_REDEEMED
    ticket.refresh_from_db()
    assert ticket.redeemed_at == first_redeemed_at  # state unchanged by repeat scans
    assert ticket.redeemed_by == gate_staff
    assert ScanLog.objects.filter(ticket=ticket).count() == 3


def test_manual_code_entry(ticket, event, gate_staff):
    assert redeem_ticket(raw=ticket.code.lower(), event=event, scanned_by=gate_staff).ok


def test_forged_token_is_invalid(ticket, event, gate_staff):
    forged = ticket.token[:-2] + "xx"
    assert redeem_ticket(raw=forged, event=event, scanned_by=gate_staff).result == ScanLog.Result.INVALID
    ticket.refresh_from_db()
    assert ticket.status == Ticket.Status.VALID


def test_wrong_event_is_rejected(ticket, gate_staff):
    other = EventFactory()
    result = redeem_ticket(raw=ticket.token, event=other, scanned_by=gate_staff)
    assert result.result == ScanLog.Result.WRONG_EVENT


def test_refunded_ticket_is_rejected(ticket, event, gate_staff):
    Ticket.objects.filter(pk=ticket.pk).update(status=Ticket.Status.REFUNDED)
    assert redeem_ticket(raw=ticket.token, event=event, scanned_by=gate_staff).result == ScanLog.Result.REFUNDED
