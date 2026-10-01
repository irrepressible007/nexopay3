"""
Admin sidebar helpers: permission checks and the live counters ("badges") next to menu items.

Imported by settings, so nothing here may import models at module level.
"""
import copy

from django.utils.module_loading import import_string


def navigation(request):
    """settings.ADMIN_NAVIGATION for this request: an item's counter (`badge_fn`) is shown only when
    something is waiting, so empty queues stay quiet."""
    from django.conf import settings

    groups = copy.deepcopy(settings.ADMIN_NAVIGATION)
    for group in groups:
        for item in group["items"]:
            fn = item.pop("badge_fn", None)
            if fn:
                try:
                    count = import_string(fn)(request)
                except Exception:  # a counter must never break the menu
                    count = None
                if count:
                    item["badge"] = count
    return groups


def perm(*codenames):
    """Show a menu item only to staff who may view at least one of these models."""

    def check(request):
        user = request.user
        return user.is_active and user.is_staff and any(user.has_perm(c) for c in codenames)

    return check


def _count(qs):
    n = qs.count()
    return n or None  # no badge when there is nothing waiting


def pending_organizers(request):
    from apps.organizers.models import OrganizerProfile

    return _count(OrganizerProfile.objects.filter(status=OrganizerProfile.Status.PENDING_REVIEW))


def open_refunds(request):
    from apps.payments.models import Refund

    return _count(Refund.objects.filter(status__in=("requested", "approved")))


def new_messages(request):
    from apps.support.models import ContactMessage

    return _count(ContactMessage.objects.filter(status=ContactMessage.Status.NEW))


def orders_today(request):
    from django.utils import timezone

    from apps.orders.models import Order

    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return _count(Order.objects.filter(status__in=("paid", "partially_refunded"), paid_at__gte=start))


def events_on_sale(request):
    from apps.events.models import Event

    return _count(Event.objects.filter(status=Event.Status.ON_SALE))
