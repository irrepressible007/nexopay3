"""
Security regression suite: each test is an attack that must fail.

Grouped by what an outsider (or a lower-privileged insider) would try: reading other
people's data, tampering with checkout/payments, injecting script, abusing uploads,
brute-forcing logins and escalating staff permissions.
"""
import csv
import io
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.accounts.roles import ensure_staff_roles
from apps.cms.models import SiteSettings, SiteText
from apps.events.models import Event
from apps.orders.models import Order
from apps.orders.services import start_checkout
from apps.organizers.models import OrganizerProfile
from apps.payments.models import PaymentAttempt, PaymentProviderSetting, Provider
from apps.payments.services import mark_succeeded, new_attempt
from apps.tickets.models import ScannerAccess, Ticket

from .conftest import checkout_kwargs
from .factories import EventFactory, OrganizerFactory, TicketTypeFactory, UserFactory

pytestmark = pytest.mark.django_db


# --- helpers ---------------------------------------------------------------------------
def _paid_order(user, event, ticket_type, **extra):
    order = start_checkout(**checkout_kwargs(user, event, {ticket_type.pk: 1}, **extra))
    mark_succeeded(new_attempt(order, Provider.MOCK), f"SEC-{order.reference}")
    order.refresh_from_db()
    return order


def _login(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def victim_order(buyer, event, ticket_type):
    return _paid_order(buyer, event, ticket_type)


@pytest.fixture
def attacker(db):
    return UserFactory()


# --- 1. Reading other people's data (IDOR) ---------------------------------------------
class TestBuyerIsolation:
    def test_other_buyer_cannot_open_order_tickets_or_pdfs(self, client, attacker, victim_order):
        ticket = victim_order.tickets.get()
        _login(client, attacker)
        for url in (
            reverse("orders:detail", args=[victim_order.reference]),
            reverse("accounts:ticket", args=[ticket.code]),
            reverse("accounts:ticket_pdf", args=[ticket.code]),
            reverse("accounts:order_pdf", args=[victim_order.reference]),
        ):
            assert client.get(url).status_code == 404, url
        assert client.post(reverse("orders:pay", args=[victim_order.reference]), {"payment_method": "mock"}).status_code == 404

    def test_anonymous_is_sent_to_login(self, client, victim_order):
        ticket = victim_order.tickets.get()
        for url in (reverse("orders:detail", args=[victim_order.reference]), reverse("accounts:ticket", args=[ticket.code])):
            response = client.get(url)
            assert response.status_code == 302 and "/accounts/login/" in response["Location"]

    def test_forged_share_token_is_rejected(self, client, victim_order):
        ticket = victim_order.tickets.get()
        forged = ticket.token[:-4] + ("AAAA" if not ticket.token.endswith("AAAA") else "BBBB")
        assert client.get(reverse("tickets:share", args=[forged])).status_code == 404
        assert client.get(reverse("tickets:share", args=[str(ticket.pk)])).status_code == 404  # raw id, unsigned

    def test_draft_event_is_invisible_to_the_public(self, client, attacker, organizer):
        draft = EventFactory(organizer=organizer, status=Event.Status.DRAFT)
        TicketTypeFactory(event=draft)
        _login(client, attacker)
        for url in (
            reverse("events:detail", args=[draft.slug]),
            reverse("events:ticket_panel", args=[draft.slug]),
            reverse("events:ics", args=[draft.slug]),
            reverse("orders:checkout", args=[draft.slug]),
        ):
            assert client.get(url).status_code == 404, url


class TestOrganizerIsolation:
    @pytest.fixture
    def rival(self, db):
        return OrganizerFactory()

    def test_rival_organizer_cannot_touch_another_event(self, client, rival, event, victim_order):
        _login(client, rival.user)
        slug = event.slug
        assert client.get(reverse("organizers:event", args=[slug])).status_code == 404
        assert client.get(reverse("organizers:event_edit", args=[slug])).status_code == 404
        assert client.get(reverse("organizers:attendees_csv", args=[slug])).status_code == 404
        assert client.post(reverse("organizers:scanner_add", args=[slug]), {"email": rival.user.email}).status_code == 404
        assert client.post(reverse("organizers:order_refund", args=[slug, victim_order.reference]), {"reason": "x"}).status_code == 404
        assert not ScannerAccess.objects.filter(event=event).exists()
        assert not victim_order.refunds.exists()

    def test_pending_organizer_has_no_dashboard(self, client):
        pending = OrganizerFactory(status=OrganizerProfile.Status.PENDING_REVIEW)
        _login(client, pending.user)
        response = client.get(reverse("organizers:dashboard"))
        assert response.status_code == 302 and reverse("organizers:apply") in response["Location"]
        assert client.get(reverse("organizers:event_new")).status_code == 302

    def test_cannot_edit_another_events_ticket_type_through_the_formset(self, client, organizer, event, ticket_type, rival):
        rival_event = EventFactory(organizer=rival)
        rival_tt = TicketTypeFactory(event=rival_event, name="Rival VIP", price="900.00")
        _login(client, organizer.user)
        data = {
            "title_en": event.title, "starts_at": event.starts_at.strftime("%Y-%m-%dT%H:%M"),
            "categories": [], "venue_name_en": "Hall", "max_tickets_per_order": 10, "action": "draft",
            "tt-TOTAL_FORMS": "1", "tt-INITIAL_FORMS": "1", "tt-MIN_NUM_FORMS": "0", "tt-MAX_NUM_FORMS": "1000",
            "tt-0-id": str(rival_tt.pk), "tt-0-event": str(event.pk), "tt-0-name_en": "Hijacked", "tt-0-price": "1",
            "tt-0-stock": "5", "tt-0-max_per_order": "", "tt-0-is_available": "on",
        }
        client.post(reverse("organizers:event_edit", args=[event.slug]), data)
        rival_tt.refresh_from_db()
        assert rival_tt.name == "Rival VIP" and str(rival_tt.price) == "900.00" and rival_tt.event_id == rival_event.pk

    def test_gate_staff_of_one_event_cannot_check_in_another(self, client, organizer, victim_order, rival):
        other_event = EventFactory(organizer=rival)
        staff = UserFactory()
        ScannerAccess.objects.create(event=other_event, user=staff)
        _login(client, staff)
        ticket = victim_order.tickets.get()
        # Not allowed on the victim's event at all…
        url = reverse("scan:redeem", args=[victim_order.event.slug])
        assert client.post(url, {"code": ticket.code}, content_type="application/json").status_code == 403
        # …and on their own event the foreign ticket is rejected and stays valid.
        response = client.post(reverse("scan:redeem", args=[other_event.slug]), {"code": ticket.token}, content_type="application/json")
        assert response.json()["result"] == "wrong_event"
        ticket.refresh_from_db()
        assert ticket.status == Ticket.Status.VALID

    def test_plain_buyer_cannot_open_a_scanner(self, client, attacker, event):
        _login(client, attacker)
        assert client.get(reverse("scan:event", args=[event.slug])).status_code == 404


# --- 2. Checkout & payment tampering ---------------------------------------------------
class TestCheckoutTampering:
    def test_ticket_type_from_another_event_is_ignored(self, client, attacker, event, ticket_type):
        cheap_elsewhere = TicketTypeFactory(event=EventFactory(), price="1.00")
        _login(client, attacker)
        response = client.get(reverse("orders:checkout", args=[event.slug]) + f"?q_{cheap_elsewhere.pk}=1")
        assert response.status_code == 302  # nothing valid selected → back to the event
        assert not Order.objects.filter(user=attacker).exists()

    def test_quantity_limits_and_junk_values(self, client, attacker, event, ticket_type, settings):
        settings.ALLOW_MOCK_PAYMENTS = True
        PaymentProviderSetting.objects.filter(provider="mock").update(is_enabled=True)
        _login(client, attacker)
        base = {"buyer_name": "A", "buyer_phone": "01711111111", "delivery_email": attacker.email,
                "payment_method": "mock", "agree": "on"}
        for qty in ("-1", "0", "1e3", "abc", "999999"):
            client.post(reverse("orders:checkout", args=[event.slug]), {**base, f"q_{ticket_type.pk}": qty})
        orders = Order.objects.filter(user=attacker)
        assert all(sum(i.quantity for i in o.items.all()) <= ticket_type.effective_max_per_order for o in orders)

    def test_price_comes_from_the_server(self, client, attacker, event, ticket_type, settings):
        settings.ALLOW_MOCK_PAYMENTS = True
        PaymentProviderSetting.objects.filter(provider="mock").update(is_enabled=True)
        _login(client, attacker)
        client.post(reverse("orders:checkout", args=[event.slug]), {
            f"q_{ticket_type.pk}": "1", "price": "1", "total": "1", "unit_price": "1", "subtotal": "1",
            "buyer_name": "A", "buyer_phone": "01711111111", "delivery_email": attacker.email,
            "payment_method": "mock", "agree": "on",
        })
        order = Order.objects.get(user=attacker)
        assert order.subtotal == Decimal(str(ticket_type.price))

    def test_fake_gateway_is_off_on_the_live_site(self, client, attacker, event, ticket_type, settings):
        settings.DEBUG = False
        settings.ALLOW_MOCK_PAYMENTS = False
        PaymentProviderSetting.objects.filter(provider="mock").update(is_enabled=True)  # even if enabled by mistake
        order = start_checkout(**checkout_kwargs(attacker, event, {ticket_type.pk: 1}))
        attempt = new_attempt(order, Provider.MOCK)
        assert client.get(reverse("payments:mock_gateway", args=[attempt.tran_id])).status_code == 404
        client.get(reverse("payments:return", args=["mock"]) + f"?tran_id={attempt.tran_id}&outcome=success")
        order.refresh_from_db()
        assert order.status == Order.Status.PENDING_PAYMENT

    def test_fake_gateway_cannot_settle_a_real_providers_payment(self, client, attacker, event, ticket_type, settings):
        """Where the test gateway is allowed (staging), it must not mark a bKash/card attempt as paid."""
        settings.ALLOW_MOCK_PAYMENTS = True
        order = start_checkout(**checkout_kwargs(attacker, event, {ticket_type.pk: 1}))
        attempt = new_attempt(order, Provider.BKASH)
        client.get(reverse("payments:return", args=["mock"]) + f"?tran_id={attempt.tran_id}&outcome=success")
        attempt.refresh_from_db()
        order.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.INITIATED
        assert order.status == Order.Status.PENDING_PAYMENT

    def test_forged_ipn_is_rejected(self, client, attacker, event, ticket_type):
        order = start_checkout(**checkout_kwargs(attacker, event, {ticket_type.pk: 1}))
        attempt = new_attempt(order, Provider.SSLCOMMERZ)
        PaymentProviderSetting.objects.filter(provider="sslcommerz").update(is_enabled=True)
        response = client.post(reverse("payments:ipn", args=["sslcommerz"]),
                               {"tran_id": attempt.tran_id, "status": "VALID", "amount": str(order.total)})
        assert response.status_code == 400
        order.refresh_from_db()
        assert order.status == Order.Status.PENDING_PAYMENT


# --- 3. Script injection (XSS) ---------------------------------------------------------
XSS = '<script>alert(1)</script><img src=x onerror=alert(2)><a href="javascript:alert(3)">x</a><svg onload=alert(4)>'


class TestScriptInjection:
    def test_rich_text_is_sanitized(self, client, organizer):
        event = EventFactory(organizer=organizer, description=XSS, terms_and_conditions=XSS)
        TicketTypeFactory(event=event)
        html = client.get(event.get_absolute_url()).content.decode()
        for bad in ("<script>alert(1)", "onerror=", "javascript:alert", "onload="):
            assert bad not in html, bad

    def test_title_cannot_break_out_of_json_ld_or_alpine(self, client, organizer):
        title = "</script><script>alert(1)</script><!--<script>' \" `"
        event = EventFactory(organizer=organizer, title=title)
        TicketTypeFactory(event=event)
        html = client.get(event.get_absolute_url()).content.decode()
        assert "</script><script>alert(1)" not in html
        assert "<!--<script>" not in html
        ld = html.split('<script type="application/ld+json">', 1)[1].split("</script>", 1)[0]
        assert "<" not in ld.replace("\\u003c", "")

    def test_names_are_escaped_where_organizers_see_them(self, client, organizer, event, ticket_type):
        buyer = UserFactory(full_name='<img src=x onerror=alert(1)>')
        _paid_order(buyer, event, ticket_type, buyer_name='<img src=x onerror=alert(1)>')
        _login(client, organizer.user)
        html = client.get(reverse("organizers:event", args=[event.slug])).content.decode()
        assert "<img src=x onerror" not in html

    def test_search_term_is_escaped(self, client):
        html = client.get(reverse("events:catalog") + '?q="><script>alert(1)</script>').content.decode()
        assert "<script>alert(1)</script>" not in html

    def test_site_text_override_cannot_inject_attributes(self, client):
        row = SiteText.objects.filter(msgid="Search events…").first() or SiteText.objects.filter(msgid__startswith="Search").first()
        assert row is not None
        row.text_en = 'x" autofocus onfocus="alert(1)'
        row.full_clean()
        row.save()
        html = client.get("/").content.decode()
        assert 'onfocus="alert(1)"' not in html

    def test_site_text_written_outside_the_admin_is_also_neutralized(self, client):
        from apps.cms.sitetext import bump_version

        row = SiteText.objects.filter(msgid="Search events…").first() or SiteText.objects.filter(msgid__startswith="Search").first()
        SiteText.objects.filter(pk=row.pk).update(text_en="&quot; autofocus onfocus=&quot;alert(1)")
        bump_version()
        html = client.get("/").content.decode()
        assert "onfocus=&quot;alert(1)" not in html and 'onfocus="alert(1)"' not in html


# --- 4. Spreadsheet formula injection ---------------------------------------------------
def test_attendee_csv_neutralizes_formulas(client, organizer, event, ticket_type):
    buyer = UserFactory()
    _paid_order(buyer, event, ticket_type, buyer_name='=HYPERLINK("http://evil.example","Click")')
    _login(client, organizer.user)
    body = client.get(reverse("organizers:attendees_csv", args=[event.slug])).content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(body)))
    cells = [cell for row in rows[1:] for cell in row]
    assert not any(cell[:1] in ("=", "+", "-", "@", "\t", "\r") for cell in cells), cells


