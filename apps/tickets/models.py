import uuid

from django.conf import settings
from django.core import signing
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.core.utils import random_code


def new_ticket_code() -> str:
    return random_code(10)


def _signer() -> signing.Signer:
    return signing.Signer(salt=settings.NEXOPAY["TICKET_SIGNING_SALT"])


class Ticket(TimeStampedModel):
    """
    One canonical record per purchased unit. Email PDF, WhatsApp share link and
    the in-app QR are all *renderings* of this record — never regenerated per
    channel. The QR encodes a signed token, so IDs cannot be guessed or forged.
    """

    class Status(models.TextChoices):
        VALID = "valid", _("Valid")
        REDEEMED = "redeemed", _("Checked in")
        REFUNDED = "refunded", _("Refunded")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=12, unique=True, default=new_ticket_code, editable=False)
    order = models.ForeignKey("orders.Order", on_delete=models.PROTECT, related_name="tickets")
    order_item = models.ForeignKey("orders.OrderItem", on_delete=models.PROTECT, related_name="tickets")
    ticket_type = models.ForeignKey("events.TicketType", on_delete=models.PROTECT, related_name="tickets")
    event = models.ForeignKey("events.Event", on_delete=models.PROTECT, related_name="tickets")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tickets")
    holder_name = models.CharField(max_length=150, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.VALID, db_index=True)
    redeemed_at = models.DateTimeField(null=True, blank=True)
    redeemed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = _("ticket")
        verbose_name_plural = _("tickets")
        ordering = ["created_at"]
        indexes = [models.Index(fields=["event", "status"])]

    def __str__(self):
        return f"{self.code} ({self.ticket_type.name})"

    @property
    def token(self) -> str:
        """Signed value encoded into the QR code."""
        return _signer().sign(self.id.hex)

    @staticmethod
    def id_from_token(token: str) -> uuid.UUID | None:
        """Return the ticket id if the signature is valid, else None."""
        try:
            return uuid.UUID(hex=_signer().unsign(token.strip()))
        except (signing.BadSignature, ValueError, AttributeError):
            return None

    def get_absolute_url(self):
        return reverse("accounts:ticket", kwargs={"code": self.code})

    def get_share_url(self):
        return reverse("tickets:share", kwargs={"token": self.token})


class ScannerAccess(TimeStampedModel):
    """Gate staff allowed to scan tickets for a specific event."""

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="scanner_access")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="scanner_access")
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        verbose_name = _("scanner access")
        verbose_name_plural = _("scanner access")
        constraints = [models.UniqueConstraint(fields=["event", "user"], name="scanneraccess_unique")]

    def __str__(self):
        return f"{self.user} @ {self.event}"


class ScanLog(models.Model):
    """Every scan attempt — the organizer's check-in log and an audit trail."""

    class Result(models.TextChoices):
        OK = "ok", _("Checked in")
        ALREADY_REDEEMED = "already_redeemed", _("Already used")
        REFUNDED = "refunded", _("Refunded ticket")
        WRONG_EVENT = "wrong_event", _("Different event")
        INVALID = "invalid", _("Invalid code")

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="scan_logs")
    ticket = models.ForeignKey(Ticket, null=True, blank=True, on_delete=models.SET_NULL, related_name="scan_logs")
    scanned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    result = models.CharField(max_length=20, choices=Result.choices)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_result_display()} @ {self.created_at:%H:%M:%S}"
