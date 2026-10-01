from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponsePermanentRedirect
from django.shortcuts import render

from apps.cms.models import SiteSettings

# Browser features the site may use: the camera only on our own pages (gate scanner); the rest are off.
PERMISSIONS_POLICY = "camera=(self), microphone=(), geolocation=(), payment=(), usb=(), browsing-topics=()"


class CanonicalHostMiddleware:
    """www.<site> → <site> in one permanent hop (straight to https), so search engines see one site."""

    def __init__(self, get_response):
        self.get_response = get_response
        canonical = urlsplit(settings.SITE_URL)
        self.scheme, self.host = canonical.scheme or "https", (canonical.hostname or "").lower()

    def __call__(self, request):
        if self.host and not self.host.startswith("www.") and request.method in ("GET", "HEAD"):
            host = request.get_host().split(":", 1)[0].lower()
            if host == f"www.{self.host}":
                return HttpResponsePermanentRedirect(f"{self.scheme}://{self.host}{request.get_full_path()}")
        return self.get_response(request)


class PermissionsPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        return response


# Payment callbacks must keep working during maintenance so no payment is lost.
ALWAYS_OPEN = ("/static/", "/media/", "/payments/", "/i18n/", "/accounts/login/")


class MaintenanceModeMiddleware:
    """Serve a 503 page to non-staff visitors while SiteSettings.maintenance_mode is on."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path_info
        if (
            SiteSettings.load().maintenance_mode
            and not path.startswith(ALWAYS_OPEN)
            and settings.ADMIN_URL not in path
            and not (request.user.is_authenticated and request.user.is_staff)
        ):
            response = render(request, "cms/maintenance.html", status=503)
            response["Retry-After"] = "600"
            return response
        return self.get_response(request)
