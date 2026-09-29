import json
import re
from decimal import Decimal

from django import template
from django.conf import settings
from django.core.files.storage import default_storage
from django.urls import translate_url
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.translation import get_language

register = template.Library()

_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


@register.filter
def taka(value):
    """1500 → ৳1,500 ; 99.5 → ৳99.50 ; 0 → Free handled by caller."""
    if value in (None, ""):
        return ""
    value = Decimal(value)
    text = f"{value:,.0f}" if value == value.to_integral() else f"{value:,.2f}"
    if get_language() == "bn":
        text = text.translate(_BN_DIGITS)
    return f"৳{text}"


@register.filter
def bn_digits(value):
    text = str(value)
    return text.translate(_BN_DIGITS) if get_language() == "bn" else text


@register.filter
def rendition(renditions, width):
    """URL of the stored WebP rendition closest to `width` (falls back to the largest)."""
    if not renditions:
        return ""
    widths = sorted(int(k) for k in renditions if k.isdigit())
    if not widths:
        return default_storage.url(renditions["src"]) if renditions.get("src") else ""
    target = next((w for w in widths if w >= int(width)), widths[-1])
    return default_storage.url(renditions[str(target)])


@register.filter
def srcset(renditions):
    if not renditions:
        return ""
    return ", ".join(
        f"{default_storage.url(renditions[k])} {k}w" for k in sorted((k for k in renditions if k.isdigit()), key=int)
    )


@register.simple_tag
def icon(name, css="w-5 h-5"):
    return format_html('<svg class="{}" aria-hidden="true"><use href="#i-{}"></use></svg>', css, name)


@register.simple_tag(takes_context=True)
def lang_url(context, code):
    request = context.get("request")
    if not request:
        return "/"
    return translate_url(request.get_full_path(), code)


@register.simple_tag(takes_context=True)
def absolute(context, path):
    return settings.SITE_URL + path


@register.filter
def json_script_safe(value):
    return mark_safe(json.dumps(value, ensure_ascii=False).replace("</", "<\\u002f"))


@register.filter
def is_future(dt):
    return dt and dt > timezone.now()


@register.filter
def get_item(mapping, key):
    return mapping.get(key) if mapping else None


@register.filter
def localize_url(url):
    """Give admin-entered internal links (/events/…) the current language prefix (/bn/events/…)."""
    if not url or not url.startswith("/") or url.startswith("//"):
        return url
    lang = get_language()
    if lang == settings.LANGUAGE_CODE:
        return url
    prefix = f"/{lang}/"
    return url if url.startswith(prefix) or url == f"/{lang}" else f"/{lang}{url}"


@register.simple_tag
def category_icon(category, css="w-5 h-5"):
    """An admin-uploaded icon if present, else the chosen built-in icon."""
    if not hasattr(category, "icon"):  # None / "" when an event has no category yet
        return icon("ticket", css)
    if getattr(category, "icon_image", None):
        return format_html('<img src="{}" alt="" class="{} object-contain" loading="lazy">', category.icon_image.url, css)
    return icon(category.icon or "ticket", css)


_HIGHLIGHT = re.compile(r"\*([^*]+)\*")


@register.filter
def highlight(text):
    """Admins wrap words in *asterisks* to show them in the brand gradient."""
    from django.utils.html import escape

    escaped = escape(text or "")
    return mark_safe(_HIGHLIGHT.sub(r'<span class="text-gradient">\1</span>', escaped))


@register.filter
def reveal_words(text):
    """Like `highlight`, but each word is its own span (with its position in --i) so a headline
    can animate in word by word. Splits on spaces only, so Bangla words stay whole."""
    from django.utils.html import escape

    text, words, pos = text or "", [], 0
    parts = []
    for match in _HIGHLIGHT.finditer(text):
        parts += [(text[pos:match.start()], False), (match.group(1), True)]
        pos = match.end()
    parts.append((text[pos:], False))
    for part, marked in parts:
        for word in part.split():
            css = "word text-gradient" if marked else "word"
            words.append(f'<span class="{css}" style="--i:{len(words)}">{escape(word)}</span>')
    return mark_safe(" ".join(words))
