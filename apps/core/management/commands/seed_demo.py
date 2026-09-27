"""
Populate a development/staging database with realistic demo content.

    python manage.py seed_demo            # add demo data (idempotent)
    python manage.py seed_demo --reset    # delete demo events first
"""
import io
import math
import random
from datetime import timedelta
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFilter

from apps.accounts.models import User
from apps.events.models import Category, Event, TicketType
from apps.organizers.models import OrganizerProfile
from apps.payments.models import PaymentProviderSetting

PALETTES = [
    ("#A855F7", "#EC4899", "#22D3EE"),
    ("#F97316", "#EF4444", "#FACC15"),
    ("#22D3EE", "#3B82F6", "#A855F7"),
    ("#10B981", "#22D3EE", "#6366F1"),
    ("#EC4899", "#F59E0B", "#8B5CF6"),
    ("#6366F1", "#EC4899", "#F43F5E"),
]

# title_en, title_bn, categories, days_from_now, status, featured, venue, ticket spec
DEMO_EVENTS = [
    ("Neon Nights — Live in Dhaka", "নিয়ন নাইটস — লাইভ ইন ঢাকা", ["concert", "music"], 12, "on_sale", True,
     "International Convention City Bashundhara", [("General Admission", 1500, 800), ("VIP Standing", 3500, 150), ("Platinum Lounge", 8000, 40)]),
    ("Kpop Fiesta Bangladesh 2026", "কে-পপ ফিয়েস্তা বাংলাদেশ ২০২৬", ["competitions", "pop-culture", "festivals"], 20, "on_sale", True,
     "Shilpakala Academy, Dhaka", "kpop"),
    ("Dhaka Winter Food & Music Festival", "ঢাকা উইন্টার ফুড অ্যান্ড মিউজিক ফেস্টিভ্যাল", ["festivals", "music"], 30, "on_sale", True,
     "Army Stadium", [("Day Pass", 400, 3000), ("Weekend Pass", 700, 1500)]),
    ("Laugh Riot: Stand-up Night", "লাফ রায়ট: স্ট্যান্ড-আপ নাইট", ["stand-up"], 6, "on_sale", False,
     "Jatra Biroti, Banani", [("Entry", 800, 120)]),
    ("Texture by the Sea — Pottery Workshop", "টেক্সচার বাই দ্য সি — মৃৎশিল্প কর্মশালা", ["workshops"], 9, "on_sale", False,
     "Inani Beach Studio, Cox's Bazar", [("Workshop Seat", 1950, 18)]),
    ("Best of ASCO & MOSB Congress 2026", "বেস্ট অফ এএসসিও কংগ্রেস ২০২৬", ["conferences", "seminars"], 40, "coming_soon", False,
     "Pan Pacific Sonargaon", [("Delegate", 2000, 400)]),
    ("JnU Esports Carnival", "জবি ইস্পোর্টস কার্নিভাল", ["sports", "competitions"], 15, "on_sale", False,
     "Jagannath University", [("Team Entry", 100, 300)]),
    ("Cine Totem Screen: Classics Week", "সিনে টোটেম স্ক্রিন: ক্লাসিকস উইক", ["movie-drama"], 4, "on_sale", False,
     "Alliance Française de Dhaka", [("Screening Pass", 250, 90)]),
    ("Emira — The Wedding Chapter", "এমিরা — দ্য ওয়েডিং চ্যাপ্টার", ["exhibitions"], 18, "on_sale", False,
     "Radisson Blu Water Garden", [("Visitor Pass", 0, 2000)]),
    ("Rooftop Groove: Sunset Party", "রুফটপ গ্রুভ: সানসেট পার্টি", ["party", "music"], 25, "coming_soon", False,
     "Gulshan Rooftop", [("Entry", 1200, 200)]),
    ("Monsoon Echoes Unplugged", "মনসুন একোস আনপ্লাগড", ["music", "concert"], -20, "ended", False,
     "Bengal Shilpalay", [("Entry", 700, 150)]),
]

