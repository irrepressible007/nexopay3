"""The control room's home: sales at a glance, what needs attention, and whether the site is ready."""
import json
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.events.models import Event
from apps.orders.models import Order
from apps.organizers.models import OrganizerProfile
from apps.payments.models import PaymentProviderSetting, Refund
from apps.support.models import ContactMessage
from apps.tickets.models import Ticket

PAID = (Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED)
BRAND = "#7351F5"


def _money(value) -> str:
    return f"৳{value or 0:,.0f}"


def _change(now, before):
    """'+12%' style change against the previous period (None when there is nothing to compare)."""
    if not before:
        return None
    pct = round((float(now or 0) - float(before)) / float(before) * 100)
    return {"text": f"{pct:+d}%", "up": pct >= 0}


def _period(paid, start, end):
    agg = paid.filter(paid_at__gte=start, paid_at__lt=end).aggregate(
        gross=Sum("total"), commission=Sum("commission_amount"), fees=Sum("buyer_fee"), n=Count("pk"))
    agg = {k: v or 0 for k, v in agg.items()}
    agg["tickets"] = Ticket.objects.filter(order__status__in=PAID, order__paid_at__gte=start,
                                           order__paid_at__lt=end).count()
    agg["revenue"] = agg["commission"] + agg["fees"]
    return agg


def _setup_checklist(request):
    """What still needs doing before the site is fully ready to sell."""
    from apps.cms.models import Page, SiteSettings

    site = SiteSettings.load()
    live_methods = PaymentProviderSetting.objects.filter(is_enabled=True, is_sandbox=False).exclude(provider="mock")
    policies = Page.objects.filter(slug__in=("terms", "privacy", "refund-policy"))
    unwritten = [p.title for p in policies if not (p.body_en or p.body_bn)]
    posters = Event.objects.featured().exclude(banner="").exists()
    settings_url = reverse("admin:cms_sitesettings_change", args=[site.pk])
    items = [
        {"label": _("Live payment method switched on"), "ok": live_methods.exists(),
         "hint": _("Payment methods: enter merchant details, switch off sandbox, enable."),
         "url": reverse("admin:payments_paymentprovidersetting_changelist")},
        {"label": _("Ticket emails have a sender address"), "ok": bool(site.email_from_address or site.email_host),
         "hint": _("Look & settings › Email."), "url": settings_url},
        {"label": _("Terms, privacy and refund pages written"), "ok": policies.exists() and not unwritten,
         "hint": ", ".join(unwritten) or _("Website › Pages."), "url": reverse("admin:cms_page_changelist")},
        {"label": _("At least one approved organizer"),
         "ok": OrganizerProfile.objects.filter(status=OrganizerProfile.Status.APPROVED).exists(),
         "hint": _("People › Organizers."), "url": reverse("admin:organizers_organizerprofile_changelist")},
        {"label": _("Featured events with pictures for the home page"), "ok": posters,
         "hint": _("Events: tick 'featured' on events that have a picture."),
         "url": reverse("admin:events_event_changelist") + "?featured__exact=1"},
        {"label": _("Contact email and phone filled in"), "ok": bool(site.contact_email and site.contact_phone),
         "hint": _("Look & settings › Contact."), "url": settings_url},
        {"label": _("Visitor statistics (Google Analytics)"), "ok": bool(site.google_analytics_id),
         "hint": _("Optional. Look & settings › SEO."), "url": settings_url, "optional": True},
    ]
    done = sum(1 for i in items if i["ok"])
    return {"items": items, "done": done, "total": len(items), "pct": round(done / len(items) * 100),
            "label": _("%(done)s of %(total)s done") % {"done": done, "total": len(items)}}


