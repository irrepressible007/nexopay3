from django.conf import settings
from django.core.cache import cache
from django.db.models import Prefetch

from apps.core.cache import versioned_key

from .models import FooterColumn, MenuItem, SiteSettings


def _navigation(lang: str) -> dict:
    """Header menu, footer columns and payment badges — all admin-managed, cached per language."""
    key = versioned_key("navigation", lang)
    data = cache.get(key)
    if data is not None:
        return data
    from apps.payments.models import PaymentProviderSetting

    header = [
        {"label": item.label, "url": item.url, "new_tab": item.open_in_new_tab}
        for item in MenuItem.objects.filter(location=MenuItem.Location.HEADER, is_enabled=True).order_by("sort_order")
    ]
    columns = [
        {
            "title": col.title,
            "links": [{"label": i.label, "url": i.url, "new_tab": i.open_in_new_tab} for i in col.enabled_items],
        }
        for col in FooterColumn.objects.filter(is_enabled=True).prefetch_related(
            Prefetch("items", queryset=MenuItem.objects.filter(is_enabled=True).order_by("sort_order"),
                     to_attr="enabled_items")
        )
    ]
    payments = [
        {"name": str(p), "color": p.brand_color, "logo": p.logo.url if p.logo else ""}
        for p in PaymentProviderSetting.objects.filter(show_in_footer=True).exclude(provider__in=("mock", "free"))
    ]
    data = {"header_links": header, "footer_columns": columns, "payment_badges": payments}
    cache.set(key, data, 3600)
    return data


def site(request):
    lang = getattr(request, "LANGUAGE_CODE", "en")
    return {"sitecfg": SiteSettings.load(), "ADMIN_URL": settings.ADMIN_URL, **_navigation(lang)}
