"""Gate scanning — a mobile web app; no native app needed."""
import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.core.http import private_no_store
from apps.events.models import Event

from .models import ScanLog, ScannerAccess, Ticket
from .services import redeem_ticket


def can_scan(user, event) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_staff or event.organizer.user_id == user.pk:
        return True
    return ScannerAccess.objects.filter(event=event, user=user).exists()


def _scannable_events(user):
    recent = timezone.now() - timedelta(days=1)
    qs = Event.objects.exclude(status__in=(Event.Status.DRAFT, Event.Status.CANCELLED)).filter(
        Q(ends_at__gte=recent) | Q(ends_at__isnull=True, starts_at__gte=recent - timedelta(hours=12))
    )
    if not user.is_staff:
        qs = qs.filter(Q(organizer__user=user) | Q(scanner_access__user=user)).distinct()
    return qs.select_related("organizer").order_by("starts_at")


@login_required
@private_no_store
def home(request):
    return render(request, "scan/home.html", {"events": _scannable_events(request.user)})


def _counts(event):
    return Ticket.objects.filter(event=event).aggregate(
        total=Count("pk", filter=~Q(status=Ticket.Status.REFUNDED)),
        checked_in=Count("pk", filter=Q(status=Ticket.Status.REDEEMED)),
    )


@login_required
@private_no_store
def event(request, slug):
    event = get_object_or_404(Event.objects.select_related("organizer"), slug=slug)
    if not can_scan(request.user, event):
        raise Http404
    return render(request, "scan/scanner.html", {"event": event, "counts": _counts(event)})


MESSAGES = {
    ScanLog.Result.OK: gettext_lazy("Welcome in!"),
    ScanLog.Result.ALREADY_REDEEMED: gettext_lazy("Already used"),
    ScanLog.Result.REFUNDED: gettext_lazy("Refunded ticket — not valid"),
    ScanLog.Result.WRONG_EVENT: gettext_lazy("Ticket is for a different event"),
    ScanLog.Result.INVALID: gettext_lazy("Not a valid Nexopay ticket"),
}


@login_required
@require_POST
@ratelimit(key="user", rate="120/m", block=True)
def redeem(request, slug):
    event = get_object_or_404(Event.objects.select_related("organizer"), slug=slug)
    if not can_scan(request.user, event):
        return JsonResponse({"error": "forbidden"}, status=403)
    try:
        raw = json.loads(request.body or "{}").get("code", "")
    except ValueError:
        raw = request.POST.get("code", "")
    result = redeem_ticket(raw=str(raw)[:200], event=event, scanned_by=request.user)
    ticket = result.ticket
    payload = {
        "ok": result.ok,
        "result": result.result,
        "message": str(MESSAGES[result.result]),
        "counts": _counts(event),
    }
    if ticket is not None and result.result != ScanLog.Result.WRONG_EVENT:
        payload["ticket"] = {
            "code": ticket.code,
            "type": ticket.ticket_type.name,
            "holder": ticket.holder_name,
            "redeemed_at": timezone.localtime(ticket.redeemed_at).strftime("%I:%M %p") if ticket.redeemed_at else None,
            "redeemed_by": ticket.redeemed_by.get_full_name() if ticket.redeemed_by_id else None,
        }
    return JsonResponse(payload)
