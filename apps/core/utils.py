import re
import secrets

import nh3
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

# Bangladeshi mobile numbers: 01[3-9] followed by 8 digits.
_BD_MOBILE = re.compile(r"^01[3-9]\d{8}$")


def normalize_phone(raw: str) -> str:
    """Return a Bangladeshi mobile number as +8801XXXXXXXXX or raise ValidationError."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("880"):
        digits = digits[2:]
    if not _BD_MOBILE.match(digits):
        raise ValidationError(_("Enter a valid Bangladeshi mobile number, e.g. 01712345678."))
    return "+88" + digits


def validate_bd_phone(value: str) -> None:
    normalize_phone(value)


# Readable, unambiguous alphabet (no 0/O/1/I/L) for public references.
_REF_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def random_code(length: int = 8) -> str:
    return "".join(secrets.choice(_REF_ALPHABET) for _ in range(length))


_ALLOWED_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "s", "ul", "ol", "li", "a",
    "h2", "h3", "h4", "blockquote", "hr", "span",
}


def sanitize_html(value: str) -> str:
    """Strip anything but a small set of formatting tags from rich text."""
    if not value:
        return value
    return nh3.clean(
        value,
        tags=_ALLOWED_TAGS,
        attributes={"a": {"href", "title"}},
        link_rel="noopener noreferrer nofollow",
        url_schemes={"http", "https", "mailto", "tel"},
    )
