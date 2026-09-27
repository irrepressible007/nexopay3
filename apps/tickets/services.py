"""Gate check-in. The one control that stops a screenshotted QR being used twice."""
from dataclasses import dataclass

from django.utils import timezone

from .models import ScanLog, Ticket


@dataclass
class ScanResult:
    result: str
    ticket: Ticket | None = None

    @property
    def ok(self) -> bool:
        return self.result == ScanLog.Result.OK


def find_ticket(raw: str) -> Ticket | None:
    """Accept either the signed QR token or the printed 10-character ticket code."""
    raw = (raw or "").strip()
    ticket_id = Ticket.id_from_token(raw)
    qs = Ticket.objects.select_related("ticket_type", "event", "redeemed_by")
    if ticket_id:
        return qs.filter(pk=ticket_id).first()
    code = raw.upper().replace("-", "").replace(" ", "")
    if 8 <= len(code) <= 12:
        return qs.filter(code=code).first()
    return None


def redeem_ticket(*, raw: str, event, scanned_by) -> ScanResult:
    """
    Check a ticket in. The status flip is a single conditional UPDATE, so two
    gates scanning the same ticket at the same instant can never both succeed,
    and scanning a redeemed ticket again always fails without changing it.
    """
    ticket = find_ticket(raw)
    if ticket is None:
        result = ScanResult(ScanLog.Result.INVALID)
    elif ticket.event_id != event.pk:
        result = ScanResult(ScanLog.Result.WRONG_EVENT, ticket)
    else:
        updated = Ticket.objects.filter(pk=ticket.pk, status=Ticket.Status.VALID).update(
            status=Ticket.Status.REDEEMED, redeemed_at=timezone.now(), redeemed_by=scanned_by
        )
        ticket.refresh_from_db()
        if updated == 1:
            result = ScanResult(ScanLog.Result.OK, ticket)
        elif ticket.status == Ticket.Status.REFUNDED:
            result = ScanResult(ScanLog.Result.REFUNDED, ticket)
        else:
            result = ScanResult(ScanLog.Result.ALREADY_REDEEMED, ticket)
    ScanLog.objects.create(event=event, ticket=result.ticket, scanned_by=scanned_by, result=result.result)
    return result
