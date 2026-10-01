"""
Hardening helpers that don't belong to one app: control-room login throttling,
upload checks and the "who may touch money settings" rule.
"""
import re
from functools import wraps

from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.utils.translation import gettext as _
from django_ratelimit.core import is_ratelimited

# --- Control-room login --------------------------------------------------------------
# The site login (allauth) has its own limits; Django's admin login has none, so a
# password could be guessed there at full speed. Every POST counts, per account and per IP.
ADMIN_LOGIN_RATES = {"user": "5/5m", "ip": "20/h"}


def _username_key(group, request):
    return (request.POST.get("username") or "").strip().lower()


def throttle_login(login_view):
    @wraps(login_view)
    def view(request, *args, **kwargs):
        if request.method == "POST":
            hits = [
                is_ratelimited(request, group="admin-login-user", key=_username_key,
                               rate=ADMIN_LOGIN_RATES["user"], method="POST", increment=True),
                is_ratelimited(request, group="admin-login-ip", key="ip",
                               rate=ADMIN_LOGIN_RATES["ip"], method="POST", increment=True),
            ]
            if any(hits):
                return render(request, "errors/429.html", status=429)
        return login_view(request, *args, **kwargs)

    return view


# --- Money settings --------------------------------------------------------------------
def can_manage_money(user) -> bool:
    """Fees, holds and refund rights: superusers and the Finance role only."""
    return user.is_superuser or user.has_perm("payments.change_paymentprovidersetting")


# --- Uploads ---------------------------------------------------------------------------
_SIGNATURES = {
    "pdf": lambda head: head.startswith(b"%PDF-"),
    "jpg": lambda head: head.startswith(b"\xff\xd8\xff"),
    "jpeg": lambda head: head.startswith(b"\xff\xd8\xff"),
    "png": lambda head: head.startswith(b"\x89PNG\r\n\x1a\n"),
    "webp": lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
}


def check_document(upload, *, max_mb=5, allowed=("pdf", "jpg", "jpeg", "png", "webp")):
    """A private document must really be the PDF/image its name says (no HTML or scripts in disguise)."""
    if not upload or not hasattr(upload, "read"):
        return upload
    if upload.size > max_mb * 1024 * 1024:
        raise ValidationError(_("Please upload a file smaller than %(n)s MB.") % {"n": max_mb})
    ext = upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
    if ext not in allowed:
        raise ValidationError(_("Upload a PDF, JPG, PNG or WebP file."))
    upload.seek(0)
    head = upload.read(16)
    upload.seek(0)
    if not _SIGNATURES[ext](head):
        raise ValidationError(_("This file isn't a real %(type)s.") % {"type": ext.upper()})
    return upload


# Decoding is what costs memory: a 2 MB PNG can unpack to gigabytes. 40 MP covers any real banner.
MAX_PIXELS = 40_000_000


def too_many_pixels(width: int, height: int) -> bool:
    return width * height > MAX_PIXELS


def check_image_size(upload, *, max_mb):
    if not upload or not hasattr(upload, "size"):
        return upload
    if upload.size > max_mb * 1024 * 1024:
        raise ValidationError(_("Please upload an image smaller than %(n)s MB.") % {"n": max_mb})
    from PIL import Image

    try:
        upload.seek(0)
        with Image.open(upload) as img:  # reads the header only
            width, height = img.size
    except Exception:  # not an image: the ImageField itself reports that
        return upload
    finally:
        upload.seek(0)
    if too_many_pixels(width, height):
        raise ValidationError(_("This image is too large (%(w)s×%(h)s). Please use one under 8000×5000 pixels.")
                              % {"w": width, "h": height})
    return upload


_SVG_DANGER = re.compile(
    rb"<\s*(script|foreignobject|iframe|embed|object|handler|use[^>]+href\s*=\s*[\"']?\s*(?:https?:|//|data:text))"
    rb"|\bon[a-z]+\s*=|javascript:|<!ENTITY",
    re.I,
)
_ALLOWED_ARTWORK = ("svg", "png", "jpg", "jpeg", "webp", "gif", "ico")


def validate_artwork(upload):
    """Logos, icons and favicons: images only, and SVGs without scripts, event handlers or external content."""
    if not upload or not hasattr(upload, "name"):
        return
    ext = upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
    if ext not in _ALLOWED_ARTWORK:
        raise ValidationError(_("Upload an SVG, PNG, JPG, WebP, GIF or ICO image."))
    if getattr(upload, "size", 0) > 5 * 1024 * 1024:
        raise ValidationError(_("Please upload an image smaller than %(n)s MB.") % {"n": 5})
    if ext == "svg":
        try:
            upload.seek(0)
            data = upload.read()
            upload.seek(0)
        except Exception:  # an already-stored file we can't reopen: it was checked when uploaded
            return
        if _SVG_DANGER.search(data):
            raise ValidationError(_("This SVG contains scripts or links to outside content. Export it as a plain image."))
