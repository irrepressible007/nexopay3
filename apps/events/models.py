from decimal import Decimal

from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.core.security import validate_artwork
from apps.core.utils import sanitize_html

hex_color = RegexValidator(r"^#[0-9A-Fa-f]{6}$", _("Use a hex colour like #A855F7."))

ICON_CHOICES = [
    (name, name.replace("-", " ").title())
    for name in (
        "ticket", "festival", "mic", "music", "headphones", "trophy", "ball", "podium", "tools", "film",
        "party", "frame", "book", "sparkles", "smile", "shirt", "heart", "users", "rocket", "star", "flame",
        "globe", "building", "calendar", "zap", "phone-device", "pin", "chart",
    )
]


class Category(models.Model):
    """Fixed, admin-managed taxonomy. Organizers pick from it; they never create it."""

    name = models.CharField(_("name"), max_length=60)
    slug = models.SlugField(max_length=70, unique=True)
    icon = models.CharField(_("icon"), max_length=40, choices=ICON_CHOICES, default="ticket")
    icon_image = models.FileField(
        _("custom icon"), upload_to="categories/", blank=True, validators=[validate_artwork],
        help_text=_("Optional SVG/PNG. Replaces the built-in icon."),
    )
    accent_color = models.CharField(_("accent colour"), max_length=7, default="#A855F7", validators=[hex_color])
    sort_order = models.PositiveSmallIntegerField(default=0)
    show_on_home = models.BooleanField(_("show in homepage grid"), default=True)
    show_in_hero = models.BooleanField(_("show as quick link in the hero"), default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("category")
        verbose_name_plural = _("categories")
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


def event_banner_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"org/{instance.organizer_id}/event/{instance.slug}/banner-{timezone.now():%Y%m%d%H%M%S}.{ext}"


class EventQuerySet(models.QuerySet):
    PUBLIC_STATUSES = ("coming_soon", "on_sale", "sold_out", "ended")

    def public(self):
        return self.filter(status__in=self.PUBLIC_STATUSES)

    def live(self):
        return self.filter(status__in=("on_sale", "sold_out"))

    def upcoming(self):
        return self.filter(status="coming_soon")

    def featured(self):
        return self.public().filter(featured=True).exclude(status="ended")


class Event(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        COMING_SOON = "coming_soon", _("Coming soon")
        ON_SALE = "on_sale", _("On sale")
        SOLD_OUT = "sold_out", _("Sold out")
        ENDED = "ended", _("Ended")
        CANCELLED = "cancelled", _("Cancelled")

    organizer = models.ForeignKey("organizers.OrganizerProfile", on_delete=models.PROTECT, related_name="events")
    title = models.CharField(_("title"), max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    summary = models.CharField(_("short summary"), max_length=300, blank=True)
    description = models.TextField(_("description"), blank=True)
    terms_and_conditions = models.TextField(_("event terms & conditions"), blank=True)
    categories = models.ManyToManyField(Category, related_name="events", verbose_name=_("categories"))

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    featured = models.BooleanField(
        _("featured"), default=False, help_text=_("Editorial promotion; independent of status.")
    )
    featured_rank = models.PositiveSmallIntegerField(default=0, help_text=_("Lower shows first."))

    starts_at = models.DateTimeField(_("starts at"))
    ends_at = models.DateTimeField(_("ends at"), null=True, blank=True)
    sales_start_at = models.DateTimeField(_("ticket sales open"), null=True, blank=True)
    sales_end_at = models.DateTimeField(_("ticket sales close"), null=True, blank=True)

    venue_name = models.CharField(_("venue"), max_length=200, blank=True)
    venue_address = models.CharField(_("venue address"), max_length=300, blank=True)
    city = models.CharField(_("city"), max_length=80, default="Dhaka")
    map_url = models.URLField(_("map link"), blank=True)
    is_online = models.BooleanField(_("online event"), default=False)

    banner = models.ImageField(_("banner image"), upload_to=event_banner_path, blank=True)
    banner_renditions = models.JSONField(default=dict, blank=True, editable=False)
    max_tickets_per_order = models.PositiveSmallIntegerField(default=10)
    published_at = models.DateTimeField(null=True, blank=True)

    objects = EventQuerySet.as_manager()

    class Meta:
        verbose_name = _("event")
        verbose_name_plural = _("events")
        ordering = ["starts_at"]
        indexes = [
            models.Index(fields=["status", "starts_at"]),
            models.Index(fields=["featured", "featured_rank"]),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("events:detail", kwargs={"slug": self.slug})

    def save(self, *args, **kwargs):
        # Sanitize every language variant of the rich-text fields.
        for field in ("description", "terms_and_conditions"):
            for attr in [field] + [f"{field}_{code}" for code in ("en", "bn")]:
                if hasattr(self, attr):
                    setattr(self, attr, sanitize_html(getattr(self, attr)))
        if self.status != self.Status.DRAFT and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    # --- state helpers -----------------------------------------------------------
    @property
    def place(self) -> str:
        """Where it happens, for display: the venue, "Online", or at least the city (never a wrong "Online")."""
        if self.venue_name:
            return self.venue_name
        return str(_("Online")) if self.is_online else self.city

    @property
    def is_multi_day(self) -> bool:
        if not self.ends_at:
            return False
        return timezone.localtime(self.ends_at).date() != timezone.localtime(self.starts_at).date()

    @property
    def is_purchasable(self) -> bool:
        if self.status != self.Status.ON_SALE:
            return False
        now = timezone.now()
        if self.sales_start_at and now < self.sales_start_at:
            return False
        if self.sales_end_at and now > self.sales_end_at:
            return False
        return True

    @property
    def is_past(self) -> bool:
        return (self.ends_at or self.starts_at) < timezone.now()

    def min_price(self):
        prices = [t.price for t in self.ticket_types.all() if t.is_available]
        return min(prices) if prices else None

    def refresh_sold_out_status(self, save=True):
        """Flip between on_sale and sold_out based on per-ticket-type stock."""
        if self.status not in (self.Status.ON_SALE, self.Status.SOLD_OUT):
            return
        types = list(self.ticket_types.filter(is_available=True))
        all_gone = bool(types) and all(t.remaining <= 0 for t in types)
        new_status = self.Status.SOLD_OUT if all_gone else self.Status.ON_SALE
        if new_status != self.status:
            self.status = new_status
            if save:
                self.save(update_fields=["status", "updated_at"])


class TicketType(models.Model):
    """
    One purchasable product of an event. Stock is tracked here — never on the
    Event — so a single segment can sell out while others stay on sale.
    """

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="ticket_types")
    name = models.CharField(_("name"), max_length=120)
    description = models.TextField(_("what's included"), blank=True)
    price = models.DecimalField(
        _("price (BDT)"), max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0"))]
    )
    stock = models.PositiveIntegerField(_("total quantity"))
    sold_count = models.PositiveIntegerField(default=0, editable=False)
    held_count = models.PositiveIntegerField(default=0, editable=False)
    is_available = models.BooleanField(_("available for sale"), default=True)
    is_bundle = models.BooleanField(
        _("all-access bundle"), default=False, help_text=_("Highlight as the all-inclusive tier.")
    )
    allow_quantity = models.BooleanField(
        _("allow buying more than one"),
        default=False,
        help_text=_("By default one email/phone can buy this ticket only once."),
    )
    max_per_order = models.PositiveSmallIntegerField(_("max per order"), default=10)
    sales_start_at = models.DateTimeField(null=True, blank=True)
    sales_end_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _("ticket type")
        verbose_name_plural = _("ticket types")
        ordering = ["sort_order", "price"]
        constraints = [
            models.CheckConstraint(
                condition=Q(sold_count__lte=F("stock") - F("held_count")),
                name="tickettype_no_oversell",
            ),
        ]

    def __str__(self):
        return f"{self.event} — {self.name}"

    @property
    def remaining(self) -> int:
        return max(self.stock - self.sold_count - self.held_count, 0)

    @property
    def effective_max_per_order(self) -> int:
        return self.max_per_order if self.allow_quantity else 1

    @property
    def is_on_sale_now(self) -> bool:
        now = timezone.now()
        if self.sales_start_at and now < self.sales_start_at:
            return False
        if self.sales_end_at and now > self.sales_end_at:
            return False
        return self.is_available

    @property
    def availability(self) -> str:
        """One of: available, low, sold_out, closed."""
        if not self.is_on_sale_now:
            return "closed"
        remaining = self.remaining
        if remaining <= 0:
            return "sold_out"
        if remaining <= max(5, self.stock // 10):
            return "low"
        return "available"
