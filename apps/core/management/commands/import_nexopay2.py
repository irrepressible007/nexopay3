"""
Bring accounts, the past event(s), pages and partner logos over from Nexopay 2 (the
Laravel site that ran on nexopay.com.bd). Run on the server; it only ever reads the
old database (read-only session), using the login in Nexopay 2's own .env, which is
never printed.

    python manage.py import_nexopay2                       # dry run: what would come over
    python manage.py import_nexopay2 --venue "BUET, Dhaka" # venue for the old event(s)
    python manage.py import_nexopay2 --yes                 # do it

Safe to run again: anything already here (same email / event address / page address /
partner name) is skipped, never overwritten.

  accounts  same email and password (Laravel bcrypt; re-saved in our format at first login).
            Verified emails stay verified. Old Admin/Finance roles are NOT given staff rights
            here: they're listed, so you can add them to a staff role yourself.
  events    as ended events (still-upcoming ones as drafts) under the house organizer, with
            their description, cover image and old address (so /event/<slug> links land there).
  pages     with their old addresses (/p/<slug>, same as before). Existing ones are kept.
  partners  name, logo and link.
Registrations are not moved (decided 2026-10-02); they stay in the old database.
"""
import re
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import slugify

from apps.cms.models import Page, Partner, SiteSettings
from apps.core.security import validate_artwork
from apps.core.utils import normalize_phone
from apps.events.models import Category, Event
from apps.organizers.models import OrganizerProfile

LARAVEL_BCRYPT = re.compile(r"^\$2[aby]\$\d\d\$[./A-Za-z0-9]{53}$")
PHONE_KEYS = re.compile(r"phone|mobile|contact|whatsapp|number", re.I)
CATEGORY_HINTS = [  # (words in the title/description, our category slug)
    (r"olympiad|competition|contest|hackathon|quiz|championship", "competitions"),
    (r"festival|carnival|fest\b|mela", "festivals"),
    (r"workshop|bootcamp|training|masterclass", "workshops"),
    (r"seminar|talk|lecture", "seminars"),
    (r"conference|summit|symposium", "conferences"),
    (r"concert|live music|gig", "concert"),
    (r"exhibition|expo|fair\b|showcase", "exhibitions"),
]


# --- reading Nexopay 2 ------------------------------------------------------------------------
def read_laravel_env(path: Path) -> dict:
    values = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        values[key.strip()] = value
    return values


class LegacyDatabase:
    """Read-only access to Nexopay 2's MySQL/MariaDB database and its uploaded files."""

    def __init__(self, env_path: Path, storage_root: Path):
        if not env_path.exists():
            raise CommandError(f"Nexopay 2's settings file was not found at {env_path} (use --source-env).")
        env = read_laravel_env(env_path)
        try:
            import MySQLdb as driver
        except ImportError:
            import pymysql as driver
        try:
            self.conn = driver.connect(
                host=env.get("DB_HOST", "localhost") or "localhost", port=int(env.get("DB_PORT") or 3306),
                user=env.get("DB_USERNAME", ""), password=env.get("DB_PASSWORD", ""),
                database=env.get("DB_DATABASE", ""), charset="utf8mb4",
            )
        except Exception as exc:  # never echo the connection settings
            raise CommandError(f"Couldn't open Nexopay 2's database ({type(exc).__name__}).") from None
        self.database = env.get("DB_DATABASE", "")
        self.storage_root = storage_root
        with self.conn.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")  # this import can't change anything there

    def _rows(self, sql):
        with self.conn.cursor() as cursor:
            cursor.execute(sql)
            names = [col[0] for col in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]

    def _has_column(self, table, column):
        with self.conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s",
                (self.database, table, column),
            )
            return cursor.fetchone()[0] > 0

    def users(self):
        where = "WHERE deleted_at IS NULL" if self._has_column("users", "deleted_at") else ""
        return self._rows(f"SELECT * FROM users {where} ORDER BY id")

    def events(self):
        return self._rows("SELECT * FROM events ORDER BY id")

    def pages(self):
        return self._rows("SELECT * FROM pages ORDER BY id")

    def partners(self):
        return self._rows("SELECT * FROM partners ORDER BY id")

    def read_file(self, stored_path):
        """Bytes of a file the old site stored on its public disk, or None."""
        if not stored_path:
            return None
        rel = str(stored_path).strip().split("?", 1)[0]
        rel = re.sub(r"^(https?://[^/]+)?/?(storage/)?", "", rel)
        path = (self.storage_root / rel).resolve()
        if self.storage_root.resolve() not in path.parents or not path.is_file():
            return None
        return path.read_bytes()


