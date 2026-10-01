"""Word-by-word text reveals: |split_words wraps words safely and pages render them."""
import pytest
from django.urls import reverse

from apps.core.templatetags.nexo import highlight, split_words

from .factories import EventFactory, TicketTypeFactory

pytestmark = pytest.mark.django_db


def test_split_words_escapes_plain_text():
    html = split_words('<img src=x onerror=alert(1)> & "quotes"')
    assert "<img" not in html and "&lt;img" in html and "&amp;" in html
    assert html.count('class="sw-i"') == 5


def test_split_words_keeps_highlight_spans_and_numbers_words():
    html = split_words(highlight("Tickets to *everything* worth going to."))
    assert '<span class="text-hl"><span class="sw"><span class="sw-i" style="--wi:2">everything</span></span></span>' in html
    assert 'style="--wi:5">to.</span>' in html


def test_bangla_words_stay_whole():
    html = split_words("খুঁজে নিন আপনার পরের অভিজ্ঞতা")
    assert html.count('class="sw-i"') == 5 and "অভিজ্ঞতা</span>" in html


def test_pages_render_word_reveals(client):
    event = EventFactory(title="Night <b>Market</b>")
    TicketTypeFactory(event=event)
    for url, cls in (("/", "words-in"), ("/events/", "words-in"), (event.get_absolute_url(), "words-in"), ("/faq/", "words-in")):
        html = client.get(url).content.decode()
        assert f'class="{cls}' in html and 'class="sw-i"' in html, url
    assert "Night <b>Market" not in client.get(event.get_absolute_url()).content.decode()
