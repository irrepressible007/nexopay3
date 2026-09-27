import json
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
