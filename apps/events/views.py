from datetime import timedelta
from datetime import timezone as dt_timezone

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, Min, Q, When
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.http import private_no_store, public_cache

from .models import Category, Event

PAGE_SIZE = 12
STATUS_CHOICES = ("all", "live", "upcoming")


def _filtered(status: str, query: str):
    qs = Event.objects.public()
    if status == "live":
        qs = qs.live()
    elif status == "upcoming":
        qs = qs.upcoming()
    if query:
        qs = qs.filter(
            Q(title_en__icontains=query)
            | Q(title_bn__icontains=query)
            | Q(venue_name_en__icontains=query)
            | Q(organizer__name__icontains=query)
            | Q(city__icontains=query)
        )
    return qs


@public_cache(60)
def catalog(request):
    status = request.GET.get("status", "all")
    if status not in STATUS_CHOICES:
        status = "all"
    query = request.GET.get("q", "").strip()[:80]
    selected = [s for s in request.GET.getlist("category") if s][:18]

    base = _filtered(status, query)
    events = base
    if selected:
        events = events.filter(categories__slug__in=selected).distinct()
    events = (
        events.select_related("organizer")
        .prefetch_related("categories")
        .annotate(
            min_price=Min("ticket_types__price", filter=Q(ticket_types__is_available=True)),
            is_ended=Case(When(status="ended", then=1), default=0, output_field=IntegerField()),
        )
        .order_by("is_ended", "starts_at")
    )
    page = Paginator(events, PAGE_SIZE).get_page(request.GET.get("page"))

    # Facet counts honour status + search but not the category filter itself, and
    # include categories with zero events (fixed, admin-managed taxonomy).
    categories = Category.objects.filter(is_active=True).annotate(
        n=Count("events", filter=Q(events__in=base.values("pk")), distinct=True)
    )
    return render(
        request,
        "events/catalog.html",
        {
            "page": page,
            "categories": categories,
            "selected": selected,
            "status": status,
            "query": query,
            "status_choices": [("all", _("All")), ("live", _("Live")), ("upcoming", _("Upcoming"))],
        },
    )


def _get_visible_event(request, slug):
    event = get_object_or_404(
        Event.objects.select_related("organizer").prefetch_related("categories", "ticket_types"), slug=slug
    )
    if event.status != Event.Status.DRAFT:
        return event, True
    user = request.user
    if user.is_authenticated and (user.is_staff or event.organizer.user_id == user.pk):
        return event, False  # draft preview for its organizer / staff
    raise Http404


def detail(request, slug):
    event, public = _get_visible_event(request, slug)
    if public:
        return _detail_public(request, event)
    return _render_detail(request, event, preview=True)


@public_cache(60)
def _detail_public(request, event):
    return _render_detail(request, event)


def _render_detail(request, event, preview=False):
    from apps.cms.models import SiteSettings

    related = (
        Event.objects.public()
        .exclude(pk=event.pk)
        .exclude(status="ended")
        .filter(categories__in=event.categories.all())
        .distinct()
        .select_related("organizer")
        .annotate(min_price=Min("ticket_types__price", filter=Q(ticket_types__is_available=True)))
        .order_by("starts_at")[: SiteSettings.load().related_events_count]
    )
    ticket_types = list(event.ticket_types.all())
    prices = [t.price for t in ticket_types if t.is_available]
    return render(
        request,
        "events/detail.html",
        {
            "event": event,
            "related": related,
            "preview": preview,
            "min_price": min(prices) if prices else None,
            "max_price": max(prices) if prices else None,
            "end_time": event.ends_at or event.starts_at + timedelta(hours=3),
            "share_url": settings.SITE_URL + request.path,
        },
    )


@private_no_store
def ticket_panel(request, slug):
    """Live availability + selection form. Never cached — it reflects stock right now."""
    event, _public = _get_visible_event(request, slug)
    ticket_types = list(event.ticket_types.all())
    if request.user.is_authenticated:
        # One-per-person tickets this buyer already holds: say so here instead of failing at checkout.
        from apps.orders.models import Order, PurchaseClaim

        held = dict(
            PurchaseClaim.objects.filter(order__user=request.user, ticket_type__event=event)
            .filter(order__status__in=(Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED, Order.Status.PENDING_PAYMENT))
            .values_list("ticket_type_id", "order_id")
        )
        orders = {o.pk: o for o in Order.objects.filter(pk__in=set(held.values()))}
        for t in ticket_types:
            t.held_by_me = orders.get(held.get(t.pk))
    return render(
        request,
        "events/_ticket_panel.html",
        {"event": event, "ticket_types": ticket_types, "now": timezone.now()},
    )


def calendar_ics(request, slug):
    event, _public = _get_visible_event(request, slug)
    start = event.starts_at
    end = event.ends_at or event.starts_at + timedelta(hours=3)

    def fmt(dt):
        return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def esc(text):
        return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    body = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Nexopay//Events//EN",
            "BEGIN:VEVENT",
            f"UID:event-{event.pk}@nexopay.com.bd",
            f"DTSTAMP:{fmt(timezone.now())}",
            f"DTSTART:{fmt(start)}",
            f"DTEND:{fmt(end)}",
            f"SUMMARY:{esc(event.title)}",
            f"LOCATION:{esc(', '.join(filter(None, [event.venue_name, event.venue_address, event.city])))}",
            f"URL:{settings.SITE_URL}{event.get_absolute_url()}",
            f"DESCRIPTION:{esc(event.summary)}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{event.slug}.ics"'
    return response
