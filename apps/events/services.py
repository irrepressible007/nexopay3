from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Event

# Events without an explicit end are treated as over this long after they start.
DEFAULT_DURATION = timedelta(hours=6)


def advance_event_statuses() -> dict:
    """Open sales at sales_start_at and close events once they are over. Run from cron."""
    now = timezone.now()
    opened = 0
    for event in Event.objects.filter(status=Event.Status.COMING_SOON, sales_start_at__isnull=False, sales_start_at__lte=now):
        event.status = Event.Status.ON_SALE
        event.save(update_fields=["status", "updated_at"])
        event.refresh_sold_out_status()
        opened += 1

    over = Q(ends_at__isnull=False, ends_at__lt=now) | Q(ends_at__isnull=True, starts_at__lt=now - DEFAULT_DURATION)
    ended = 0
    for event in Event.objects.filter(over, status__in=(Event.Status.COMING_SOON, Event.Status.ON_SALE, Event.Status.SOLD_OUT)):
        event.status = Event.Status.ENDED
        event.save(update_fields=["status", "updated_at"])
        ended += 1
    return {"opened": opened, "ended": ended}
