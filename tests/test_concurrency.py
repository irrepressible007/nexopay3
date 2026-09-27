"""
Real row-locking tests. They need the production engine (MySQL/MariaDB) —
SQLite serialises all writes and would pass trivially.
"""
import threading

import pytest
from django.db import connection, connections

from apps.orders.services import CheckoutError, start_checkout
from apps.payments.models import Provider
from apps.payments.services import mark_succeeded, new_attempt
from apps.tickets.models import Ticket
from apps.tickets.services import redeem_ticket

from .conftest import checkout_kwargs
from .factories import EventFactory, TicketTypeFactory, UserFactory

pytestmark = [
    pytest.mark.django_db(transaction=True, serialized_rollback=True),
    pytest.mark.skipif(connection.vendor != "mysql", reason="needs MySQL/MariaDB row locks"),
]


def _race(n, fn):
    barrier = threading.Barrier(n)
    results = []
    lock = threading.Lock()

    def worker(i):
        try:
            barrier.wait()
            outcome = fn(i)
        except Exception as exc:  # collected and asserted by the test
            outcome = exc
        finally:
            connections.close_all()
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_last_ticket_cannot_be_oversold():
    event = EventFactory()
    tt = TicketTypeFactory(event=event, stock=1)
    buyers = [UserFactory() for _ in range(8)]

    results = _race(8, lambda i: start_checkout(**checkout_kwargs(buyers[i], event, {tt.pk: 1})))

    winners = [r for r in results if not isinstance(r, Exception)]
    losers = [r for r in results if isinstance(r, CheckoutError)]
    assert len(winners) == 1, results
    assert len(losers) == 7, results
    tt.refresh_from_db()
    assert tt.held_count == 1 and tt.sold_count == 0


def test_same_identity_racing_checkouts_get_one_claim():
    event = EventFactory()
    tt = TicketTypeFactory(event=event, stock=50)
    phone = "01812345678"
    buyers = [UserFactory() for _ in range(5)]

    results = _race(5, lambda i: start_checkout(**checkout_kwargs(buyers[i], event, {tt.pk: 1}, buyer_phone=phone)))
    assert sum(1 for r in results if not isinstance(r, Exception)) == 1, results


def test_concurrent_gate_scans_admit_once():
    event = EventFactory()
    tt = TicketTypeFactory(event=event)
    order = start_checkout(**checkout_kwargs(UserFactory(), event, {tt.pk: 1}))
    mark_succeeded(new_attempt(order, Provider.MOCK), "C1")
    ticket = Ticket.objects.get(order=order)
    staff = [UserFactory() for _ in range(6)]

    results = _race(6, lambda i: redeem_ticket(raw=ticket.token, event=event, scanned_by=staff[i]))
    assert sum(1 for r in results if getattr(r, "ok", False)) == 1, results
