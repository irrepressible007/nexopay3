"""Control room upgrade: site-wide options take effect, admin tools work, roles and menu behave."""
import csv
import io

import pytest
from django.contrib.auth.models import Group
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.cms.models import HomeSection, SiteSettings
from apps.events.models import Event

from .factories import EventFactory, TicketTypeFactory, UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_settings():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def _site(**changes):
    site = SiteSettings.load()
    for k, v in changes.items():
        setattr(site, k, v)
    site.save()
    return site


def _home(client):
    return client.get("/").content.decode()


class TestSiteOptions:
    def test_header_button_search_and_language_switch(self, client):
        _site(header_cta_label_en="List your event", header_cta_url="/organizers/apply/",
              show_header_search=False, show_language_switch=False)
        html = _home(client)
        assert "List your event" in html and 'href="/organizers/apply/"' in html
        assert 'class="w-56 rounded-full' not in html  # header search box
        assert 'hreflang="bn" title=' not in html  # language switch

    def test_motion_level_and_system_font(self, client):
        _site(motion_level="off", font_choice="system")
        html = _home(client)
        assert 'class="motion-off"' in html
        assert "reveal-ready" not in html  # no scroll reveals at all
        assert "Satoshi-Variable.woff2" not in html and "--font-sans:ui-sans-serif" in html

    def test_tracking_codes_only_when_set(self, client):
        assert "googletagmanager" not in _home(client)
        _site(google_analytics_id="G-ABC123XYZ", meta_pixel_id="123456789012", google_site_verification="abc")
        html = _home(client)
        assert "gtag/js?id=G-ABC123XYZ" in html and 'fbq("init","123456789012")' in html
        assert 'name="google-site-verification" content="abc"' in html

    def test_tracking_ids_are_validated(self):
        from django.core.exceptions import ValidationError

        site = SiteSettings.load()
        site.google_analytics_id = "UA-1234"
        with pytest.raises(ValidationError):
            site.full_clean()

    def test_custom_css_cannot_close_the_style_tag(self, client):
        _site(custom_css="body{color:red}</style><script>alert(1)</script>")
        html = _home(client)
        assert "body{color:red}<\\/style><script>" in html
        assert "</style><script>alert(1)" not in html

    def test_announcement_schedule_style_and_dismiss_key(self, client):
        site = _site(announcement_enabled=True, announcement_text_en="Early bird ends tonight",
                     announcement_style="accent", announcement_starts_at=timezone.now() + timezone.timedelta(days=1))
        assert "Early bird ends tonight" not in _home(client)  # not started yet
        site.announcement_starts_at = None
        site.save()
        html = _home(client)
        assert "Early bird ends tonight" in html and "bg-accent text-on-accent" in html
        assert f"announcement('{site.announcement_key}')" in html
        key = site.announcement_key
        site.announcement_text_en = "Something new"
        site.save()
        assert SiteSettings.load().announcement_key != key  # a new announcement shows again

    def test_hero_text_mode_hides_posters(self, client):
        EventFactory(featured=True, banner="events/poster.jpg")
        assert 'class="poster-card' in _home(client)
        _site(hero_mode="text")
        assert 'class="poster-card' not in _home(client)

    def test_section_shown_on_phones_only(self, client):
        section = HomeSection.objects.get(kind="faq")
        section.show_on = "phones"
        section.save()
        assert "sm:hidden" in _home(client)

    def test_event_page_switches(self, client, event, ticket_type):
        other = EventFactory(organizer=event.organizer)
        other.categories.set(event.categories.all())
        _site(show_calendar_buttons=False, show_share_buttons=False, show_organizer_contact=False,
              related_events_count=0)
        html = client.get(event.get_absolute_url()).content.decode()
        assert "Google Calendar" not in html and "wa.me/?text" not in html
        assert "mailto:" + event.organizer.contact_email not in html
        assert "You might also like" not in html

    def test_maintenance_message(self, client):
        _site(maintenance_mode=True, maintenance_message_en="Back at 9 pm with new events")
        assert "Back at 9 pm with new events" in _home(client)

    def test_stale_cached_settings_reload(self):
        from django.core.cache import cache

        from apps.cms.models import SITE_SETTINGS_CACHE_KEY

        site = SiteSettings.load()
        del site.__dict__["motion_level"]  # as if cached before the field existed
        cache.set(SITE_SETTINGS_CACHE_KEY, site, 60)
        assert SiteSettings.load().motion_level == "full"


