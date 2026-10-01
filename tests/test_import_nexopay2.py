"""Bringing accounts, the past event, pages and partners over from Nexopay 2 (Laravel)."""
import io
import json
from datetime import datetime

import bcrypt
import pytest
from allauth.account.models import EmailAddress
from django.core.management import call_command
from django.urls import reverse
from PIL import Image

from apps.cms.models import Page, Partner
from apps.core.management.commands import import_nexopay2
from apps.events.models import Event

from .factories import UserFactory

pytestmark = pytest.mark.django_db

BCRYPT_FIRST = ["django.contrib.auth.hashers.PBKDF2PasswordHasher", "django.contrib.auth.hashers.BCryptPasswordHasher"]


def laravel_hash(password: str) -> str:
    """What Laravel's Hash::make() stores: bcrypt with the $2y$ prefix."""
    return "$2y$" + bcrypt.hashpw(password.encode(), bcrypt.gensalt(4)).decode()[4:]


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (1200, 630), (90, 40, 200)).save(buf, "PNG")
    return buf.getvalue()


class FakeNexopay2:
    def __init__(self):
        self.files = {"events/covers/steam.png": png_bytes(), "partners/buet.png": png_bytes(),
                      "partners/evil.svg": b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'}
        self._users = [
            {"id": 1, "name": "Rahim Uddin", "email": "Rahim@Example.com", "email_verified_at": datetime(2026, 6, 10),
             "password": laravel_hash("old-secret-1"), "global_role": "user",
             "profile_data": json.dumps({"Phone Number": "01712-345678", "Institution": "BUET"}),
             "created_at": datetime(2026, 6, 10, 8, 0)},
            {"id": 2, "name": "Karim", "email": "karim@example.com", "email_verified_at": None,
             "password": laravel_hash("old-secret-2"), "global_role": "Admin", "profile_data": None,
             "created_at": datetime(2026, 6, 11)},
            {"id": 3, "name": "Already Here", "email": "taken@example.com", "email_verified_at": datetime(2026, 6, 1),
             "password": laravel_hash("x"), "global_role": "user", "profile_data": None, "created_at": datetime(2026, 6, 1)},
            {"id": 4, "name": "Odd Hash", "email": "odd@example.com", "email_verified_at": None,
             "password": "not-a-bcrypt-hash", "global_role": "user", "profile_data": '{"mobile": "12345"}',
             "created_at": datetime(2026, 6, 12)},
        ]
        self._events = [
            {"id": 3, "title": "National STEAM Carnival", "slug": "national-steam-carnival-6a2318de50c6a",
             "description": "<h2>National STEAM Olympiad</h2><p style='color:red'>Prizes <script>x()</script></p>",
             "short_description": "<h1>Segment Details</h1><p>Robotics, Science fair</p>",
             "cover_image": "events/covers/steam.png", "start_date": datetime(2026, 8, 13, 3, 0),
             "end_date": datetime(2026, 8, 15, 12, 0), "status": "upcoming", "created_at": datetime(2026, 6, 4)},
            {"id": 4, "title": "Half-made idea", "slug": "half-made", "description": "", "short_description": "",
             "cover_image": None, "start_date": None, "end_date": None, "status": "draft", "created_at": datetime(2026, 7, 1)},
        ]
        self._pages = [
            {"id": 1, "title": "About Us", "slug": "about-us", "content": "<p>We are Nexopay.</p>", "is_published": 1},
            {"id": 2, "title": "What We Do", "slug": "what-we-do", "content": "<p>Events.</p><img src=x onerror=y>", "is_published": 1},
            {"id": 3, "title": "About", "slug": "about", "content": "<p>Old about</p>", "is_published": 1},
        ]
        self._partners = [
            {"id": 1, "name": "Bangladesh University of Engineering and Technology (BUET)", "logo_image": "partners/buet.png",
             "destination_url": "https://www.buet.ac.bd/web/#/", "is_active": 1},
            {"id": 2, "name": "Ghost", "logo_image": "partners/missing.png", "destination_url": "javascript:alert(1)", "is_active": 1},
            {"id": 3, "name": "Sneaky", "logo_image": "partners/evil.svg", "destination_url": "", "is_active": 1},
        ]

    def users(self):
        return self._users

    def events(self):
        return self._events

    def pages(self):
        return self._pages

    def partners(self):
        return self._partners

    def read_file(self, path):
        return self.files.get(path)


@pytest.fixture
def old_site(monkeypatch, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.PASSWORD_HASHERS = BCRYPT_FIRST
    fake = FakeNexopay2()
    monkeypatch.setattr(import_nexopay2.Command, "get_source", lambda self, options: fake)
    UserFactory(email="taken@example.com", full_name="Kept As Is")
    UserFactory(is_staff=True, is_superuser=True, email="owner@example.com")
    return fake


def run(*args):
    out = io.StringIO()
    call_command("import_nexopay2", *args, stdout=out)
    return out.getvalue()


def test_dry_run_changes_nothing(old_site):
    from apps.accounts.models import User

    before = (User.objects.count(), Event.objects.count(), Page.objects.count(), Partner.objects.count())
    out = run()
    assert "3  accounts" in out and "Nothing was changed" in out
    assert "karim@example.com (Admin)" in out
    assert (User.objects.count(), Event.objects.count(), Page.objects.count(), Partner.objects.count()) == before


def test_accounts_keep_their_passwords_and_verification(old_site, client):
    from apps.accounts.models import User

    run("--yes")
    rahim = User.objects.get(email="rahim@example.com")
    assert rahim.full_name == "Rahim Uddin" and rahim.phone == "+8801712345678"
    assert rahim.password.startswith("bcrypt$$2y$")
    assert EmailAddress.objects.get(user=rahim).verified
    assert not EmailAddress.objects.get(email="karim@example.com").verified
    assert not User.objects.get(email="karim@example.com").is_staff  # old Admin role isn't carried over
    assert not User.objects.get(email="odd@example.com").has_usable_password()
    assert User.objects.get(email="taken@example.com").full_name == "Kept As Is"  # never overwritten

    # The old password works on the new login page, and is re-saved in the new format.
    response = client.post(reverse("account_login"), {"login": "rahim@example.com", "password": "old-secret-1"})
    assert response.status_code == 302
    rahim.refresh_from_db()
    assert rahim.password.startswith("pbkdf2_sha256$")
    client.logout()
    assert client.post(reverse("account_login"), {"login": "rahim@example.com", "password": "wrong"}).status_code == 200


def test_past_event_becomes_an_archive(old_site, client):
    out = run("--yes", "--venue", "BUET, Dhaka")
    event = Event.objects.get(slug="national-steam-carnival-6a2318de50c6a")
    assert event.status == Event.Status.ENDED and event.venue_name == "BUET, Dhaka"
    assert event.starts_at.isoformat().startswith("2026-08-13T03:00:00")  # stored UTC
    assert "<script" not in event.description and "style=" not in event.description
    assert "Segment Details" in event.description
    assert {c.slug for c in event.categories.all()} >= {"competitions", "festivals"}
    assert event.banner and event.banner.name.startswith(f"org/{event.organizer_id}/event/")
    assert event.organizer.user.email == "owner@example.com" and event.organizer.is_approved
    assert not Event.objects.filter(slug="half-made").exists()  # old drafts stay behind
    # The old address now lands on it.
    response = client.get("/event/national-steam-carnival-6a2318de50c6a")
    assert response.status_code == 301 and response["Location"] == event.get_absolute_url()
    assert client.get(event.get_absolute_url()).status_code == 200
    panel = client.get(reverse("events:ticket_panel", args=[event.slug])).content.decode()
    assert "This event has ended" in panel
    assert "Imported 3 accounts, 1 events" in out


def test_without_a_venue_the_page_shows_the_city_not_online(old_site, client):
    run("--yes")
    event = Event.objects.get(slug="national-steam-carnival-6a2318de50c6a")
    assert event.place == "Dhaka"
    assert "Online event" not in client.get(event.get_absolute_url()).content.decode()


def test_pages_and_partners(old_site, client):
    out = run("--yes")
    assert Page.objects.get(slug="about-us").is_published
    assert "<img" not in Page.objects.get(slug="what-we-do").body
    assert Page.objects.get(slug="about").title != "About" or "Old about" not in Page.objects.get(slug="about").body
    assert client.get("/p/about-us").status_code in (200, 301)
    assert client.get("/p/about-us/").status_code == 200
    buet = Partner.objects.get(name__startswith="Bangladesh University")
    assert buet.url == "https://www.buet.ac.bd/web/#/" and buet.logo
    assert not Partner.objects.filter(name__in=["Ghost", "Sneaky"]).exists()
    assert "logo file missing" in out and "Sneaky" in out


def test_running_twice_imports_nothing_new(old_site):
    run("--yes")
    counts = (Event.objects.count(), Page.objects.count(), Partner.objects.count())
    out = run("--yes")
    assert "0  accounts" in out and "Imported 0 accounts, 0 events, 0 pages, 0 partners" in out
    assert (Event.objects.count(), Page.objects.count(), Partner.objects.count()) == counts


def test_laravel_env_parsing(tmp_path):
    env = tmp_path / ".env"
    env.write_text('APP_NAME="Nexopay"\nDB_HOST=127.0.0.1\nDB_PASSWORD="p@ss word#1"\nDB_DATABASE=nexopayc_db # comment\n')
    values = import_nexopay2.read_laravel_env(env)
    assert values["DB_PASSWORD"] == "p@ss word#1" and values["DB_DATABASE"] == "nexopayc_db"


def test_missing_source_env_is_a_clear_error(tmp_path):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="settings file was not found"):
        call_command("import_nexopay2", "--source-env", str(tmp_path / "nope.env"))
