from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from apps.core.utils import normalize_phone, sanitize_html
from apps.events.models import Category, Event, TicketType
from apps.tickets.models import Ticket

from .factories import CategoryFactory, EventFactory, TicketTypeFactory

pytestmark = pytest.mark.django_db


class TestPhone:
    @pytest.mark.parametrize("raw", ["01712345678", "+8801712345678", "8801712345678", "017-1234-5678"])
    def test_normalizes_bd_numbers(self, raw):
        assert normalize_phone(raw) == "+8801712345678"

    @pytest.mark.parametrize("raw", ["", "0171234567", "01212345678", "12345"])
    def test_rejects_invalid(self, raw):
        with pytest.raises(ValidationError):
            normalize_phone(raw)


def test_eighteen_categories_are_seeded():
    assert Category.objects.count() == 18
    assert Category.objects.filter(slug="reunions").exists()


def test_event_supports_multiple_categories():
    festivals = Category.objects.get(slug="festivals")
    competitions = Category.objects.get(slug="competitions")
    event = EventFactory(categories=[festivals, competitions])
    assert set(event.categories.values_list("slug", flat=True)) == {"festivals", "competitions"}


def test_category_counts_include_zero():
    event = EventFactory(categories=[Category.objects.get(slug="concert")])
    counts = dict(
        Category.objects.annotate(n=Count("events", filter=Q(events__pk=event.pk))).values_list("slug", "n")
    )
    assert counts["concert"] == 1
    assert counts["reunions"] == 0
    assert len(counts) == 18


def test_multi_segment_ticket_types_have_independent_stock():
    event = EventFactory()
    entry = TicketTypeFactory(event=event, name="Entry", price=Decimal("120"), stock=50)
    dance = TicketTypeFactory(event=event, name="Entry + Dance", price=Decimal("200"), stock=1)
    golden = TicketTypeFactory(event=event, name="Golden Ticket", price=Decimal("600"), stock=3, is_bundle=True)
    TicketType.objects.filter(pk=dance.pk).update(sold_count=1)
    dance.refresh_from_db()
    assert dance.availability == "sold_out"
    assert entry.availability == "available"
    assert golden.remaining == 3


def test_stock_check_constraint_blocks_oversell():
    tt = TicketTypeFactory(stock=2)
    with pytest.raises(IntegrityError), transaction.atomic():
        TicketType.objects.filter(pk=tt.pk).update(sold_count=3)


def test_event_description_is_sanitized():
    event = EventFactory(description='<p>Hi</p><script>alert(1)</script><a href="javascript:x">y</a>')
    event.refresh_from_db()
    assert "<script>" not in event.description
    assert "javascript:" not in event.description


def test_sanitize_keeps_formatting():
    assert sanitize_html("<p><strong>Bold</strong></p>") == "<p><strong>Bold</strong></p>"


def test_ticket_token_roundtrip_and_tamper():
    import uuid

    t = Ticket(id=uuid.uuid4())
    assert Ticket.id_from_token(t.token) == t.id
    tampered = t.token[:-1] + ("A" if t.token[-1] != "A" else "B")
    assert Ticket.id_from_token(tampered) is None
    assert Ticket.id_from_token(uuid.uuid4().hex) is None


def test_featured_is_independent_of_status():
    live = EventFactory(featured=True, status=Event.Status.ON_SALE)
    soon = EventFactory(featured=True, status=Event.Status.COMING_SOON)
    EventFactory(featured=True, status=Event.Status.DRAFT)
    EventFactory(featured=False, status=Event.Status.ON_SALE)
    assert set(Event.objects.featured()) == {live, soon}
