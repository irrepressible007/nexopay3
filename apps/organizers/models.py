from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


def organizer_logo_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"org/u{instance.user_id}/logo-{timezone.now():%Y%m%d%H%M%S}.{ext}"


def organizer_document_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"org/u{instance.user_id}/docs/{timezone.now():%Y%m%d%H%M%S}.{ext}"


def _private_storage():
    from django.core.files.storage import storages

    return storages["private"]


PERCENT = [MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))]


class OrganizerProfile(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING_REVIEW = "pending_review", _("Pending review")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organizer_profile"
    )
    name = models.CharField(_("organizer / brand name"), max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    logo = models.ImageField(upload_to=organizer_logo_path, blank=True)
    about = models.TextField(_("about"), blank=True)

    # Public contact block shown on every event page.
    contact_email = models.EmailField(_("contact email"))
    contact_phone = models.CharField(_("contact phone"), max_length=20)
    website = models.URLField(blank=True)
    facebook_url = models.URLField(blank=True)

    # Vetting information (private, admin-only).
    organization_type = models.CharField(_("organization type"), max_length=80, blank=True)
    trade_license_no = models.CharField(_("trade license / registration no."), max_length=80, blank=True)
    verification_document = models.FileField(
        upload_to=organizer_document_path, storage=_private_storage, blank=True
    )
    application_note = models.TextField(_("tell us about your events"), blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_REVIEW, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    review_note = models.TextField(blank=True, help_text=_("Sent to the organizer when rejected."))

    # Fee overrides — NULL means "use the platform default" from SiteSettings.
    commission_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=PERCENT)
    buyer_fee_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, validators=PERCENT)
    buyer_fee_flat = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))]
    )

    can_issue_refunds = models.BooleanField(
        default=False, help_text=_("Allow this organizer to issue refunds without admin approval.")
    )

    class Meta:
        verbose_name = _("organizer")
        verbose_name_plural = _("organizers")
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def is_approved(self) -> bool:
        return self.status == self.Status.APPROVED

    def approve(self, by):
        self.status = self.Status.APPROVED
        self.reviewed_at = timezone.now()
        self.reviewed_by = by
        self.save(update_fields=["status", "reviewed_at", "reviewed_by", "updated_at"])

    def reject(self, by, note=""):
        self.status = self.Status.REJECTED
        self.reviewed_at = timezone.now()
        self.reviewed_by = by
        self.review_note = note
        self.save(update_fields=["status", "reviewed_at", "reviewed_by", "review_note", "updated_at"])
