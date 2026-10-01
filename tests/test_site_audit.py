"""Regressions found in the site audit: favicon, error pages, ticket links, admin query counts."""
import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.contrib.staticfiles import finders
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory
from django.urls import reverse
from django.views import defaults
from django.views.csrf import csrf_failure

from apps.orders.services import start_checkout
from apps.payments.models import Provider
from apps.payments.services import mark_succeeded, new_attempt
from apps.tickets.models import Ticket

from .conftest import checkout_kwargs
from .factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def ticket(buyer, event, ticket_type):
    order = start_checkout(**checkout_kwargs(buyer, event, {ticket_type.pk: 1}))
    mark_succeeded(new_attempt(order, Provider.MOCK), "AUDIT-1")
    return order.tickets.get()


@pytest.fixture
def staff_client(client):
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    return client


def _request(path="/"):
    request = RequestFactory().get(path)
    request.user = AnonymousUser()
    return request


def test_favicon_redirects_to_a_file_that_exists(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 301
    assert response["Location"].endswith("img/favicon.ico")
    assert finders.find("img/favicon.ico"), "favicon.ico redirect points at a missing static file (500 in production)"


def test_404_page_is_branded_with_search(client):
    response = client.get("/no-such-page-here/")
    assert response.status_code == 404
    html = response.content.decode()
    assert "This page isn&#x27;t here" in html or "This page isn't here" in html
    assert 'role="search"' in html


def test_403_page_renders():
    response = defaults.permission_denied(_request(), PermissionDenied())
    assert response.status_code == 403
    assert "403" in response.content.decode()


@pytest.mark.parametrize("view, status, text", [
    (lambda r: defaults.server_error(r), 500, "Something went wrong"),
    (lambda r: defaults.bad_request(r, Exception()), 400, "<main>"),
    (lambda r: csrf_failure(r), 403, "This page was open for a while"),
])
def test_standalone_error_pages_render_without_site_context(view, status, text):
    response = view(_request())
    assert response.status_code == status
    html = response.content.decode()
    assert text in html
    assert "নিরাপত্তার" in html or status != 403  # Bangla line on the expired-form page


def test_ticket_url_opens_the_pass(client, buyer, ticket):
    url = ticket.get_absolute_url()
    assert url == reverse("accounts:ticket", kwargs={"code": ticket.code})
    client.force_login(buyer)
    assert client.get(url).status_code == 200


def test_admin_view_on_site_for_a_ticket(staff_client, ticket):
    ct = ContentType.objects.get_for_model(Ticket)
    response = staff_client.get(reverse("admin:view_on_site", args=[ct.pk, ticket.pk]))
    assert response.status_code == 302
    assert ticket.code in response["Location"]


def test_admin_dashboard_query_count_stays_flat(staff_client, ticket, django_assert_max_num_queries):
    staff_client.get(reverse("admin:index"))  # warm caches (settings, content types)
    with django_assert_max_num_queries(40):
        assert staff_client.get(reverse("admin:index")).status_code == 200


def test_admin_user_list_query_count(staff_client, django_assert_max_num_queries):
    for _ in range(15):
        UserFactory()
    url = reverse("admin:accounts_user_changelist")
    staff_client.get(url)
    with django_assert_max_num_queries(16):
        assert staff_client.get(url).status_code == 200


class TestRefundAfterGateScan:
    """A refund requested before the show must not pay out once the ticket was used at the gate."""

    def test_refund_is_rejected_when_ticket_was_scanned_in(self, ticket, event):
        from apps.payments.models import Refund
        from apps.payments.refunds import process_refund, request_refund
        from apps.tickets.services import redeem_ticket

        refund = request_refund(order=ticket.order, reason="Can't make it")
        assert redeem_ticket(raw=ticket.token, event=event, scanned_by=UserFactory()).ok
        refund = process_refund(refund)
        assert refund.status == Refund.Status.REJECTED
        ticket.refresh_from_db()
        ticket.order.refresh_from_db()
        assert ticket.status == Ticket.Status.REDEEMED
        assert ticket.order.status == "paid"

    def test_organizer_sees_checked_in_instead_of_refund_button(self, client, ticket, event):
        from apps.tickets.services import redeem_ticket

        redeem_ticket(raw=ticket.token, event=event, scanned_by=UserFactory())
        client.force_login(event.organizer.user)
        html = client.get(reverse("organizers:event", kwargs={"slug": event.slug})).content.decode()
        assert ticket.order.reference in html
        assert reverse("organizers:order_refund", args=[event.slug, ticket.order.reference]) not in html

    def test_refund_errors_are_translated(self, client, ticket, event):
        from apps.tickets.services import redeem_ticket

        redeem_ticket(raw=ticket.token, event=event, scanned_by=UserFactory())
        client.force_login(event.organizer.user)
        url = "/bn" + reverse("organizers:order_refund", args=[event.slug, ticket.order.reference])
        response = client.post(url, {"reason": "x"}, follow=True)
        assert "There are no refundable" not in response.content.decode()


def test_ticket_panel_marks_tickets_the_buyer_already_has(client, buyer, ticket, event, ticket_type):
    client.force_login(buyer)
    owned = f'href="{reverse("accounts:tickets")}" class="inline-flex shrink-0'
    html = client.get(reverse("events:ticket_panel", args=[event.slug])).content.decode()
    assert owned in html
    assert f'name="q_{ticket_type.pk}"' in html  # the row stays, only the picker is replaced
    client.logout()
    assert owned not in client.get(reverse("events:ticket_panel", args=[event.slug])).content.decode()