def test_admin_csv_export_neutralizes_formulas(client, event, ticket_type):
    from apps.core.admin_utils import csv_safe

    assert csv_safe("=1+1") == "'=1+1"
    assert csv_safe("+8801711111111") == "'+8801711111111"
    assert csv_safe("Normal") == "Normal"
    assert csv_safe(42) == 42


# --- 5. Logins ---------------------------------------------------------------------------
class TestLogins:
    def test_admin_login_is_throttled(self, client, settings):
        settings.RATELIMIT_ENABLE = True
        admin_user = UserFactory(is_staff=True, is_superuser=True)
        url = reverse("admin:login")
        codes = [client.post(url, {"username": admin_user.email, "password": f"wrong-{i}"}).status_code for i in range(12)]
        assert 429 in codes
        # Even the right password is refused while throttled.
        assert client.post(url, {"username": admin_user.email, "password": "pass12345!"}).status_code == 429

    def test_login_redirect_stays_on_site(self, client, buyer):
        response = client.post(reverse("account_login") + "?next=https://evil.example/steal",
                               {"login": buyer.email, "password": "pass12345!"})
        assert response.status_code == 302
        assert "evil.example" not in response["Location"]

    def test_password_reset_does_not_reveal_accounts(self, client, buyer):
        known = client.post(reverse("account_reset_password"), {"email": buyer.email})
        unknown = client.post(reverse("account_reset_password"), {"email": "nobody-here@example.com"})
        assert known.status_code == unknown.status_code
        assert known.get("Location") == unknown.get("Location")

    def test_forms_require_csrf(self, buyer, event, ticket_type):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(buyer)
        assert strict.post(reverse("support:contact"), {"name": "x"}).status_code == 403
        assert strict.post(reverse("accounts:profile"), {"full_name": "x"}).status_code == 403