KPOP_TIERS = [
    ("Entry Ticket", 120, False), ("Entry + Dance", 200, False), ("Entry + Singing", 200, False),
    ("Entry + Quiz", 150, False), ("Entry + Drawing", 150, False), ("Entry + Mystery Solve", 180, False),
    ("Entry + Video Editing", 180, False), ("Entry + Entertainment (Stand-up / Jokes)", 180, False),
    ("Golden Ticket — all segments", 600, True),
]


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def make_banner(seed: int, palette) -> bytes:
    """Abstract, concert-poster style gradient art (no external assets needed)."""
    rnd = random.Random(seed)
    w, h = 1600, 900
    img = Image.new("RGB", (w, h), (8, 7, 12))
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(glow)
    for i in range(7):
        color = _hex(palette[i % 3])
        r = rnd.randint(220, 520)
        x, y = rnd.randint(-100, w + 100), rnd.randint(-100, h + 100)
        d.ellipse((x - r, y - r, x + r, y + r), fill=color)
    glow = glow.filter(ImageFilter.GaussianBlur(150))
    img = Image.blend(img, glow, 0.85)
    lines = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lines)
    for k in range(26):
        amp, freq, phase = rnd.randint(30, 120), rnd.uniform(0.002, 0.006), rnd.uniform(0, math.pi * 2)
        y0 = h * 0.35 + k * 14
        pts = [(x, y0 + amp * math.sin(freq * x + phase)) for x in range(0, w + 20, 20)]
        ld.line(pts, fill=(255, 255, 255, 26), width=2)
    img = Image.alpha_composite(img.convert("RGBA"), lines).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=86)
    return buf.getvalue()


class Command(BaseCommand):
    help = "Create demo organizer, events and ticket types."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true")

    @transaction.atomic
    def handle(self, *args, reset=False, **options):
        user, _ = User.objects.get_or_create(
            email="demo-organizer@nexopay.com.bd", defaults={"full_name": "Demo Organizer", "phone": "+8801700000001"}
        )
        user.set_password("demo12345!")
        user.save()
        org, _ = OrganizerProfile.objects.update_or_create(
            user=user,
            defaults={
                "name": "Pulse Live BD",
                "slug": "pulse-live-bd",
                "contact_email": "hello@pulselive.example",
                "contact_phone": "01700000001",
                "about": "Live music, festivals and culture across Bangladesh.",
                "status": OrganizerProfile.Status.APPROVED,
            },
        )
        if reset:
            Event.objects.filter(organizer=org).delete()

        now = timezone.localtime().replace(hour=19, minute=0, second=0, microsecond=0)
        for idx, (title, title_bn, cats, days, status, featured, venue, tiers) in enumerate(DEMO_EVENTS):
            slug = f"demo-{idx + 1}-" + "".join(ch if ch.isalnum() else "-" for ch in title.lower())[:50].strip("-")
            event, created = Event.objects.get_or_create(
                slug=slug,
                defaults={
                    "organizer": org,
                    "title": title, "title_en": title, "title_bn": title_bn,
                    "summary": f"{title} — an unforgettable experience you don't want to miss.",
                    "summary_en": f"{title} — an unforgettable experience you don't want to miss.",
                    "description_en": "<p>Join us for a night to remember. Doors open one hour before showtime.</p>"
                                      "<ul><li>Bring a valid photo ID</li><li>No outside food or drinks</li><li>Kids under 5 enter free</li></ul>",
                    "terms_and_conditions_en": "<p>Tickets are non-transferable once scanned. The organizer reserves the right of admission.</p>",
                    "status": status,
                    "featured": featured,
                    "featured_rank": idx,
                    "starts_at": now + timedelta(days=days),
                    "sales_start_at": now + timedelta(days=3) if status == "coming_soon" else None,
                    "venue_name": venue, "venue_name_en": venue,
                    "city": "Dhaka" if "Cox" not in venue else "Cox's Bazar",
                },
            )
            if not created:
                continue
            event.categories.set(Category.objects.filter(slug__in=cats))
            event.banner.save(f"banner-{idx}.jpg", ContentFile(make_banner(idx * 7 + 3, PALETTES[idx % len(PALETTES)])))
            if tiers == "kpop":
                for order, (name, price, bundle) in enumerate(KPOP_TIERS):
                    TicketType.objects.create(
                        event=event, name=name, name_en=name, price=Decimal(price), stock=150 if not bundle else 60,
                        is_bundle=bundle, sort_order=order,
                        description_en=(
                            "Main venue access plus every competition segment" if bundle
                            else "Main venue access" + ("" if name == "Entry Ticket" else " plus this segment")
                        ),
                    )
            else:
                for order, (name, price, stock) in enumerate(tiers):
                    TicketType.objects.create(
                        event=event, name=name, name_en=name, price=Decimal(price), stock=stock, sort_order=order,
                        allow_quantity=price > 0 and stock > 100, max_per_order=6,
                    )
            self.stdout.write(f"  + {title}")

        PaymentProviderSetting.objects.filter(provider="mock").update(is_enabled=True)
        self.stdout.write(self.style.SUCCESS("Demo data ready. Organizer login: demo-organizer@nexopay.com.bd / demo12345!"))
