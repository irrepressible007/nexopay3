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


SCROLL_LINKED = {"reveal", "reveal-text", "reveal-pop", "reveal-scale", "words-scroll", "parallax-img"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


TEXT_INPUTS = {None, "text", "email", "search", "tel", "password", "number", "url"}


def scan(html):
    """Walk the page and report (1) scroll-linked reveals sitting inside an `overflow-hidden` box
    (one without the `overflow-clip` upgrade): `hidden` makes the box its own scroll container, so
    the reveal would follow that box instead of the page and freeze part-way; and (2) text fields
    inside something that moves with the scroll (typing into a fading, blurring box feels broken)."""
    from html.parser import HTMLParser

    trapped, typing = [], []

    class Walk(HTMLParser):
        stack = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            classes = set((attrs.get("class") or "").split())
            if classes & SCROLL_LINKED and any(trap for _, trap, _ in self.stack):
                trapped.append(f"<{tag} class={' '.join(sorted(classes & SCROLL_LINKED))}>")
            is_field = (tag == "input" and attrs.get("type") in TEXT_INPUTS) or tag in ("textarea", "select") or "contenteditable" in attrs
            if is_field and any(moving for _, _, moving in self.stack):
                typing.append(f"<{tag} name={attrs.get('name')}>")
            if tag not in VOID:
                trap = "overflow-hidden" in classes and not any(c.endswith("overflow-clip") for c in classes)
                self.stack.append((tag, trap, bool(classes & SCROLL_LINKED)))

        def handle_endtag(self, tag):
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    break

    Walk().feed(html)
    return trapped, typing


def trapped_reveals(html):
    return scan(html)[0]


def typing_in_motion(html):
    return scan(html)[1]


def test_every_home_section_reveals_and_nothing_is_trapped(client):
    from apps.cms.models import HomeSection, Partner

    for i in range(3):
        TicketTypeFactory(event=EventFactory(featured=True, banner=f"org/1/event/{i}/banner.jpg"))
    HomeSection.objects.create(kind="promo_banner", title="Season pass is here", subtitle="One pass.", cta_label="Get yours",
                               image="home/promo.jpg", sort_order=65)
    HomeSection.objects.create(kind="partners", title="Trusted by organizers", sort_order=75)
    Partner.objects.create(name="Acme", logo="partners/acme.png")
    html = client.get("/").content.decode()
    for marker in ('class="reveal-pop cat-pill', 'class="parallax-img', 'class="words-scroll max-w-lg',
                   'class="reveal-text container-x', 'class="reveal-scale relative', 'class="reveal min-w-0',
                   'class="scroll-lift', 'scroll-sink'):
        assert marker in html, marker
    assert trapped_reveals(html) == []


def test_inner_pages_reveal_and_nothing_is_trapped(client):
    event = EventFactory(description="<p>First.</p><p>Second.</p>")
    TicketTypeFactory(event=event)
    for url in (event.get_absolute_url(), "/faq/", "/contact/", "/events/"):
        html = client.get(url).content.decode()
        assert trapped_reveals(html) == [], url
    html = client.get(event.get_absolute_url()).content.decode()
    assert html.count('class="words-scroll') >= 3 and 'class="reveal-scale card' in html
    client.force_login(event.organizer.user)
    for url in ("/organizers/dashboard/", f"/organizers/events/{event.slug}/"):
        html = client.get(url).content.decode()
        assert "reveal-scale" in html and trapped_reveals(html) == [], url


def test_trap_detector_catches_a_hidden_box():
    assert trapped_reveals('<div class="overflow-hidden"><p class="reveal">x</p></div>') == ["<p class=reveal>"]
    assert trapped_reveals('<div class="overflow-hidden supports-[overflow:clip]:overflow-clip"><p class="reveal">x</p></div>') == []
    assert trapped_reveals('<div class="overflow-hidden"><img src="a"></div><p class="reveal">x</p>') == []


def test_text_fields_never_move_with_the_scroll(client):
    from pathlib import Path

    event = EventFactory()
    TicketTypeFactory(event=event)
    pages = ["/", "/events/", event.get_absolute_url(), "/contact/", "/faq/"]
    for url in pages:
        assert typing_in_motion(client.get(url).content.decode()) == [], url
    client.force_login(event.organizer.user)
    for url in ("/organizers/dashboard/", f"/organizers/events/{event.slug}/", f"/organizers/events/{event.slug}/edit/"):
        response = client.get(url)
        assert response.status_code == 200, url
        assert typing_in_motion(response.content.decode()) == [], url
    # The event editor's typing area is .prose-nx: its paragraphs must not get the prose reveal.
    css = Path(__file__).resolve().parent.parent.joinpath("assets/tailwind/app.css").read_text(encoding="utf-8")
    assert ".prose-nx > *" not in css and ".prose-nx:not([contenteditable], .prose-lead) > *" in css


def test_typing_detector_catches_a_field_in_a_moving_box():
    assert typing_in_motion('<form class="reveal-scale"><input name="q"></form>') == ["<input name=q>"]
    assert typing_in_motion('<form class="reveal"><input type="checkbox" name="c"></form>') == []
    assert typing_in_motion('<div class="reveal"></div><input name="q">') == []


def test_reveals_never_hide_for_good(client):
    """The head script switches reveals on before the first paint and off again if app.js hasn't
    started 2.5 s later, so no block can stay hidden; app.js replays a block that drops below."""
    from pathlib import Path

    html = client.get("/").content.decode()
    assert 'd.classList.add("reveal-ready")' in html and 'd.classList.contains("reveal-live")||d.classList.remove("reveal-ready")' in html
    js = Path(__file__).resolve().parent.parent.joinpath("static/js/app.js").read_text(encoding="utf-8")
    assert 'classList.remove("is-in", "rv-now")' in js and 'root.classList.add("reveal-live")' in js


def test_event_banner_zooms_with_the_scroll(client):
    event = EventFactory(banner="org/1/event/x/banner.jpg")
    TicketTypeFactory(event=event)
    assert 'class="scroll-zoom' in client.get(event.get_absolute_url()).content.decode()