# --- the command ------------------------------------------------------------------------------
class Command(BaseCommand):
    help = "Bring accounts, past events, pages and partners over from Nexopay 2 (dry run unless --yes)."

    def add_arguments(self, parser):
        home = Path.home()
        parser.add_argument("--source-env", default=str(home / "nexopay2" / ".env"),
                            help="Nexopay 2's .env (default ~/nexopay2/.env)")
        parser.add_argument("--storage", default=str(home / "nexopay2" / "storage" / "app" / "public"),
                            help="Nexopay 2's uploaded files (default ~/nexopay2/storage/app/public)")
        parser.add_argument("--venue", default="", help="Venue to show on the imported event(s), e.g. \"BUET, Dhaka\"")
        parser.add_argument("--yes", action="store_true", help="Actually import (default: only show).")

    def get_source(self, options):  # tests replace this
        return LegacyDatabase(Path(options["source_env"]).expanduser(), Path(options["storage"]).expanduser())

    def handle(self, *args, **options):
        source = self.get_source(options)
        self.source, self.yes, self.venue = source, options["yes"], options["venue"].strip()
        self.report = []
        plan = {
            "users": self.plan_users(source.users()),
            "events": self.plan_events(source.events()),
            "pages": self.plan_pages(source.pages()),
            "partners": self.plan_partners(source.partners()),
        }
        self.print_plan(plan)
        if not self.yes:
            self.stdout.write("\nNothing was changed. Run again with --yes to import.")
            return
        with transaction.atomic():
            counts = {
                "accounts": self.import_users(plan["users"]["new"]),
                "events": self.import_events(plan["events"]["new"]),
                "pages": self.import_pages(plan["pages"]["new"]),
                "partners": self.import_partners(plan["partners"]["new"]),
            }
        for line in self.report:
            self.stdout.write(self.style.WARNING(f"  ! {line}"))
        self.stdout.write(self.style.SUCCESS(
            "\n✓ Imported " + ", ".join(f"{n} {label}" for label, n in counts.items())
        ))

    # --- accounts ------------------------------------------------------------------------
    def plan_users(self, rows):
        User = get_user_model()
        existing = set(User.objects.values_list("email", flat=True))
        taken_phones = set(User.objects.exclude(phone=None).values_list("phone", flat=True))
        new, skipped, staff_roles, seen = [], [], [], set()
        for row in rows:
            email = (row.get("email") or "").strip().lower()
            if not email or "@" not in email:
                continue
            if email in existing or email in seen:
                skipped.append(email)
                continue
            seen.add(email)
            phone = self.phone_from_profile(row.get("profile_data"))
            if phone and phone in taken_phones:
                phone = None
            if phone:
                taken_phones.add(phone)
            role = (row.get("global_role") or "").strip()
            if role.lower() in ("admin", "finance"):
                staff_roles.append(f"{email} ({role})")
            new.append({**row, "_email": email, "_phone": phone})
        return {"new": new, "skipped": skipped, "staff_roles": staff_roles}

    @staticmethod
    def phone_from_profile(profile):
        import json

        if isinstance(profile, (bytes, str)):
            try:
                profile = json.loads(profile or "{}")
            except ValueError:
                return None
        if not isinstance(profile, dict):
            return None
        for key, value in profile.items():
            if PHONE_KEYS.search(str(key)) and isinstance(value, (str, int)):
                try:
                    return normalize_phone(str(value))
                except ValidationError:
                    continue
        return None

    def import_users(self, rows):
        from allauth.account.models import EmailAddress

        User = get_user_model()
        for row in rows:
            hashed = (row.get("password") or "").strip()
            user = User(
                email=row["_email"], full_name=(row.get("name") or "")[:150], phone=row["_phone"],
                date_joined=self.aware(row.get("created_at")) or timezone.now(),
            )
            if LARAVEL_BCRYPT.match(hashed):
                user.password = "bcrypt$" + hashed  # Django's BCryptPasswordHasher reads Laravel's hash as is
            else:
                user.set_unusable_password()
            user.save()
            EmailAddress.objects.create(user=user, email=user.email, primary=True,
                                        verified=bool(row.get("email_verified_at")))
        return len(rows)

    # --- events --------------------------------------------------------------------------
    def plan_events(self, rows):
        existing = set(Event.objects.values_list("slug", flat=True))
        new, skipped = [], []
        for row in rows:
            slug = slugify(row.get("slug") or row.get("title") or "")[:220] or f"nexopay2-event-{row['id']}"
            if slug in existing:
                skipped.append(slug)
                continue
            if (row.get("status") or "") == "draft":
                continue
            new.append({**row, "_slug": slug})
        return {"new": new, "skipped": skipped}

    def house_organizer(self):
        """Old Nexopay 2 events were run by Nexopay itself: file them under the site owner's organizer profile."""
        User = get_user_model()
        owner = User.objects.filter(is_superuser=True).order_by("date_joined", "pk").first()
        if owner is None:
            raise CommandError("No superuser exists to own the imported events.")
        profile = getattr(owner, "organizer_profile", None)
        if profile is None:
            site = SiteSettings.load()
            base = slugify(site.site_name) or "nexopay"
            slug, n = base, 2
            while OrganizerProfile.objects.filter(slug=slug).exists():
                slug, n = f"{base}-{n}", n + 1
            profile = OrganizerProfile.objects.create(
                user=owner, name=site.site_name or "Nexopay", slug=slug, status=OrganizerProfile.Status.APPROVED,
                contact_email=site.contact_email or owner.email, contact_phone=site.contact_phone or "",
                reviewed_at=timezone.now(), reviewed_by=owner,
            )
        return profile

    def import_events(self, rows):
        if not rows:
            return 0
        organizer = self.house_organizer()
        now = timezone.now()
        for row in rows:
            starts = self.aware(row.get("start_date")) or self.aware(row.get("created_at")) or now
            ends = self.aware(row.get("end_date"))
            description = row.get("description") or ""
            extra = row.get("short_description") or ""
            if extra and strip_tags(extra).strip() and strip_tags(extra).strip()[:80] not in strip_tags(description):
                description = f"{description}\n{extra}"
            event = Event(
                organizer=organizer, slug=row["_slug"], title=(row.get("title") or row["_slug"])[:200],
                description=description, starts_at=starts, ends_at=ends,
                status=Event.Status.ENDED if (ends or starts) < now else Event.Status.DRAFT,
                venue_name=self.venue[:200], city="Dhaka",
            )
            event.save()
            text = f"{event.title} {strip_tags(description)}".lower()
            slugs = [slug for pattern, slug in CATEGORY_HINTS if re.search(pattern, text)]
            event.categories.set(Category.objects.filter(slug__in=slugs))
            cover = self.source.read_file(row.get("cover_image"))
            if cover and self.is_image(cover):
                event.banner.save(Path(str(row["cover_image"])).name, ContentFile(cover), save=True)
            elif row.get("cover_image"):
                self.report.append(f"cover image missing for event {event.slug}: {row.get('cover_image')}")
        return len(rows)

    # --- pages & partners ----------------------------------------------------------------
    def plan_pages(self, rows):
        existing = set(Page.objects.values_list("slug", flat=True))
        new, skipped = [], []
        for row in rows:
            slug = slugify(row.get("slug") or row.get("title") or "")[:80]
            if not slug:
                continue
            (skipped if slug in existing else new).append({**row, "_slug": slug})
        return {"new": new, "skipped": [r["_slug"] for r in skipped]}

    def import_pages(self, rows):
        for i, row in enumerate(rows):
            Page.objects.create(slug=row["_slug"], title=(row.get("title") or row["_slug"])[:150],
                                body=row.get("content") or "", is_published=bool(row.get("is_published", True)),
                                sort_order=100 + i)
        return len(rows)

    def plan_partners(self, rows):
        existing = {n.lower() for n in Partner.objects.values_list("name", flat=True)}
        new, skipped = [], []
        for row in rows:
            name = (row.get("name") or "").strip()[:100]
            if not name:
                continue
            (skipped if name.lower() in existing else new).append({**row, "_name": name})
        return {"new": new, "skipped": [r["_name"] for r in skipped]}

    def import_partners(self, rows):
        count = 0
        for i, row in enumerate(rows):
            data = self.source.read_file(row.get("logo_image"))
            if not data:
                self.report.append(f"partner '{row['_name']}' skipped: logo file missing ({row.get('logo_image')})")
                continue
            upload = ContentFile(data, name=Path(str(row["logo_image"])).name)
            try:
                validate_artwork(upload)
            except ValidationError as exc:
                self.report.append(f"partner '{row['_name']}' skipped: {' '.join(exc.messages)}")
                continue
            url = (row.get("destination_url") or "").strip()
            partner = Partner(name=row["_name"], url=url if urlparse(url).scheme in ("http", "https") else "",
                              is_enabled=bool(row.get("is_active", True)), sort_order=100 + i)
            partner.logo.save(upload.name, upload, save=True)
            count += 1
        return count

    # --- helpers -------------------------------------------------------------------------
    def is_image(self, data: bytes) -> bool:
        from io import BytesIO

        from PIL import Image

        from apps.core.security import too_many_pixels

        try:
            with Image.open(BytesIO(data)) as img:
                size = img.size
                img.verify()
        except Exception:
            self.report.append("an old cover file isn't a readable image - skipped")
            return False
        if too_many_pixels(*size):
            self.report.append(f"an old cover image is too large ({size[0]}x{size[1]}) - skipped")
            return False
        return True

    @staticmethod
    def aware(value):
        """Laravel stored UTC wall-clock times (config/app.php timezone = UTC)."""
        if not value:
            return None
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", ""))
        return value if timezone.is_aware(value) else value.replace(tzinfo=dt_timezone.utc)

    def print_plan(self, plan):
        w = self.stdout.write
        users, events, pages, partners = plan["users"], plan["events"], plan["pages"], plan["partners"]
        verified = sum(1 for u in users["new"] if u.get("email_verified_at"))
        keep_pw = sum(1 for u in users["new"] if LARAVEL_BCRYPT.match((u.get("password") or "").strip()))
        w(self.style.MIGRATE_HEADING("Will import:" if self.yes else "Would import (dry run, nothing changed):"))
        w(f"  {len(users['new']):>5}  accounts  ({verified} with verified email, {keep_pw} keep their password, "
          f"{sum(1 for u in users['new'] if u['_phone'])} with a mobile number)")
        w(f"  {len(events['new']):>5}  events    " + ", ".join(e["_slug"] for e in events["new"]))
        w(f"  {len(pages['new']):>5}  pages     " + ", ".join(p["_slug"] for p in pages["new"]))
        w(f"  {len(partners['new']):>5}  partners  " + ", ".join(p["_name"] for p in partners["new"]))
        if self.venue:
            w(f"         venue for the events: {self.venue}")
        elif events["new"]:
            w("         no --venue given: the event page will show the city (Dhaka) as the place")
        skipped = [("accounts already here", users["skipped"]), ("events already here", events["skipped"]),
                   ("pages already here (kept as they are)", pages["skipped"]),
                   ("partners already here", partners["skipped"])]
        for label, items in skipped:
            if items:
                w(f"  skipped, {label}: " + ", ".join(items[:20]) + (" …" if len(items) > 20 else ""))
        if users["staff_roles"]:
            w(self.style.WARNING("  had Admin/Finance rights on the old site (imported as normal accounts; "
                                 "add them to a staff role yourself if they should have one):"))
            for line in users["staff_roles"]:
                w(f"      {line}")
