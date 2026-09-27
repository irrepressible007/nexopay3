import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.events.models import Category, Event
from apps.orders.models import Order
from apps.orders.services import start_checkout
from apps.organizers.models import OrganizerProfile
from apps.payments.models import PaymentProviderSetting
from apps.payments.services import new_attempt, mark_succeeded
from apps.tickets.models import ScannerAccess, Ticket

from .conftest import checkout_kwargs
from .factories import EventFactory, OrganizerFactory, TicketTypeFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def mock_payments(settings):
    settings.ALLOW_MOCK_PAYMENTS = True
    PaymentProviderSetting.objects.filter(provider="mock").update(is_enabled=True)


class TestPublicPages:
    def test_home_is_edge_cacheable_and_user_agnostic(self, client, event, ticket_type):
        response = client.get("/")
        assert response.status_code == 200
        assert "s-maxage=60" in response["Cache-Control"] and "public" in response["Cache-Control"]
        assert not response.cookies  # no session/csrf cookie → Cloudflare may cache it
        assert b'hx-get="/_/nav/"' in response.content

    def test_bangla_url_prefix(self, client, event):
        response = client.get("/bn/events/")
        assert response.status_code == 200
        assert b'lang="bn"' in response.content

    def test_catalog_combines_category_and_status_filters(self, client):
        concert, festival = Category.objects.get(slug="concert"), Category.objects.get(slug="festivals")
        live_concert = EventFactory(categories=[concert], status=Event.Status.ON_SALE, title="Live Concert")
        soon_concert = EventFactory(categories=[concert], status=Event.Status.COMING_SOON, title="Soon Concert")
        live_fest = EventFactory(categories=[festival], status=Event.Status.ON_SALE, title="Live Fest")
        EventFactory(categories=[concert], status=Event.Status.DRAFT, title="Draft Concert")

        page = client.get("/events/?category=concert&status=live").context["page"]
        assert list(page.object_list) == [live_concert]
        page = client.get("/events/?category=concert&category=festivals&status=live").context["page"]
        assert set(page.object_list) == {live_concert, live_fest}
        page = client.get("/events/?status=upcoming").context["page"]
        assert list(page.object_list) == [soon_concert]
        counts = {c.slug: c.n for c in client.get("/events/?status=live").context["categories"]}
        assert counts["concert"] == 1 and counts["festivals"] == 1 and counts["reunions"] == 0

    def test_event_page_and_live_ticket_panel(self, client, event, ticket_type):
        assert client.get(event.get_absolute_url()).status_code == 200
        panel = client.get(reverse("events:ticket_panel", args=[event.slug]))
        assert "no-store" in panel["Cache-Control"]
        assert ticket_type.name.encode() in panel.content

    def test_draft_is_hidden_from_public_but_previewable_by_owner(self, client, organizer):
        draft = EventFactory(organizer=organizer, status=Event.Status.DRAFT)
        assert client.get(draft.get_absolute_url()).status_code == 404
        client.force_login(organizer.user)
        assert client.get(draft.get_absolute_url()).status_code == 200

    def test_ics_download(self, client, event):
        response = client.get(reverse("events:ics", args=[event.slug]))
        assert response["Content-Type"].startswith("text/calendar")
        assert b"BEGIN:VEVENT" in response.content


class TestCheckoutViews:
    def test_requires_login(self, client, event, ticket_type):
        response = client.get(reverse("orders:checkout", args=[event.slug]) + f"?q_{ticket_type.pk}=1")
        assert response.status_code == 302 and "/accounts/login/" in response["Location"]

    def test_post_creates_order_and_redirects_to_gateway(self, client, buyer, event, ticket_type, mock_payments):
        client.force_login(buyer)
        response = client.post(reverse("orders:checkout", args=[event.slug]), {
            f"q_{ticket_type.pk}": 1, "buyer_name": "Rahim", "buyer_phone": "01812345678",
            "delivery_email": "rahim@example.com", "payment_method": "mock", "agree": "on",
        })
        order = Order.objects.get(user=buyer)
        assert response.status_code == 302 and "/payments/test-gateway/" in response["Location"]
        assert order.status == Order.Status.PENDING_PAYMENT and order.delivery_email == "rahim@example.com"

    def test_other_users_cannot_see_an_order(self, client, buyer, event, ticket_type):
        order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
        client.force_login(UserFactory())
        assert client.get(order.get_absolute_url()).status_code == 404

    def test_ticket_pdf_download_for_owner_only(self, client, buyer, event, ticket_type):
        order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
        mark_succeeded(new_attempt(order, "mock"), "M1")
        ticket = order.tickets.get()
        client.force_login(buyer)
        pdf = client.get(reverse("accounts:ticket_pdf", args=[ticket.code]))
        assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
        client.force_login(UserFactory())
        assert client.get(reverse("accounts:ticket_pdf", args=[ticket.code])).status_code == 404

    def test_share_link_needs_valid_signature(self, client, buyer, event, ticket_type):
        order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
        mark_succeeded(new_attempt(order, "mock"), "M2")
        ticket = order.tickets.get()
        assert client.get(reverse("tickets:share", args=[ticket.token])).status_code == 200
        assert client.get(reverse("tickets:share", args=[ticket.id.hex + ":forged"])).status_code == 404