# --- 6. Mass assignment ------------------------------------------------------------------
class TestMassAssignment:
    def test_profile_cannot_grant_staff(self, client, buyer):
        _login(client, buyer)
        client.post(reverse("accounts:profile"), {
            "full_name": "Me", "phone": "01722222222", "preferred_language": "en",
            "is_staff": "on", "is_superuser": "on", "email": "takeover@example.com",
        })
        buyer.refresh_from_db()
        assert not buyer.is_staff and not buyer.is_superuser and buyer.email != "takeover@example.com"

    def test_organizer_cannot_approve_themselves_or_set_fees(self, client, attacker):
        _login(client, attacker)
        client.post(reverse("organizers:apply"), {
            "name": "Sneaky", "organization_type": "individual", "contact_email": attacker.email,
            "contact_phone": "01733333333", "application_note": "x",
            "status": "approved", "commission_pct": "0", "buyer_fee_pct": "0", "can_issue_refunds": "on",
        })
        profile = OrganizerProfile.objects.get(user=attacker)
        assert profile.status == OrganizerProfile.Status.PENDING_REVIEW
        assert profile.commission_pct is None and not profile.can_issue_refunds

    def test_organizer_cannot_feature_their_event(self, client, organizer, event, ticket_type):
        _login(client, organizer.user)
        client.post(reverse("organizers:event_edit", args=[event.slug]), {
            "title_en": event.title, "starts_at": event.starts_at.strftime("%Y-%m-%dT%H:%M"),
            "featured": "on", "status": "on_sale", "organizer": "999",
        })
        event.refresh_from_db()
        assert not event.featured and event.organizer_id == organizer.pk


