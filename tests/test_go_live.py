"""Moving to nexopay.com.bd: old Nexopay 2 addresses, www → bare domain, and the test-data purge."""
import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.events.models import Event
from apps.orders.models import Order
from apps.orders.services import start_checkout
from apps.organizers.models import OrganizerProfile
from apps.payments.models import PaymentProviderSetting, Provider
from apps.payments.services import mark_succeeded, new_attempt
from apps.tickets.models import Ticket

from .conftest import checkout_kwargs
from .factories import EventFactory, OrganizerFactory, TicketTypeFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("old, new", [
    ("/login", "/accounts/login/"),
    ("/register", "/accounts/signup/"),
    ("/forgot-password", "/accounts/password/reset/"),
    ("/dashboard", "/account/tickets/"),
    ("/profile/", "/account/profile/"),
    ("/event/national-steam-carnival-6a2318de50c6a", "/events/"),
])
def test_old_site_addresses_redirect(client, old, new):
    response = client.get(old)
    assert response.status_code == 301 and response["Location"] == new


def test_old_event_address_finds_a_matching_event(client, event):
    response = client.get(f"/event/{event.slug}")
    assert response.status_code == 301 and response["Location"] == event.get_absolute_url()


def test_www_goes_to_the_bare_domain(client, settings):
    settings.SITE_URL = "https://nexopay.com.bd"
    settings.ALLOWED_HOSTS = ["nexopay.com.bd", "www.nexopay.com.bd", "new.nexopay.com.bd"]
    response = client.get("/events/?q=jazz", HTTP_HOST="www.nexopay.com.bd")
    assert response.status_code == 301
    assert response["Location"] == "https://nexopay.com.bd/events/?q=jazz"
    assert client.get("/", HTTP_HOST="nexopay.com.bd").status_code == 200
    assert client.get("/", HTTP_HOST="new.nexopay.com.bd").status_code == 200  # devs' address still answers
    assert client.post("/contact/", HTTP_HOST="www.nexopay.com.bd").status_code != 301  # posts are never bounced


class TestPurge:
    @pytest.fixture
    def world(self, buyer, event, ticket_type):
        order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
        mark_succeeded(new_attempt(order, Provider.MOCK), "T-PURGE")
        staff = UserFactory(is_staff=True)
        staff_org = OrganizerFactory(user=staff)
        real = EventFactory(organizer=OrganizerFactory(), slug="real-launch-night")
        real_tt = TicketTypeFactory(event=real)
        real_order = start_checkout(**checkout_kwargs(UserFactory(), real, {real_tt.pk: 1}))
        mark_succeeded(new_attempt(real_order, Provider.MOCK), "T-REAL")
        PaymentProviderSetting.objects.filter(provider="mock").update(is_enabled=True)
        return {"staff": staff, "staff_org": staff_org, "real": real, "real_tt": real_tt}

    def test_dry_run_changes_nothing(self, world):
        before = (Order.objects.count(), Ticket.objects.count(), Event.objects.count())
        call_command("purge_test_data")
        assert (Order.objects.count(), Ticket.objects.count(), Event.objects.count()) == before

    def test_purge_keeps_staff_settings_and_chosen_event(self, world, buyer, event):
        call_command("purge_test_data", "--yes", "--keep-event", "real-launch-night")
        assert not Order.objects.exists() and not Ticket.objects.exists()
        assert not Event.objects.filter(pk=event.pk).exists()
        real = Event.objects.get(slug="real-launch-night")
        world["real_tt"].refresh_from_db()
        assert world["real_tt"].sold_count == 0 and world["real_tt"].held_count == 0
        assert OrganizerProfile.objects.filter(pk=real.organizer_id).exists()
        assert OrganizerProfile.objects.filter(pk=world["staff_org"].pk).exists()
        assert type(buyer).objects.filter(pk=world["staff"].pk).exists()
        assert not type(buyer).objects.filter(pk=buyer.pk).exists()
        assert not PaymentProviderSetting.objects.get(provider="mock").is_enabled

    def test_unknown_event_to_keep_stops_everything(self, world):
        call_command("purge_test_data", "--yes", "--keep-event", "no-such-event")
        assert Order.objects.exists()


def test_unknown_host_is_refused_quietly(client, mailoutbox, settings):
    settings.ADMINS = [("Ops", "ops@example.com")]
    assert client.get("/", HTTP_HOST="evil.example.com").status_code == 400
    assert mailoutbox == []