def dashboard_callback(request, context):
    now = timezone.now()
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    paid = Order.objects.filter(status__in=PAID)
    last30 = _period(paid, now - timedelta(days=30), now)
    prev30 = _period(paid, now - timedelta(days=60), now - timedelta(days=30))
    t_today = _period(paid, today, now + timedelta(seconds=1))

    started = Order.objects.filter(created_at__gte=now - timedelta(days=30)).count()
    conversion = round(last30["n"] / started * 100) if started else None

    # Daily sales for the chart (30 days), in one grouped query.
    first_day = today - timedelta(days=29)
    per_day = {
        row["day"]: row["v"] for row in paid.filter(paid_at__gte=first_day)
        .annotate(day=TruncDate("paid_at", tzinfo=timezone.get_current_timezone()))
        .values("day").annotate(v=Sum("total"))
    }
    labels, values = [], []
    for i in range(29, -1, -1):
        day = (today - timedelta(days=i)).date()
        labels.append(day.strftime("%d %b"))
        values.append(float(per_day.get(day) or 0))
    chart = {"labels": labels, "datasets": [{"label": _("Sales (৳)"), "data": values, "backgroundColor": BRAND,
                                             "borderColor": BRAND, "borderRadius": 6, "maxBarThickness": 22}]}

    by_method = list(paid.filter(paid_at__gte=now - timedelta(days=30)).values("payment_method")
                     .annotate(total=Sum("total"), n=Count("pk")).order_by("-total"))
    top_method = by_method[0]["total"] if by_method else 0
    methods = [{"name": (m["payment_method"] or "-").replace("_", " ").title(), "total": _money(m["total"]),
                "n": m["n"], "pct": round(float(m["total"]) / float(top_method) * 100) if top_method else 0}
               for m in by_method]

    top_events = (Event.objects.filter(orders__status__in=PAID, orders__paid_at__gte=now - timedelta(days=30))
                  .annotate(gross=Sum("orders__total"), n=Count("orders", distinct=True)).order_by("-gross")[:5])
    recent = Order.objects.filter(status__in=PAID).select_related("event").order_by("-paid_at")[:6]

    context.update({
        "kpis": [
            {"label": _("Sales today"), "value": _money(t_today["gross"]),
             "sub": _("%(n)s orders") % {"n": t_today["n"]}, "icon": "today"},
            {"label": _("Sales · 30 days"), "value": _money(last30["gross"]), "change": _change(last30["gross"], prev30["gross"]),
             "sub": _("%(n)s orders") % {"n": last30["n"]}, "icon": "trending_up"},
            {"label": _("Tickets sold · 30 days"), "value": f"{last30['tickets']:,}",
             "change": _change(last30["tickets"], prev30["tickets"]),
             "sub": _("%(n)s events on sale") % {"n": Event.objects.filter(status="on_sale").count()},
             "icon": "confirmation_number"},
            {"label": _("Platform revenue · 30 days"), "value": _money(last30["revenue"]),
             "change": _change(last30["revenue"], prev30["revenue"]),
             "sub": (_("%(pct)s%% of checkouts paid") % {"pct": conversion}) if conversion is not None
             else _("commission + service fees"), "icon": "account_balance"},
        ],
        "queues": [
            {"label": _("Organizer applications"), "icon": "storefront",
             "count": OrganizerProfile.objects.filter(status="pending_review").count(),
             "url": reverse("admin:organizers_organizerprofile_changelist") + "?status__exact=pending_review"},
            {"label": _("Refunds to review / process"), "icon": "currency_exchange",
             "count": Refund.objects.filter(status__in=("requested", "approved")).count(),
             "url": reverse("admin:payments_refund_changelist")},
            {"label": _("New support messages"), "icon": "mail",
             "count": ContactMessage.objects.filter(status="new").count(),
             "url": reverse("admin:support_contactmessage_changelist") + "?status__exact=new"},
            {"label": _("Draft events"), "icon": "edit_note",
             "count": Event.objects.filter(status="draft").count(),
             "url": reverse("admin:events_event_changelist") + "?status__exact=draft"},
        ],
        "chart": json.dumps(chart),
        "chart_options": json.dumps({"plugins": {"legend": {"display": False}},
                                     "scales": {"x": {"grid": {"display": False}}, "y": {"beginAtZero": True}}}),
        "methods": methods,
        "top_events": [{"title": e.title, "gross": _money(e.gross), "n": e.n,
                        "url": reverse("admin:events_event_change", args=[e.pk])} for e in top_events],
        "recent": [{"ref": o.reference, "who": o.buyer_name or o.delivery_email, "event": o.event.title,
                    "total": _money(o.total), "when": o.paid_at,
                    "url": reverse("admin:orders_order_change", args=[o.pk])} for o in recent],
        "upcoming": [
            {"title": e.title, "when": e.starts_at, "org": e.organizer.name, "status": e.get_status_display(),
             "sold": e.sold or 0, "cap": e.cap or 0, "pct": round((e.sold or 0) / e.cap * 100) if e.cap else 0,
             "url": reverse("admin:events_event_change", args=[e.pk])}
            for e in Event.objects.filter(status__in=("on_sale", "sold_out", "coming_soon"), starts_at__gte=now)
            .select_related("organizer")
            .annotate(sold=Sum("ticket_types__sold_count"), cap=Sum("ticket_types__stock"))
            .order_by("starts_at")[:6]
        ],
        "setup": _setup_checklist(request),
        "quick_actions": [
            {"label": _("New event"), "icon": "add_circle", "url": reverse("admin:events_event_add")},
            {"label": _("Homepage sections"), "icon": "view_quilt", "url": reverse("admin:cms_homesection_changelist")},
            {"label": _("Look & settings"), "icon": "tune", "url": reverse("admin:cms_sitesettings_changelist")},
            {"label": _("Announcement bar"), "icon": "campaign", "url": reverse("admin:cms_sitesettings_changelist")},
            {"label": _("Site texts"), "icon": "translate", "url": reverse("admin:cms_sitetext_changelist")},
            {"label": _("View website"), "icon": "open_in_new", "url": "/"},
        ],
    })
    return context


def environment_callback(request):
    """Badge in the admin header so nobody confuses staging with production."""
    from django.conf import settings

    if settings.DEBUG:
        return ["Development", "info"]
    if "staging" in settings.SITE_URL or "new." in settings.SITE_URL:
        return ["Staging", "warning"]
    return ["Production", "danger"]