class TestOrganizerFlow:
    def test_application_lands_in_pending_review(self, client):
        user = UserFactory()
        client.force_login(user)
        response = client.post(reverse("organizers:apply"), {
            "name": "Dhaka Beats", "contact_email": "hi@beats.example", "contact_phone": "01712345678",
            "application_note": "Monthly concerts, 500-2000 people",
        })
        assert response.status_code == 302
        profile = OrganizerProfile.objects.get(user=user)
        assert profile.status == OrganizerProfile.Status.PENDING_REVIEW
        # Not approved yet: the dashboard sends them back to the status page.
        assert client.get(reverse("organizers:dashboard"))["Location"].endswith(reverse("organizers:apply"))

    def test_approved_organizer_publishes_multi_segment_event(self, client, organizer):
        client.force_login(organizer.user)
        starts = (timezone.localtime() + timedelta(days=20)).strftime("%Y-%m-%dT%H:%M")
        data = {
            "title_en": "Robo Fest", "summary_en": "Robots!", "description_en": "<p>Build <b>robots</b></p>",
            "categories": [Category.objects.get(slug="competitions").pk, Category.objects.get(slug="festivals").pk],
            "starts_at": starts, "venue_name_en": "BUET", "city": "Dhaka", "max_tickets_per_order": 5,
            "action": "publish",
            "tt-TOTAL_FORMS": 2, "tt-INITIAL_FORMS": 0, "tt-MIN_NUM_FORMS": 0, "tt-MAX_NUM_FORMS": 1000,
            "tt-0-name_en": "Entry", "tt-0-price": "150", "tt-0-stock": 200, "tt-0-max_per_order": 1,
            "tt-0-is_available": "on", "tt-0-sort_order": 0,
            "tt-1-name_en": "Golden", "tt-1-price": "600", "tt-1-stock": 20, "tt-1-max_per_order": 1,
            "tt-1-is_available": "on", "tt-1-is_bundle": "on", "tt-1-sort_order": 1,
        }
        response = client.post(reverse("organizers:event_new"), data)
        assert response.status_code == 302, response.context and response.context["form"].errors
        event = Event.objects.get(title_en="Robo Fest")
        assert event.status == Event.Status.ON_SALE and event.organizer == organizer
        assert event.categories.count() == 2 and event.ticket_types.count() == 2
        assert client.get(reverse("organizers:event", args=[event.slug])).status_code == 200

    def test_cannot_open_another_organizers_event(self, client, organizer):
        other = EventFactory(organizer=OrganizerFactory())
        client.force_login(organizer.user)
        assert client.get(reverse("organizers:event", args=[other.slug])).status_code == 404
        assert client.get(reverse("organizers:attendees_csv", args=[other.slug])).status_code == 404

    def test_attendee_csv(self, client, organizer, buyer):
        event = EventFactory(organizer=organizer)
        tt = TicketTypeFactory(event=event, price=Decimal("0"))
        start_checkout(**checkout_kwargs(buyer, event, {tt.pk: 1}))
        client.force_login(organizer.user)
        response = client.get(reverse("organizers:attendees_csv", args=[event.slug]))
        assert response.status_code == 200 and buyer.email.encode() in response.content


class TestScanner:
    @pytest.fixture
    def paid_ticket(self, buyer, event, ticket_type):
        order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
        mark_succeeded(new_attempt(order, "mock"), "S1")
        return order.tickets.get()

    def _scan(self, client, event, code):
        return client.post(reverse("scan:redeem", args=[event.slug]), json.dumps({"code": code}),
                           content_type="application/json")

    def test_staff_scan_then_reject_duplicate(self, client, event, paid_ticket):
        staff = UserFactory()
        ScannerAccess.objects.create(event=event, user=staff)
        client.force_login(staff)
        first = self._scan(client, event, paid_ticket.token).json()
        second = self._scan(client, event, paid_ticket.token).json()
        assert first["ok"] is True and first["counts"]["checked_in"] == 1
        assert second["ok"] is False and second["result"] == "already_redeemed"
        assert second["ticket"]["redeemed_at"]

    def test_random_user_cannot_scan(self, client, event, paid_ticket):
        client.force_login(UserFactory())
        assert self._scan(client, event, paid_ticket.token).status_code == 403
        paid_ticket.refresh_from_db()
        assert paid_ticket.status == Ticket.Status.VALID

    def test_scanner_page_for_organizer(self, client, organizer, event):
        client.force_login(organizer.user)
        assert client.get(reverse("scan:event", args=[event.slug])).status_code == 200


def test_admin_dashboard_renders(client, event, ticket_type):
    admin = UserFactory(is_staff=True, is_superuser=True)
    client.force_login(admin)
    response = client.get("/control-room/")
    assert response.status_code == 200
    assert b"Sales today" in response.content
    for url in ["/control-room/events/event/", "/control-room/orders/order/", "/control-room/payments/refund/",
                "/control-room/cms/homesection/", "/control-room/organizers/organizerprofile/",
                f"/control-room/events/event/{event.pk}/change/", "/control-room/cms/sitesettings/1/change/"]:
        assert client.get(url).status_code == 200, url


def test_maintenance_mode_blocks_public_but_not_staff_or_payments(client):
    from apps.cms.models import SiteSettings

    site = SiteSettings.load()
    site.maintenance_mode = True
    site.save()
    assert client.get("/").status_code == 503
    assert client.get("/payments/mock/return/").status_code != 503
    client.force_login(UserFactory(is_staff=True))
    assert client.get("/").status_code == 200


def test_private_documents_are_staff_only(client):
    from django.core.files.base import ContentFile
    from django.core.files.storage import storages

    storage = storages["private"]
    name = storage.save("org/test/docs/licence.pdf", ContentFile(b"%PDF-1.4 test"))
    url = f"/private-media/{name}"
    try:
        assert client.get(url).status_code == 302  # to the admin login
        client.force_login(UserFactory())
        assert client.get(url).status_code == 302
        client.force_login(UserFactory(is_staff=True))
        response = client.get(url)
        assert response.status_code == 200 and b"".join(response.streaming_content).startswith(b"%PDF")
        assert client.get("/private-media/../settings.py").status_code == 404
    finally:
        storage.delete(name)
