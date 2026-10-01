"""
Clear demo and test data before the site goes live.

Keeps: site settings, categories, pages, FAQ, homepage sections, site texts, payment
provider setup, support routing, staff accounts and staff roles.
Removes: every order, ticket, payment attempt, refund, payout, scan, contact message and
background-task record; every event (unless kept); every organizer and non-staff account
(unless kept). Everything happens in one transaction.

    python manage.py purge_test_data                      # shows what would go, changes nothing
    python manage.py purge_test_data --keep-user a@b.com --keep-event my-real-event
    python manage.py purge_test_data --yes                # really delete
"""
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from apps.events.models import Event, TicketType
from apps.orders.models import Order
from apps.organizers.models import OrganizerProfile
from apps.payments.models import PaymentAttempt, PaymentProviderSetting, Payout, Provider, Refund
from apps.support.models import ContactMessage
from apps.tickets.models import ScanLog, Ticket


class Command(BaseCommand):
    help = "Remove demo/test events, orders, tickets and non-staff accounts (dry run unless --yes)."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Actually delete (default: only show).")
        parser.add_argument("--keep-user", action="append", default=[], metavar="EMAIL",
                            help="Keep this account (and its organizer profile). Repeatable.")
        parser.add_argument("--keep-event", action="append", default=[], metavar="SLUG",
                            help="Keep this event and its organizer (its test orders still go). Repeatable.")

    def handle(self, *args, yes=False, keep_user=(), keep_event=(), **options):
        User = get_user_model()
        kept_events = Event.objects.filter(slug__in=keep_event)
        missing = set(keep_event) - set(kept_events.values_list("slug", flat=True))
        if missing:
            self.stderr.write(self.style.ERROR(f"No event with slug: {', '.join(sorted(missing))}"))
            return
        kept_user_ids = set(User.objects.filter(email__in=[e.lower() for e in keep_user]).values_list("pk", flat=True))
        kept_user_ids |= set(kept_events.values_list("organizer__user_id", flat=True))

        events = Event.objects.exclude(pk__in=kept_events.values("pk")).select_related("organizer")
        organizers = (OrganizerProfile.objects.exclude(user_id__in=kept_user_ids)
                      .exclude(user__is_staff=True).exclude(user__is_superuser=True))  # staff keep their profile
        users = User.objects.filter(is_staff=False, is_superuser=False).exclude(pk__in=kept_user_ids)

        plan = [
            ("orders", Order.objects.all()),
            ("tickets", Ticket.objects.all()),
            ("payment attempts", PaymentAttempt.objects.all()),
            ("refunds", Refund.objects.all()),
            ("payouts", Payout.objects.all()),
            ("gate scans", ScanLog.objects.all()),
            ("contact messages", ContactMessage.objects.all()),
            ("events", events),
            ("organizer profiles", organizers),
            ("non-staff accounts", users),
        ]
        self.stdout.write(self.style.MIGRATE_HEADING("Will remove:" if yes else "Would remove (dry run, nothing changed):"))
        for label, qs in plan:
            self.stdout.write(f"  {qs.count():>6}  {label}")
        for event in events[:50]:
            self.stdout.write(f"          event  {event.slug}  ({event.organizer.name})")
        for user in users.order_by("email")[:50]:
            self.stdout.write(f"        account  {user.email}")
        kept = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True) | Q(pk__in=kept_user_ids)).order_by("email")
        self.stdout.write(self.style.MIGRATE_HEADING("Will keep these accounts:"))
        for user in kept:
            role = "superuser" if user.is_superuser else "staff" if user.is_staff else "kept"
            self.stdout.write(f"        {role:>9}  {user.email}")
        for event in kept_events:
            self.stdout.write(f"     kept event  {event.slug}")

        if not yes:
            self.stdout.write("Nothing was changed. Run again with --yes to delete.")
            return

        banners = [(e.banner.name if e.banner else "", dict(e.banner_renditions or {})) for e in events]
        with transaction.atomic():
            # Children before parents: tickets, attempts and refunds protect their orders.
            ScanLog.objects.all().delete()
            for refund in Refund.objects.all():
                refund.tickets.clear()
            Refund.objects.all().delete()
            Ticket.objects.all().delete()
            PaymentAttempt.objects.all().delete()
            Order.objects.all().delete()  # items and purchase claims go with them
            Payout.objects.all().delete()
            ContactMessage.objects.all().delete()
            events.delete()  # ticket types and scanner access go with them
            organizers.delete()
            users.delete()
            TicketType.objects.update(sold_count=0, held_count=0)
            for event in Event.objects.all():
                event.refresh_sold_out_status()
            PaymentProviderSetting.objects.filter(provider=Provider.MOCK).update(is_enabled=False)
            try:
                from django_tasks_db.models import DBTaskResult

                DBTaskResult.objects.all().delete()  # queued emails for orders that no longer exist
            except ImportError:
                pass
            Session.objects.all().delete()  # everyone signs in again on the live site

        for name, renditions in banners:  # uploaded files of deleted events (best effort)
            for path in [name, *renditions.values()]:
                try:
                    if path and default_storage.exists(path):
                        default_storage.delete(path)
                except Exception:
                    pass
        self.stdout.write(self.style.SUCCESS("✓ Test data removed. Staff must sign in again."))
