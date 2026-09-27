"""
Fill a DEVELOPMENT database with worst-case admin content, to prove layouts
survive anything admins might enter. Never run this on production.

    python manage.py seed_stress          # apply
    python manage.py seed_stress --undo   # remove the stress content again
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.cms.models import FooterColumn, HomeSection, MenuItem, SiteSettings, SiteText
from apps.cms.sitetext import bump_version, make_key
from apps.core.cache import bump_content_version
from apps.events.models import Category, Event, TicketType
from apps.orders.services import start_checkout
from apps.organizers.models import OrganizerProfile
from apps.payments.services import mark_succeeded, new_attempt

TAG = "[stress]"
LONG_WORD = "Supercalifragilisticexpialidocious" * 3
LONG_BN = "অতিদীর্ঘবাংলাশব্দযেটাভাঙাযায়নাসহজেইকোনোপরিস্থিতিতেই"
LONG_EN = ("The Absolutely Enormous International Music, Food, Arts, Culture and Technology Festival of Bangladesh "
           "— Grand Finale Edition With Extra Long Subtitle ") + LONG_WORD
LONG_BN_SENTENCE = ("বাংলাদেশের সবচেয়ে বড় আন্তর্জাতিক সংগীত, খাদ্য, শিল্প, সংস্কৃতি ও প্রযুক্তি উৎসব — গ্র্যান্ড ফিনালে "
                    + LONG_BN)

TEXT_OVERRIDES = {
    "Sign up": ("Create your free account now", "এখনই আপনার ফ্রি অ্যাকাউন্ট খুলুন"),
    "Continue to checkout": ("Continue securely to the checkout page and pay", "নিরাপদে চেকআউট পেজে গিয়ে পেমেন্ট করুন"),
    "Search": ("Search everything", "সবকিছু খুঁজুন"),
    "My tickets": ("My tickets and passes", "আমার টিকিট ও পাস"),
    "Featured events": ("Featured events hand-picked by our editors this week " + LONG_WORD,
                        "এই সপ্তাহে আমাদের সম্পাদকদের বাছাই করা ফিচার্ড ইভেন্ট " + LONG_BN),
    "Get in touch": ("Get in touch with our friendly support team", "আমাদের সাপোর্ট টিমের সাথে যোগাযোগ করুন"),
    "Select": ("Choose this ticket", "এই টিকিটটি বাছুন"),
    "All rights reserved.": ("All rights reserved. " + LONG_WORD, "সর্বস্বত্ব সংরক্ষিত। " + LONG_BN),
}


class Command(BaseCommand):
    help = "Worst-case content for layout testing (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--undo", action="store_true")

    def handle(self, *args, undo=False, **options):
        if not settings.DEBUG:
            raise CommandError("seed_stress only runs with DEBUG=True (never on production).")
        with transaction.atomic():
            self._undo()
            if not undo:
                self._apply()
        bump_version()
        bump_content_version()
        self.stdout.write(self.style.SUCCESS("Stress content removed." if undo else "Stress content applied."))

    def _undo(self):
        from apps.orders.models import Order
        from apps.payments.models import PaymentAttempt, Refund
        from apps.tickets.models import ScanLog, Ticket

        # Orders/tickets are protected records; remove the stress ones explicitly (dev only).
        orders = Order.objects.filter(event__slug__startswith="stress-")
        ScanLog.objects.filter(event__slug__startswith="stress-").delete()
        Refund.objects.filter(order__in=orders).delete()
        Ticket.objects.filter(order__in=orders).delete()
        PaymentAttempt.objects.filter(order__in=orders).delete()
        orders.delete()
        Event.objects.filter(slug__startswith="stress-").delete()
        OrganizerProfile.objects.filter(slug="stress-org").delete()
        User.objects.filter(email__startswith="stress-").delete()
        MenuItem.objects.filter(label__startswith=TAG).delete()
        FooterColumn.objects.filter(title__startswith=TAG).delete()
        Category.objects.filter(slug="stress-category").delete()
        for msgid in TEXT_OVERRIDES:
            SiteText.objects.filter(key=make_key(msgid)).update(text_en="", text_bn="")
        site = SiteSettings.load()
        if site.announcement_text.startswith(TAG):
            site.announcement_enabled, site.announcement_text, site.announcement_text_en = False, "", ""
            site.announcement_text_bn = ""
            site.site_name = "Nexopay"
            site.address = site.address_en = ""
            site.save()
        hero = HomeSection.objects.filter(kind="hero").first()
        if hero and hero.subtitle.startswith(TAG):
            hero.subtitle = hero.subtitle_en = hero.subtitle_bn = ""
            hero.title_en = "Tickets to *everything* worth going to."
            hero.title_bn = "সেরা সব ইভেন্টের *টিকিট*, এক জায়গায়"
            hero.save()

    def _apply(self):
        for msgid, (en, bn) in TEXT_OVERRIDES.items():
            SiteText.objects.filter(key=make_key(msgid)).update(text_en=en, text_bn=bn)

        site = SiteSettings.load()
        site.announcement_enabled = True
        site.announcement_text = site.announcement_text_en = (f"{TAG} Early-bird pricing ends tonight for every event — " + LONG_WORD)[:200]
        site.announcement_text_bn = (f"{TAG} আজ রাতেই শেষ হচ্ছে সব ইভেন্টের আর্লি-বার্ড মূল্য — " + LONG_BN)[:200]
        site.announcement_url = "/events/"
        site.address = site.address_en = ("House 1234, Road 56789, Block ZZ, Extremely Long Neighbourhood, Dhaka " + LONG_WORD)[:250]
        site.save()

        hero = HomeSection.objects.filter(kind="hero").first()
        if hero:
            hero.title_en = ("The *most unbelievably spectacular* events " + LONG_WORD)[:120]
            hero.title_bn = ("সবচেয়ে *অবিশ্বাস্য* সব ইভেন্ট " + LONG_BN)[:120]
            hero.subtitle = hero.subtitle_en = (f"{TAG} " + LONG_EN)[:250]
            hero.subtitle_bn = (f"{TAG} " + LONG_BN_SENTENCE)[:250]
            hero.save()

        for i, label in enumerate(["Concerts & Live Music", "Festivals & Fairs", "Workshops & Classes",
                                   "Conferences & Seminars", "Sports & Esports", LONG_WORD]):
            MenuItem.objects.create(location="header", label=f"{TAG} {label}"[:60], label_bn=f"{TAG} {LONG_BN}"[:60],
                                    url="/events/", sort_order=100 + i)
        for c in range(4):
            column = FooterColumn.objects.create(title=(f"{TAG} Column {c} " + LONG_WORD)[:60], title_bn=LONG_BN[:60], sort_order=100 + c)
            for i in range(6):
                MenuItem.objects.create(location="footer", column=column, label=(f"{TAG} Footer link {i} " + LONG_WORD)[:60],
                                        label_bn=LONG_BN[:60], url="https://example.com/" + LONG_WORD, sort_order=i)

        cat = Category.objects.create(name=LONG_WORD[:60], name_en=LONG_WORD[:60], name_bn=LONG_BN[:60], slug="stress-category",
                                      icon="rocket", show_in_hero=True, sort_order=99)

        user = User.objects.create_user(email="stress-organizer@example.com", password="stress12345!",
                                        full_name=("Stress Organizer " + LONG_WORD)[:150], phone="+8801999999991")
        org = OrganizerProfile.objects.create(
            user=user, name=("Stress Organizer Limited " + LONG_WORD)[:150], slug="stress-org",
            contact_email="averyveryveryverylongemailaddress." + "x" * 40 + "@example-organizer-domain.com",
            contact_phone="01999999991", about=LONG_EN, status=OrganizerProfile.Status.APPROVED,
        )
        starts = timezone.now() + timedelta(days=10)
        event = Event.objects.create(
            organizer=org, slug="stress-event", title=LONG_EN[:200], title_en=LONG_EN[:200], title_bn=LONG_BN_SENTENCE[:200],
            summary=LONG_EN[:300], summary_en=LONG_EN[:300], summary_bn=LONG_BN_SENTENCE[:300],
            description_en="<p>" + (LONG_EN + " ") * 6 + "</p><ul><li>" + LONG_WORD + "</li></ul>",
            description_bn="<p>" + (LONG_BN_SENTENCE + " ") * 6 + "</p>",
            terms_and_conditions_en="<p>" + LONG_WORD * 4 + "</p>",
            status=Event.Status.ON_SALE, featured=True, featured_rank=0, starts_at=starts,
            ends_at=starts + timedelta(hours=10), venue_name=LONG_EN[:200], venue_name_en=LONG_EN[:200],
            venue_name_bn=LONG_BN_SENTENCE[:200], venue_address=LONG_WORD, city="Dhaka " + LONG_WORD[:60],
            max_tickets_per_order=50,
        )
        event.categories.set(Category.objects.all())
        for i in range(15):
            TicketType.objects.create(
                event=event, name=(f"Tier {i} " + LONG_WORD)[: 40 + i * 5], name_bn=(f"টিয়ার {i} " + LONG_BN)[:120],
                description_en=LONG_EN, price=Decimal("1250000.50") if i % 3 == 0 else Decimal(99 * (i + 1)),
                stock=500 if i != 5 else 3, allow_quantity=i % 2 == 0, max_per_order=20, is_bundle=i == 14, sort_order=i,
            )
        Event.objects.create(organizer=org, slug="stress-no-category", title="X", title_en="X",
                             status=Event.Status.COMING_SOON, starts_at=starts)

        buyer = User.objects.create_user(email="stress-buyer@example.com", password="stress12345!",
                                         full_name=("Buyer " + LONG_WORD)[:150], phone="+8801999999992")
        free = TicketType.objects.create(event=event, name=("Free " + LONG_WORD)[:120], price=Decimal("0"), stock=10, sort_order=99)
        start_checkout(user=buyer, event=event, quantities={free.pk: 1}, buyer_name=("Buyer " + LONG_WORD)[:150],
                       buyer_phone="01999999992", delivery_email=buyer.email)
        paid_tt = event.ticket_types.get(sort_order=2)  # allows quantity
        order = start_checkout(user=buyer, event=event, quantities={paid_tt.pk: 3}, buyer_name="Buyer",
                               buyer_phone="01999999992", delivery_email=buyer.email)
        mark_succeeded(new_attempt(order, "mock"), "STRESS-1")
        self.stdout.write(f"Stress category id={cat.pk}; buyer stress-buyer@example.com / stress12345!")
