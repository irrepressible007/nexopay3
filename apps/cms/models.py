from decimal import Decimal

from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.utils import sanitize_html
from apps.events.models import hex_color

PERCENT = [MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))]
SITE_SETTINGS_CACHE_KEY = "cms:site-settings"


class ScheduledQuerySet(models.QuerySet):
    def visible(self):
        now = timezone.now()
        return self.filter(is_enabled=True).filter(
            Q(starts_at__isnull=True) | Q(starts_at__lte=now),
            Q(ends_at__isnull=True) | Q(ends_at__gte=now),
        )


class SiteSettings(models.Model):
    """Singleton holding everything an admin can change about the site without a deploy."""

    site_name = models.CharField(max_length=60, default="Nexopay")
    tagline = models.CharField(max_length=160, default="Tickets to everything worth going to")
    logo = models.FileField(upload_to="site/", blank=True, help_text=_("SVG or PNG, shown on dark backgrounds."))
    logo_on_light = models.FileField(upload_to="site/", blank=True, help_text=_("Used in emails and PDF tickets."))
    favicon = models.FileField(upload_to="site/", blank=True)
    og_image = models.ImageField(upload_to="site/", blank=True, help_text=_("Default social share image."))

    # Brand colours → CSS custom properties.
    primary_color = models.CharField(max_length=7, default="#A855F7", validators=[hex_color])
    secondary_color = models.CharField(max_length=7, default="#EC4899", validators=[hex_color])
    accent_color = models.CharField(max_length=7, default="#22D3EE", validators=[hex_color])
    background_color = models.CharField(max_length=7, default="#07060B", validators=[hex_color])

    contact_email = models.EmailField(default="support@nexopay.com.bd")
    contact_phone = models.CharField(max_length=30, blank=True)
    address = models.CharField(max_length=250, blank=True)
    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)
    tiktok_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)
    footer_text = models.CharField(max_length=300, blank=True)
    meta_description = models.CharField(max_length=300, blank=True)

    announcement_enabled = models.BooleanField(default=False)
    announcement_text = models.CharField(max_length=200, blank=True)
    announcement_url = models.CharField(max_length=300, blank=True)

    # Platform-default fees (organizers can be overridden individually).
    default_commission_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"), validators=PERCENT)
    default_buyer_fee_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"), validators=PERCENT)
    default_buyer_fee_flat = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))

    maintenance_mode = models.BooleanField(default=False, help_text=_("Show a maintenance page to non-staff visitors."))

    class Meta:
        verbose_name = _("site settings")
        verbose_name_plural = _("site settings")

    def __str__(self):
        return "Site settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(SITE_SETTINGS_CACHE_KEY)

    def delete(self, *args, **kwargs):  # the singleton cannot be deleted
        return

    @classmethod
    def load(cls) -> "SiteSettings":
        obj = cache.get(SITE_SETTINGS_CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(SITE_SETTINGS_CACHE_KEY, obj, 3600)
        return obj


class HomeSection(models.Model):
    """An ordered, schedulable block of the homepage — the homepage builder."""

    class Kind(models.TextChoices):
        HERO = "hero", _("Hero slider")
        FEATURED = "featured", _("Featured events carousel")
        CATEGORIES = "categories", _("Category grid")
        THIS_WEEK = "this_week", _("Happening this week")
        UPCOMING = "upcoming", _("Coming soon")
        JUST_ANNOUNCED = "just_announced", _("Just announced")
        CATEGORY_SPOTLIGHT = "category_spotlight", _("Category spotlight")
        PROMO_BANNER = "promo_banner", _("Promo banner")
        ORGANIZER_CTA = "organizer_cta", _("'List your event' call to action")
        PARTNERS = "partners", _("Partner logos")
        FAQ = "faq", _("FAQ teaser")

    kind = models.CharField(max_length=30, choices=Kind.choices)
    title = models.CharField(max_length=120, blank=True)
    subtitle = models.CharField(max_length=250, blank=True)
    category = models.ForeignKey(
        "events.Category", null=True, blank=True, on_delete=models.SET_NULL,
        help_text=_("Only for 'Category spotlight'."),
    )
    image = models.ImageField(upload_to="home/", blank=True, help_text=_("Only for 'Promo banner'."))
    link_url = models.CharField(max_length=300, blank=True)
    cta_label = models.CharField(max_length=60, blank=True)
    item_limit = models.PositiveSmallIntegerField(default=8)
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    is_enabled = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    objects = ScheduledQuerySet.as_manager()

    class Meta:
        verbose_name = _("homepage section")
        verbose_name_plural = _("homepage sections")
        ordering = ["sort_order"]

    def __str__(self):
        return self.title or self.get_kind_display()


class HeroSlide(models.Model):
    title = models.CharField(max_length=120)
    subtitle = models.CharField(max_length=250, blank=True)
    image = models.ImageField(upload_to="home/hero/")
    mobile_image = models.ImageField(upload_to="home/hero/", blank=True)
    image_renditions = models.JSONField(default=dict, blank=True, editable=False)
    event = models.ForeignKey("events.Event", null=True, blank=True, on_delete=models.SET_NULL)
    cta_label = models.CharField(max_length=60, blank=True)
    cta_url = models.CharField(max_length=300, blank=True, help_text=_("Leave blank to link to the event."))
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    is_enabled = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    objects = ScheduledQuerySet.as_manager()

    class Meta:
        verbose_name = _("hero slide")
        verbose_name_plural = _("hero slides")
        ordering = ["sort_order"]

    def __str__(self):
        return self.title

    @property
    def link(self):
        if self.cta_url:
            return self.cta_url
        return self.event.get_absolute_url() if self.event_id else ""


class Partner(models.Model):
    name = models.CharField(max_length=100)
    logo = models.FileField(upload_to="partners/")
    url = models.URLField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order"]

    def __str__(self):
        return self.name


class Page(models.Model):
    """Editable content pages: About, Terms, Privacy, Refund policy…"""

    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=150)
    body = models.TextField()
    meta_description = models.CharField(max_length=300, blank=True)
    show_in_footer = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "title"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("cms:page", kwargs={"slug": self.slug})

    def save(self, *args, **kwargs):
        for attr in ("body", "body_en", "body_bn"):
            if hasattr(self, attr):
                setattr(self, attr, sanitize_html(getattr(self, attr)))
        super().save(*args, **kwargs)


class FaqItem(models.Model):
    question = models.CharField(max_length=250)
    answer = models.TextField()
    sort_order = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    show_on_home = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("FAQ item")
        verbose_name_plural = _("FAQ")
        ordering = ["sort_order"]

    def __str__(self):
        return self.question

    def save(self, *args, **kwargs):
        for attr in ("answer", "answer_en", "answer_bn"):
            if hasattr(self, attr):
                setattr(self, attr, sanitize_html(getattr(self, attr)))
        super().save(*args, **kwargs)