# --- 7. Uploads -------------------------------------------------------------------------
class TestUploads:
    def _apply(self, client, user, upload):
        _login(client, user)
        return client.post(reverse("organizers:apply"), {
            "name": "Doc Test", "organization_type": "individual", "contact_email": user.email,
            "contact_phone": "01744444444", "application_note": "x", "verification_document": upload,
        })

    def test_verification_document_rejects_html(self, client, attacker):
        self._apply(client, attacker, SimpleUploadedFile("license.html", b"<script>alert(1)</script>", "text/html"))
        assert not OrganizerProfile.objects.filter(user=attacker).exists()

    def test_verification_document_rejects_disguised_html(self, client, attacker):
        self._apply(client, attacker, SimpleUploadedFile("license.pdf", b"<html><script>alert(1)</script>", "application/pdf"))
        assert not OrganizerProfile.objects.filter(user=attacker).exists()

    def test_verification_document_accepts_a_real_pdf(self, client, attacker):
        self._apply(client, attacker, SimpleUploadedFile("license.pdf", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF", "application/pdf"))
        assert OrganizerProfile.objects.filter(user=attacker).exists()

    def test_image_pixel_bombs_are_refused(self):
        from django.core.exceptions import ValidationError
        from PIL import Image

        from apps.core.security import check_image_size

        bomb = io.BytesIO()
        Image.new("1", (8000, 6000)).save(bomb, "PNG")  # 48 MP in a few kB
        upload = SimpleUploadedFile("banner.png", bomb.getvalue(), "image/png")
        with pytest.raises(ValidationError):
            check_image_size(upload, max_mb=8)
        assert Image.MAX_IMAGE_PIXELS <= 60_000_000

    def test_private_documents_need_staff(self, client, attacker):
        url = reverse("private_media", args=["organizers/1/doc.pdf"])
        assert client.get(url).status_code == 302
        _login(client, attacker)
        assert client.get(url).status_code == 302
        _login(client, UserFactory(is_staff=True))
        assert client.get(reverse("private_media", args=["../../.env"])).status_code == 404


# --- 8. Staff roles ---------------------------------------------------------------------
class TestStaffRoles:
    def _member(self, role):
        ensure_staff_roles()
        user = UserFactory(is_staff=True)
        user.groups.add(Group.objects.get(name=role))
        return user

    def test_content_editor_cannot_reach_people_or_money(self, client):
        _login(client, self._member("Content editor"))
        for name in ("accounts_user_changelist", "payments_refund_changelist", "payments_paymentprovidersetting_changelist",
                     "orders_order_changelist", "auth_group_changelist"):
            assert client.get(reverse(f"admin:{name}")).status_code == 403, name

    def test_content_editor_cannot_change_fees(self, client):
        _login(client, self._member("Content editor"))
        site = SiteSettings.load()
        url = reverse("admin:cms_sitesettings_change", args=[site.pk])
        html = client.get(url).content.decode()
        assert 'name="default_commission_pct"' not in html
        assert 'name="hold_minutes"' not in html

    def test_support_agent_cannot_make_themselves_superuser(self, client):
        agent = self._member("Support agent")
        _login(client, agent)
        client.post(reverse("admin:accounts_user_change", args=[agent.pk]), {"is_superuser": "on", "email": agent.email})
        agent.refresh_from_db()
        assert not agent.is_superuser


# --- 9. Headers & caching -----------------------------------------------------------------
def test_security_headers(client):
    response = client.get("/")
    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"]
    assert response["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "camera=(self)" in response["Permissions-Policy"]


def test_edge_cached_pages_hold_nothing_personal(client, buyer, event, ticket_type):
    _login(client, buyer)
    for url in ("/", reverse("events:catalog"), event.get_absolute_url()):
        response = client.get(url)
        html = response.content.decode()
        assert "public" in response.get("Cache-Control", ""), url
        assert buyer.email not in html and "csrfmiddlewaretoken" not in html, url
    nav = client.get(reverse("cms:nav"))
    assert "no-store" in nav["Cache-Control"] and "private" in nav["Cache-Control"]


# --- 10. More hardening ---------------------------------------------------------------------
def test_plain_http_visitors_are_redirected_to_https(client, settings):
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    cloudflare = {"REMOTE_ADDR": "172.64.1.1"}
    # The origin hop is https, but the visitor typed http:// — Cloudflare says so in CF-Visitor.
    response = client.get("/", HTTP_X_FORWARDED_PROTO="https", HTTP_CF_VISITOR='{"scheme":"http"}', **cloudflare)
    assert response.status_code == 301 and response["Location"].startswith("https://")
    assert client.get("/", HTTP_X_FORWARDED_PROTO="https", HTTP_CF_VISITOR='{"scheme":"https"}', **cloudflare).status_code == 200
    # Nobody else can spoof the header.
    spoof = client.get("/", HTTP_X_FORWARDED_PROTO="https", HTTP_CF_VISITOR='{"scheme":"http"}', REMOTE_ADDR="203.0.113.9")
    assert spoof.status_code == 200


def test_spoofed_cloudflare_ip_header_is_ignored(rf):
    from apps.core.cloudflare import CloudflareRealIPMiddleware

    seen = {}
    middleware = CloudflareRealIPMiddleware(lambda request: seen.setdefault("ip", request.META["REMOTE_ADDR"]))
    middleware(rf.get("/", HTTP_CF_CONNECTING_IP="1.2.3.4", REMOTE_ADDR="203.0.113.9"))
    assert seen["ip"] == "203.0.113.9"


@pytest.mark.parametrize("svg", [
    b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"><rect/></a></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><iframe src="https://evil.example"/></foreignObject></svg>',
])
def test_scripted_svg_logos_are_refused(svg):
    from django.core.exceptions import ValidationError

    from apps.core.security import validate_artwork

    with pytest.raises(ValidationError):
        validate_artwork(SimpleUploadedFile("logo.svg", svg, "image/svg+xml"))


def test_plain_svg_logo_is_fine():
    from apps.core.security import validate_artwork

    validate_artwork(SimpleUploadedFile("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h10v10z" fill="#fff"/></svg>'))


def test_artwork_must_be_an_image():
    from django.core.exceptions import ValidationError

    from apps.core.security import validate_artwork

    with pytest.raises(ValidationError):
        validate_artwork(SimpleUploadedFile("logo.html", b"<html></html>", "text/html"))


def test_renditions_skip_oversized_images(tmp_path, settings):
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    from PIL import Image

    from apps.core.images import build_renditions

    settings.MEDIA_ROOT = str(tmp_path)
    bomb = io.BytesIO()
    Image.new("1", (8000, 6000)).save(bomb, "PNG")
    name = default_storage.save("bomb.png", ContentFile(bomb.getvalue()))

    class Stored:
        def __init__(self):
            self.name = name
            self._f = None

        def __bool__(self):
            return True

        def open(self, mode="rb"):
            self._f = default_storage.open(name, mode)

        def read(self, *a):
            return self._f.read(*a)

        def seek(self, *a):
            return self._f.seek(*a)

        def tell(self):
            return self._f.tell()

        def close(self):
            self._f.close()

    assert build_renditions(Stored()) == {}


def test_ticket_type_with_unpaid_orders_cannot_be_deleted(client, organizer, event, ticket_type, attacker):
    start_checkout(**checkout_kwargs(attacker, event, {ticket_type.pk: 1}))  # a pending hold
    _login(client, organizer.user)
    data = {
        "title_en": event.title, "starts_at": event.starts_at.strftime("%Y-%m-%dT%H:%M"),
        "venue_name_en": "Hall", "max_tickets_per_order": 10, "action": "draft",
        "categories": [EventFactory._meta.model.categories.field.related_model.objects.first().pk],
        "tt-TOTAL_FORMS": "2", "tt-INITIAL_FORMS": "1", "tt-MIN_NUM_FORMS": "0", "tt-MAX_NUM_FORMS": "1000",
        "tt-0-id": str(ticket_type.pk), "tt-0-name_en": ticket_type.name, "tt-0-price": "500", "tt-0-stock": "10",
        "tt-0-is_available": "on", "tt-0-DELETE": "on",
        "tt-1-name_en": "New", "tt-1-price": "100", "tt-1-stock": "5", "tt-1-is_available": "on",
    }
    response = client.post(reverse("organizers:event_edit", args=[event.slug]), data)
    assert response.status_code == 200  # form shown again with the error, no crash
    assert type(ticket_type).objects.filter(pk=ticket_type.pk).exists()


def test_staff_cannot_edit_a_superuser_account(client):
    ensure_staff_roles()
    boss = UserFactory(is_staff=True, is_superuser=True)
    helper = UserFactory(is_staff=True)
    from django.contrib.auth.models import Permission

    helper.user_permissions.add(*Permission.objects.filter(codename__in=["change_user", "view_user"]))
    _login(client, helper)
    client.post(reverse("admin:accounts_user_change", args=[boss.pk]), {"email": "hijack@example.com"})
    boss.refresh_from_db()
    assert boss.email != "hijack@example.com"
    html = client.get(reverse("admin:accounts_user_change", args=[helper.pk])).content.decode()
    assert 'name="is_superuser"' not in html


class TestPrivilegedSettings:
    def _member(self, role):
        ensure_staff_roles()
        user = UserFactory(is_staff=True)
        user.groups.add(Group.objects.get(name=role))
        return user

    def test_content_editor_cannot_reroute_site_mail(self, client):
        _login(client, self._member("Content editor"))
        site = SiteSettings.load()
        url = reverse("admin:cms_sitesettings_change", args=[site.pk])
        html = client.get(url).content.decode()
        for field in ("email_host", "email_username", "email_password", "email_from_address"):
            assert f'name="{field}"' not in html, field

    def test_finance_cannot_change_merchant_credentials_or_sandbox(self, client):
        finance = self._member("Finance")
        _login(client, finance)
        setting = PaymentProviderSetting.objects.get(provider="bkash")
        setting.is_sandbox = False
        setting.save()
        url = reverse("admin:payments_paymentprovidersetting_change", args=[setting.pk])
        html = client.get(url).content.decode()
        assert 'name="cred_app_key"' not in html and 'name="clear_credentials"' not in html
        before = setting.credentials_encrypted if hasattr(setting, "credentials_encrypted") else None
        client.post(url, {"display_name_en": "bKash", "display_name_bn": "বিকাশ", "is_enabled": "on",
                          "is_sandbox": "on", "sort_order": "1", "brand_color": "#E2136E",
                          "cred_app_key": "attacker", "clear_credentials": "on"})
        setting.refresh_from_db()
        assert not setting.is_sandbox
        assert setting.get_credentials().get("app_key") != "attacker"
        if before is not None:
            assert setting.credentials_encrypted == before

    def test_superuser_still_manages_everything(self, client):
        _login(client, UserFactory(is_staff=True, is_superuser=True))
        site = SiteSettings.load()
        html = client.get(reverse("admin:cms_sitesettings_change", args=[site.pk])).content.decode()
        assert 'name="email_host"' in html and 'name="default_commission_pct"' in html and 'name="email_password"' in html
        setting = PaymentProviderSetting.objects.get(provider="bkash")
        html = client.get(reverse("admin:payments_paymentprovidersetting_change", args=[setting.pk])).content.decode()
        assert 'name="cred_app_key"' in html


def test_demo_organizer_has_no_known_password(db):
    import importlib

    from django.apps import apps as django_apps
    from django.core.management import call_command

    call_command("seed_demo")
    demo = UserFactory._meta.model.objects.get(email="demo-organizer@nexopay.com.bd")
    assert not demo.check_password("demo12345!") and not demo.has_usable_password()

    # An account left over from an older seed is locked by the migration.
    demo.set_password("demo12345!")
    demo.save()
    importlib.import_module("apps.accounts.migrations.0002_lock_demo_organizer").lock(django_apps, None)
    demo.refresh_from_db()
    assert not demo.check_password("demo12345!")


def test_deploy_checks_block_the_test_gateway_on_the_live_site(settings):
    from apps.core.checks import nexopay_deploy_checks

    settings.DEBUG = False
    settings.SECRET_KEY = "k3J#9xq!Lm2$Vb7@Zr5^Tn8&Wc4*Yp6("
    settings.SITE_URL = "https://nexopay.com.bd"
    settings.ALLOW_MOCK_PAYMENTS = True
    assert "nexopay.E002" in {issue.id for issue in nexopay_deploy_checks(None)}
    settings.SITE_URL = "https://new.nexopay.com.bd"  # staging may demo the test gateway
    assert "nexopay.E002" not in {issue.id for issue in nexopay_deploy_checks(None)}
    settings.SECRET_KEY = "dev-insecure-key-change-me"
    assert "nexopay.E001" in {issue.id for issue in nexopay_deploy_checks(None)}
