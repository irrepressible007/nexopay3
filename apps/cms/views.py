from datetime import timedelta

from django.core.cache import cache
from django.db.models import Count, Min, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import get_language

from apps.core.cache import versioned_key
from apps.core.http import private_no_store, public_cache
from apps.events.models import Category, Event

from .models import FaqItem, HeroSlide, HomeSection, Page, Partner, SiteSettings


def _event_cards(qs, limit):
    return list(
        qs.select_related("organizer")
        .prefetch_related("categories")
        .annotate(min_price=Min("ticket_types__price", filter=Q(ticket_types__is_available=True)))[:limit]
    )


def _section_payload(section: HomeSection):
    now = timezone.now()
    public = Event.objects.public()
    kind = section.kind
    K = HomeSection.Kind
    if kind == K.HERO:
        slides = list(HeroSlide.objects.visible().select_related("event"))
        if not slides:
            # Brand hero: admin headline, search and quick category links (featured events follow below).
            return {
                "hero_categories": list(Category.objects.filter(is_active=True, show_in_hero=True)[:8]),
                "brand": True,
            }
        return {"slides": slides}
    if kind == K.FEATURED:
        return {"events": _event_cards(Event.objects.featured().order_by("featured_rank", "starts_at"), section.item_limit)}
    if kind == K.CATEGORIES:
        cats = Category.objects.filter(is_active=True, show_on_home=True).annotate(
            n=Count("events", filter=Q(events__status__in=("on_sale", "sold_out", "coming_soon")))
        )
        return {"categories": list(cats)}
    if kind == K.THIS_WEEK:
        qs = public.filter(starts_at__gte=now, starts_at__lte=now + timedelta(days=7)).order_by("starts_at")
        return {"events": _event_cards(qs, section.item_limit)}
    if kind == K.UPCOMING:
        return {"events": _event_cards(public.upcoming().order_by("starts_at"), section.item_limit)}
    if kind == K.JUST_ANNOUNCED:
        qs = public.exclude(status="ended").order_by("-published_at")
        return {"events": _event_cards(qs, section.item_limit)}
    if kind == K.CATEGORY_SPOTLIGHT and section.category_id:
        qs = public.exclude(status="ended").filter(categories=section.category_id).order_by("starts_at")
        return {"events": _event_cards(qs, section.item_limit)}
    if kind == K.PARTNERS:
        return {"partners": list(Partner.objects.filter(is_enabled=True))}
    if kind == K.FAQ:
        return {"faqs": list(FaqItem.objects.filter(is_published=True, show_on_home=True)[: section.item_limit])}
    return {}


@public_cache(60)
def home(request):
    key = versioned_key("home", get_language())
    sections = cache.get(key)
    if sections is None:
        sections = []
        for section in HomeSection.objects.visible():
            payload = _section_payload(section)
            has_content = any(payload.values()) or section.kind in (
                HomeSection.Kind.HERO,
                HomeSection.Kind.PROMO_BANNER,
                HomeSection.Kind.ORGANIZER_CTA,
            )
            if has_content:
                sections.append({"section": section, **payload})
        cache.set(key, sections, 60)
    return render(request, "cms/home.html", {"sections": sections})


@public_cache(300)
def page(request, slug):
    page = get_object_or_404(Page, slug=slug, is_published=True)
    return render(request, "cms/page.html", {"page": page})


@public_cache(300)
def faq(request):
    return render(request, "cms/faq.html", {"faqs": FaqItem.objects.filter(is_published=True)})


@private_no_store
def nav_fragment(request):
    """Per-user header bits + flash messages, loaded by HTMX on edge-cached pages."""
    return render(request, "partials/nav_user.html", {"oob": True})


def maintenance(request):
    return render(request, "cms/maintenance.html", status=503)


def webmanifest(request):
    """Lets buyers and gate staff add the site to their phone's home screen."""
    from django.http import JsonResponse
    from django.templatetags.static import static

    site = SiteSettings.load()
    icon = site.favicon.url if site.favicon else static("img/icon-512.png")
    return JsonResponse(
        {
            "name": site.site_name,
            "short_name": site.site_name,
            "start_url": "/",
            "display": "standalone",
            "background_color": site.background_color,
            "theme_color": site.background_color,
            "icons": [
                {"src": static("img/icon-192.png"), "sizes": "192x192", "type": "image/png"},
                {"src": icon, "sizes": "512x512", "type": "image/png"},
            ],
        },
        content_type="application/manifest+json",
    )
