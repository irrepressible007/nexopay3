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
    logo_on_color = models.FileField(
        upload_to="site/", blank=True,
        help_text=_("All-white PNG used on coloured backgrounds: email headers and PDF tickets."),
    )
    favicon = models.FileField(upload_to="site/", blank=True)
    og_image = models.ImageField(upload_to="site/", blank=True, help_text=_("Default social share image."))

    # Brand colours → CSS custom properties.
    primary_color = models.CharField(max_length=7, default="#8B5CF6", validators=[hex_color])
    secondary_color = models.CharField(max_length=7, default="#D946EF", validators=[hex_color])
    accent_color = models.CharField(max_length=7, default="#22D3EE", validators=[hex_color])
    background_color = models.CharField(max_length=7, default="#08051A", validators=[hex_color])

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

    hold_minutes = models.PositiveSmallIntegerField(
        default=15, help_text=_("How long tickets stay reserved while a buyer pays.")
    )

    # Outgoing email (leave the host empty to use the server configuration).
    email_host = models.CharField(max_length=120, blank=True, help_text=_("e.g. mail.nexopay.com.bd"))
    email_port = models.PositiveIntegerField(default=465)
    email_use_ssl = models.BooleanField(default=True, help_text=_("Port 465: SSL on. Port 587: SSL off, TLS on."))
    email_use_tls = models.BooleanField(default=False)
    email_username = models.CharField(max_length=200, blank=True)
    email_password_encrypted = models.TextField(blank=True, editable=False)
    email_from_name = models.CharField(max_length=80, default="Nexopay")
    email_from_address = models.EmailField(blank=True, help_text=_("e.g. tickets@nexopay.com.bd"))

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

    @property
    def email_password(self) -> str:
        from apps.core.crypto import decrypt_str

        return decrypt_str(self.email_password_encrypted)

    @email_password.setter
    def email_password(self, value: str) -> None:
        from apps.core.crypto import encrypt_str

        self.email_password_encrypted = encrypt_str(value) if value else ""

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


class FooterColumn(models.Model):
    """A titled column of links in the site footer."""

    title = models.CharField(max_length=60)
    sort_order = models.PositiveIntegerField(default=0)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("footer column")
        verbose_name_plural = _("footer columns")
        ordering = ["sort_order"]

    def __str__(self):
        return self.title


class MenuItem(models.Model):
    """A link in the header menu or in a footer column: label, target and order are all editable."""

    class Location(models.TextChoices):
        HEADER = "header", _("Header menu")
        FOOTER = "footer", _("Footer column")

    location = models.CharField(max_length=10, choices=Location.choices, default=Location.HEADER)
    column = models.ForeignKey(
        FooterColumn, null=True, blank=True, on_delete=models.CASCADE, related_name="items",
        help_text=_("Required for footer links."),
    )
    label = models.CharField(max_length=60)
    url = models.CharField(
        max_length=300, help_text=_("A path on this site like /events/?status=live, or a full https:// link.")
    )
    open_in_new_tab = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("menu link")
        verbose_name_plural = _("menu links")
        ordering = ["location", "sort_order"]

    def __str__(self):
        return self.label

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.location == self.Location.FOOTER and not self.column_id:
            raise ValidationError({"column": _("Choose which footer column this link belongs to.")})
        if not self.url.startswith(("/", "https://", "http://", "mailto:", "tel:")):
            raise ValidationError({"url": _("Start with / for a page on this site, or https:// for another site.")})


class HeaderLink(MenuItem):
    """Admin view onto the header menu links only."""

    class Meta:
        proxy = True
        verbose_name = _("header menu link")
        verbose_name_plural = _("header menu")


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
    body = models.TextField(blank=True)
    meta_description = models.CharField(max_length=300, blank=True)
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


class SiteText(models.Model):
    """
    One user-visible interface string (button, label, heading, email line…).
    `msgid` is the English source text from the code; admins override it per
    language without touching code. Overrides are applied on top of the
    translation catalogs, so every template, form, email and PDF picks them up.
    """

    key = models.CharField(max_length=40, unique=True, editable=False)
    msgid = models.TextField("original text (from code)", editable=False)
    msgid_plural = models.TextField(blank=True, editable=False)
    group = models.CharField(max_length=60, db_index=True, editable=False)
    location = models.CharField(max_length=255, blank=True, editable=False)
    default_bn = models.TextField("default Bangla", blank=True, editable=False)
    placeholders = models.CharField(max_length=255, blank=True, editable=False)
    text_en = models.TextField("English text", blank=True, help_text=_("Leave empty to use the original text."))
    text_en_plural = models.TextField(
        "English text (plural)", blank=True, help_text=_("Only for texts with a number, e.g. '3 tickets'.")
    )
    text_bn = models.TextField("Bangla text", blank=True, help_text=_("Leave empty to use the default Bangla."))
    is_obsolete = models.BooleanField(default=False, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("site text")
        verbose_name_plural = _("site texts")
        ordering = ["group", "msgid"]

    def __str__(self):
        return self.msgid[:80]

    @property
    def is_customized(self) -> bool:
        return bool(self.text_en or self.text_en_plural or self.text_bn)

    def clean(self):
        from django.core.exceptions import ValidationError

        from .sitetext import clean_override, placeholder_set

        expected = placeholder_set(self.msgid + " " + self.msgid_plural)
        errors = {}
        for field in ("text_en", "text_en_plural", "text_bn"):
            value = getattr(self, field)
            if not value:
                continue
            value = clean_override(value, allow_html="<" in self.msgid)
            setattr(self, field, value)
            found = placeholder_set(value)
            # The English singular of a counted text may drop the number ("One ticket").
            singular_may_drop = field == "text_en" and self.msgid_plural and found <= expected
            if found != expected and not singular_may_drop:
                missing, extra = expected - found, found - expected
                parts = []
                if missing:
                    parts.append(_("keep %(p)s") % {"p": ", ".join(sorted(missing))})
                if extra:
                    parts.append(_("remove %(p)s") % {"p": ", ".join(sorted(extra))})
                errors[field] = _("Placeholders must stay exactly as in the original: %(details)s.") % {
                    "details": "; ".join(parts)
                }
        if errors:
            raise ValidationError(errors)
