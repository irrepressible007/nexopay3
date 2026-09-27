from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class Provider(models.TextChoices):
    BKASH = "bkash", "bKash"
    NAGAD = "nagad", "Nagad"
    UPAY = "upay", "Upay"
    PATHAOPAY = "pathaopay", "Pathao Pay"
    SSLCOMMERZ = "sslcommerz", _("Card (Visa / Mastercard)")
    FREE = "free", _("Free ticket")
    MOCK = "mock", _("Test payment")


class PaymentProviderSetting(models.Model):
    """Admin switches for each provider. Credentials live in environment variables."""

    provider = models.CharField(max_length=20, choices=Provider.choices, unique=True)
    is_enabled = models.BooleanField(default=False)
    is_sandbox = models.BooleanField(default=True, help_text=_("Use the provider's sandbox/test environment."))
    display_name = models.CharField(max_length=60, blank=True)
    logo = models.ImageField(upload_to="payments/logos/", blank=True)
    brand_color = models.CharField(
        max_length=7, default="#FFFFFF", help_text=_("Colour of the name badge, e.g. #E2136E.")
    )
    show_in_footer = models.BooleanField(default=True, help_text=_("Show this method in the site footer."))
    sort_order = models.PositiveSmallIntegerField(default=0)
    credentials_encrypted = models.TextField(blank=True, editable=False)

    class Meta:
        verbose_name = _("payment method")
        verbose_name_plural = _("payment methods")
        ordering = ["sort_order"]

    def __str__(self):
        return self.display_name or self.get_provider_display()

    def get_credentials(self) -> dict:
        from apps.core.crypto import decrypt_json

        return decrypt_json(self.credentials_encrypted)

    def set_credentials(self, values: dict) -> None:
        from apps.core.crypto import encrypt_json

        self.credentials_encrypted = encrypt_json({k: v for k, v in values.items() if v not in (None, "")})


class PaymentAttempt(TimeStampedModel):
    """
    One try at paying an order through one provider. `provider_txn_id` is the
    provider's final transaction id and is unique — replayed callbacks/IPNs for
    the same transaction are therefore detected and ignored.
    """

    class Status(models.TextChoices):
        INITIATED = "initiated", _("Initiated")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        CANCELLED = "cancelled", _("Cancelled")

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="payment_attempts")
    provider = models.CharField(max_length=20, choices=Provider.choices)
    tran_id = models.CharField(max_length=64, unique=True, help_text=_("Our id sent to the provider."))
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.INITIATED, db_index=True)
    provider_ref = models.CharField(max_length=128, blank=True, db_index=True, help_text=_("Provider session/payment id."))
    provider_txn_id = models.CharField(max_length=128, null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "provider_txn_id"], name="paymentattempt_unique_txn")
        ]

    def __str__(self):
        return f"{self.tran_id} ({self.provider}, {self.status})"

    def log(self, key: str, payload) -> None:
        """Append a provider payload to the audit trail (saved by the caller)."""
        entries = self.raw.setdefault("log", [])
        entries.append({"step": key, "data": payload})


class Refund(TimeStampedModel):
    """Refunds are always issued by the platform, never negotiated off-platform."""

    class Status(models.TextChoices):
        REQUESTED = "requested", _("Requested")
        APPROVED = "approved", _("Approved")
        SUCCEEDED = "succeeded", _("Refunded")
        FAILED = "failed", _("Failed")
        REJECTED = "rejected", _("Rejected")

    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="refunds")
    attempt = models.ForeignKey(PaymentAttempt, null=True, blank=True, on_delete=models.PROTECT, related_name="refunds")
    tickets = models.ManyToManyField("tickets.Ticket", related_name="refunds", blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    provider_refund_id = models.CharField(max_length=128, blank=True)
    manual_reference = models.CharField(
        max_length=128, blank=True, help_text=_("Reference of a refund sent manually (e.g. bKash send-money TrxID).")
    )
    raw = models.JSONField(default=dict, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Refund {self.amount} for {self.order}"


class Payout(TimeStampedModel):
    """A settlement paid to an organizer (recorded manually in v1)."""

    organizer = models.ForeignKey("organizers.OrganizerProfile", on_delete=models.PROTECT, related_name="payouts")
    event = models.ForeignKey("events.Event", null=True, blank=True, on_delete=models.PROTECT, related_name="payouts")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=60, help_text=_("e.g. Bank transfer, bKash"))
    reference = models.CharField(max_length=128, blank=True)
    note = models.TextField(blank=True)
    paid_at = models.DateTimeField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-paid_at"]

    def __str__(self):
        return f"{self.organizer} — {self.amount}"
