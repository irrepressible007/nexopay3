from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.cms.models import Page
from apps.events.models import Event


class StaticSitemap(Sitemap):
    i18n = True
    changefreq = "daily"

    def items(self):
        return ["cms:home", "events:catalog", "cms:faq", "support:contact"]

    def location(self, item):
        return reverse(item)


class EventSitemap(Sitemap):
    i18n = True
    changefreq = "hourly"

    def items(self):
        return Event.objects.public().order_by("-starts_at")[:5000]

    def lastmod(self, obj):
        return obj.updated_at


class PageSitemap(Sitemap):
    i18n = True

    def items(self):
        return Page.objects.filter(is_published=True)

    def lastmod(self, obj):
        return obj.updated_at


SITEMAPS = {"static": StaticSitemap, "events": EventSitemap, "pages": PageSitemap}
