from datetime import timedelta

from django.db.models import Count, Sum
from django.urls import reverse
from django.utils import timezone

from apps.events.models import Event
from apps.orders.models import Order
from apps.organizers.models import OrganizerProfile
from apps.payments.models import Refund
from apps.support.models import ContactMessage
from apps.tickets.models import Ticket

PAID = (Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED)


def dashboard_callback(request, context):
    now = timezone.now()
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    paid = Order.objects.filter(status__in=PAID)

    def totals(since):
        agg = paid.filter(paid_at__gte=since).aggregate(
            gross=Sum("total"), commission=Sum("commission_amount"), fees=Sum("buyer_fee"), n=Count("pk"))
        return {k: v or 0 for k, v in agg.items()}

    t_today, t_30 = totals(today), totals(now - timedelta(days=30))
    daily = []
    for i in range(13, -1, -1):
        start = today - timedelta(days=i)
        value = paid.filter(paid_at__gte=start, paid_at__lt=start + timedelta(days=1)).aggregate(v=Sum("total"))["v"] or 0
        daily.append({"label": start.strftime("%d %b"), "value": float(value)})
    peak = max((d["value"] for d in daily), default=0) or 1
    for d in daily:
        d["pct"] = round(d["value"] / peak * 100)

    context.update(
        {
            "kpis": [
                {"label": "Sales today", "value": f"৳{t_today['gross']:,.0f}", "sub": f"{t_today['n']} orders"},
                {"label": "Sales · 30 days", "value": f"৳{t_30['gross']:,.0f}", "sub": f"{t_30['n']} orders"},
                {"label": "Platform revenue · 30 days", "value": f"৳{(t_30['commission'] + t_30['fees']):,.0f}",
                 "sub": "commission + service fees"},
                {"label": "Tickets issued · 30 days",
                 "value": f"{Ticket.objects.filter(created_at__gte=now - timedelta(days=30)).count():,}",
                 "sub": f"{Event.objects.filter(status='on_sale').count()} events on sale"},
            ],
            "queues": [
                {"label": "Organizer applications", "count": OrganizerProfile.objects.filter(status="pending_review").count(),
                 "url": reverse("admin:organizers_organizerprofile_changelist") + "?status__exact=pending_review"},
                {"label": "Refunds to review / process",
                 "count": Refund.objects.filter(status__in=("requested", "approved")).count(),
                 "url": reverse("admin:payments_refund_changelist") + "?status__in=requested,approved"},
                {"label": "New support messages", "count": ContactMessage.objects.filter(status="new").count(),
                 "url": reverse("admin:support_contactmessage_changelist") + "?status__exact=new"},
            ],
            "daily": daily,
            "upcoming": [
                {"title": e.title, "when": e.starts_at, "org": e.organizer.name, "status": e.get_status_display(),
                 "sold": e.sold or 0, "cap": e.cap or 0, "pct": round((e.sold or 0) / e.cap * 100) if e.cap else 0}
                for e in Event.objects.filter(status__in=("on_sale", "sold_out", "coming_soon"), starts_at__gte=now)
                .select_related("organizer")
                .annotate(sold=Sum("ticket_types__sold_count"), cap=Sum("ticket_types__stock"))
                .order_by("starts_at")[:6]
            ],
            "quick_links": [
                ("Homepage sections", reverse("admin:cms_homesection_changelist")),
                ("Hero slides", reverse("admin:cms_heroslide_changelist")),
                ("Site settings & branding", reverse("admin:cms_sitesettings_changelist")),
                ("Payment methods", reverse("admin:payments_paymentprovidersetting_changelist")),
                ("Categories", reverse("admin:events_category_changelist")),
                ("Pages & FAQ", reverse("admin:cms_page_changelist")),
            ],
        }
    )
    return context


def environment_callback(request):
    """Badge in the admin header so nobody confuses staging with production."""
    from django.conf import settings

    if settings.DEBUG:
        return ["Development", "info"]
    if "staging" in settings.SITE_URL:
        return ["Staging", "warning"]
    return ["Production", "danger"]