class TestAdminTools:
    @pytest.fixture
    def admin_client(self, client):
        client.force_login(UserFactory(is_staff=True, is_superuser=True))
        return client

    def test_screens_open(self, admin_client, event, ticket_type):
        for url in ["/control-room/", "/control-room/events/event/", f"/control-room/events/event/{event.pk}/change/",
                    "/control-room/events/category/", "/control-room/orders/order/", "/control-room/tickets/ticket/",
                    "/control-room/accounts/user/?role=buyer", "/control-room/auth/group/",
                    "/control-room/support/contactmessage/", "/control-room/cms/homesection/",
                    "/control-room/cms/faqitem/", "/control-room/cms/page/", "/control-room/tickets/scanlog/",
                    reverse("admin:cms_sitesettings_change", args=[SiteSettings.load().pk])]:
            assert admin_client.get(url).status_code == 200, url

    def test_csv_export(self, admin_client, event, ticket_type):
        response = admin_client.post(reverse("admin:events_event_changelist"),
                                     {"action": "export_csv", "_selected_action": [event.pk]})
        assert response["Content-Type"].startswith("text/csv")
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        assert rows[0][0] == "Title" and rows[1][0] == event.title

    def test_duplicate_event_is_a_hidden_draft_with_its_tickets(self, admin_client, event, ticket_type):
        ticket_type.sold_count = 5
        ticket_type.save()
        admin_client.post(reverse("admin:events_event_changelist"), {"action": "duplicate", "_selected_action": [event.pk]})
        copy = Event.objects.exclude(pk=event.pk).get(slug__startswith=f"{event.slug}-copy")
        assert copy.status == Event.Status.DRAFT and not copy.featured
        assert copy.title_en.endswith("(copy)") and not copy.title_en.endswith("(copy) (copy)")
        assert [t.name for t in copy.ticket_types.all()] == [ticket_type.name]
        assert copy.ticket_types.get().sold_count == 0
        assert set(copy.categories.all()) == set(event.categories.all())

    def test_put_on_sale_action(self, admin_client, organizer):
        draft = EventFactory(organizer=organizer, status=Event.Status.DRAFT)
        admin_client.post(reverse("admin:events_event_changelist"), {"action": "put_on_sale", "_selected_action": [draft.pk]})
        draft.refresh_from_db()
        assert draft.status == Event.Status.ON_SALE and draft.published_at

    def test_custom_css_is_superuser_only(self, client):
        staff = UserFactory(is_staff=True)
        staff.user_permissions.add(*__import__("django.contrib.auth.models", fromlist=["Permission"]).Permission.objects
                                   .filter(codename__in=["view_sitesettings", "change_sitesettings"]))
        client.force_login(staff)
        from django.contrib import admin

        model_admin = admin.site._registry[SiteSettings]
        request = RequestFactory().get("/")
        request.user = staff
        assert "custom_css" in model_admin.get_readonly_fields(request, SiteSettings.load())


class TestRolesAndMenu:
    def test_ready_made_roles_exist(self):
        names = set(Group.objects.values_list("name", flat=True))
        assert {"Content editor", "Event manager", "Support agent", "Finance"} <= names
        assert Group.objects.get(name="Support agent").permissions.filter(codename="view_contactmessage").exists()
        assert not Group.objects.get(name="Support agent").permissions.filter(codename="change_paymentprovidersetting").exists()

    def test_menu_follows_the_role(self):
        from apps.core.admin_nav import navigation

        agent = UserFactory(is_staff=True)
        agent.groups.add(Group.objects.get(name="Support agent"))
        request = RequestFactory().get("/control-room/")
        request.user = agent
        groups = {g.get("title"): g for g in navigation(request)}
        messages = next(i for i in groups["Support"]["items"] if i["title"] == "Messages")
        methods = next(i for i in groups["Money"]["items"] if i["title"] == "Payment methods")
        assert messages["permission"](request) is True
        assert methods["permission"](request) is False

    def test_counters_only_when_something_waits(self, event):
        from apps.core.admin_nav import navigation
        from apps.support.models import ContactMessage

        request = RequestFactory().get("/control-room/")
        request.user = UserFactory(is_staff=True, is_superuser=True)
        items = {i["title"]: i for g in navigation(request) for i in g["items"]}
        assert "badge" not in items["Messages"]
        ContactMessage.objects.create(reason="feedback", name="Rina", email="rina@example.com", message="Hi")
        items = {i["title"]: i for g in navigation(request) for i in g["items"]}
        assert items["Messages"]["badge"] == 1
