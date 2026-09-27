from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from django.templatetags.static import static as static_url
from django.shortcuts import redirect
from django.views.generic import TemplateView

from apps.cms import views as cms_views
from apps.core import views as core_views
from apps.core.sitemaps import SITEMAPS

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("payments/", include("apps.payments.urls")),
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS}, name="sitemap"),
    path("favicon.ico", lambda request: redirect(static_url("img/favicon.svg"), permanent=True)),
    path("site.webmanifest", cms_views.webmanifest, name="webmanifest"),
    path("private-media/<path:path>", core_views.private_media, name="private_media"),
    path("robots.txt", TemplateView.as_view(template_name="robots.txt", content_type="text/plain")),
]

urlpatterns += i18n_patterns(
    path(settings.ADMIN_URL, admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("account/", include("apps.accounts.urls")),
    path("events/", include("apps.events.urls")),
    path("organizers/", include("apps.organizers.urls")),
    path("scan/", include("apps.tickets.scan_urls")),
    path("", include("apps.orders.urls")),
    path("", include("apps.tickets.urls")),
    path("", include("apps.support.urls")),
    path("", include("apps.cms.urls")),
    prefix_default_language=False,
)

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
