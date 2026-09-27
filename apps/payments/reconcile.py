"""
Catch payments whose confirmation never reached us (buyer closed the tab,
callback timed out, IPN lost) by asking each provider directly.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from .models import PaymentAttempt, Provider
from .registry import get_provider
from .services import PaymentError, mark_failed, mark_succeeded

logger = logging.getLogger("apps.payments")


def reconcile_pending(min_age_minutes: int = 3, give_up_hours: int = 24, limit: int = 100) -> dict:
    now = timezone.now()
    stats = {"checked": 0, "succeeded": 0, "failed": 0, "abandoned": 0}

    stale = PaymentAttempt.objects.filter(
        status=PaymentAttempt.Status.INITIATED, created_at__lt=now - timedelta(hours=give_up_hours)
    )
    for attempt in stale[:limit]:
        mark_failed(attempt, PaymentAttempt.Status.CANCELLED, {"reconcile": "abandoned"})
        stats["abandoned"] += 1

    pending = (
        PaymentAttempt.objects.filter(
            status=PaymentAttempt.Status.INITIATED,
            created_at__lt=now - timedelta(minutes=min_age_minutes),
            created_at__gte=now - timedelta(hours=give_up_hours),
        )
        .exclude(provider__in=(Provider.MOCK, Provider.FREE))
        .select_related("order")
        .order_by("created_at")[:limit]
    )
    for attempt in pending:
        provider = get_provider(attempt.provider, require_enabled=False)
        if provider is None:
            continue
        stats["checked"] += 1
        try:
            result = provider.verify(attempt)
        except PaymentError as exc:
            logger.info("Reconcile %s: %s", attempt.tran_id, exc)
            continue
        if result.status == PaymentAttempt.Status.SUCCEEDED and result.provider_txn_id:
            mark_succeeded(attempt, result.provider_txn_id, {"reconciled": result.payload})
            stats["succeeded"] += 1
        elif result.status in (PaymentAttempt.Status.FAILED, PaymentAttempt.Status.CANCELLED):
            mark_failed(attempt, result.status, {"reconciled": result.payload})
            stats["failed"] += 1
    if any(stats.values()):
        logger.info("Payment reconciliation: %s", stats)
    return stats
