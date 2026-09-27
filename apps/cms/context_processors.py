from django.conf import settings
from django.core.cache import cache

from apps.core.cache import versioned_key

from .models import Page, SiteSettings


def site(request):
    lang = getattr(request, "LANGUAGE_CODE", "en")
    key = versioned_key("footer-pages", lang)
    pages = cache.get(key)
    if pages is None:
        pages = [
            {"title": p.title, "url": p.get_absolute_url()}
            for p in Page.objects.filter(is_published=True, show_in_footer=True)
        ]
        cache.set(key, pages, 3600)
    return {"sitecfg": SiteSettings.load(), "footer_pages": pages, "ADMIN_URL": settings.ADMIN_URL}
