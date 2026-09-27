"""
Everything periodic, in one command, so cPanel needs a single cron line:

    * * * * * cd ~/nexopay && flock -n /tmp/nexopay-cron.lock ~/virtualenv/nexopay/3.12/bin/python manage.py nexopay_cron

Each job is isolated: one failing never stops the others.
"""
import logging
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run periodic jobs: expire holds, event statuses, payment reconciliation, background tasks."

    def add_arguments(self, parser):
        parser.add_argument("--skip-tasks", action="store_true", help="Don't run the background task worker.")

    def handle(self, *args, skip_tasks=False, **options):
        from apps.events.services import advance_event_statuses
        from apps.orders.services import expire_stale_orders
        from apps.payments.reconcile import reconcile_pending

        started = time.monotonic()
        for name, job in (
            ("expire_holds", expire_stale_orders),
            ("event_statuses", advance_event_statuses),
            ("reconcile_payments", reconcile_pending),
        ):
            try:
                result = job()
                if result and (not isinstance(result, dict) or any(result.values())):
                    self.stdout.write(f"{name}: {result}")
            except Exception:
                logger.exception("Cron job %s failed", name)

        if not skip_tasks:
            # Deliver emails/PDFs etc. Bounded so the next cron tick never overlaps.
            try:
                call_command("db_worker", batch=True, max_tasks=200, startup_delay=False, verbosity=0)
            except Exception:
                logger.exception("Background task worker failed")
        logger.debug("nexopay_cron finished in %.1fs", time.monotonic() - started)
