"""The homepage's right-hand deck fills itself: featured first, then upcoming, else recent past events."""
from datetime import timedelta

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.cms.views import _hero_posters
from apps.events.models import Event

from .factories import EventFactory

pytestmark = pytest.mark.django_db


def with_banner(**kwargs):
    event = EventFactory(**kwargs)
    event.banner.save("poster.png", ContentFile(b"\x89PNG\r\n\x1a\n" + b"0" * 64), save=True)
    return event


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


def test_featured_first_then_soonest_upcoming():
    now = timezone.now()
    later = with_banner(starts_at=now + timedelta(days=30))
    soon = with_banner(starts_at=now + timedelta(days=2))
    star = with_banner(starts_at=now + timedelta(days=60), featured=True)
    EventFactory(starts_at=now + timedelta(days=1))  # no poster image: never in the deck
    with_banner(starts_at=now + timedelta(days=3), status=Event.Status.DRAFT)  # not public
    posters, past = _hero_posters(4, now)
    assert [e.pk for e in posters] == [star.pk, soon.pk, later.pk] and not past


def test_limit_is_respected():
    now = timezone.now()
    for d in range(6):
        with_banner(starts_at=now + timedelta(days=d + 1))
    posters, _ = _hero_posters(4, now)
    assert len(posters) == 4


def test_nothing_upcoming_shows_recent_past_events_as_ended(client):
    now = timezone.now()
    old = with_banner(starts_at=now - timedelta(days=50), status=Event.Status.ENDED, title="STEAM Carnival")
    with_banner(starts_at=now - timedelta(days=500), status=Event.Status.ENDED)  # too long ago
    posters, past = _hero_posters(4, now)
    assert [e.pk for e in posters] == [old.pk] and past
    html = client.get("/").content.decode()
    assert "STEAM Carnival" in html and "Ended" in html and "New events are on the way" in html


def test_no_events_keeps_the_centred_text_hero(client):
    posters, past = _hero_posters(4, timezone.now())
    assert posters == [] and not past
    html = client.get("/").content.decode()
    assert "poster-stack" not in html and "New events are on the way" not in html
