from decimal import Decimal

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.core.utils import random_code


def new_order_reference() -> str:
    return f"NXP{random_code(8)}"


class Order(TimeStampedModel):
    """
    A purchase of one or more ticket types for a single event. An account is
    always required (no guest checkout). Fees are snapshotted at creation so
    later changes to an organizer's rates never alter past orders.
    """

    class Status(models.TextChoices):
        PENDING_PAYMENT = "pending_payment", _("Awaiting payment")
        PAID = "paid", _("Paid")
        EXPIRED = "expired", _("Expired")
        CANCELLED = "cancelled", _("Cancelled")
        REFUNDED = "refunded", _("Refunded")
        PARTIALLY_REFUNDED = "partially_refunded", _("Partially refunded")

    reference = models.CharField(max_length=20, unique=True, default=new_order_reference, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    event = models.ForeignKey("events.Event", on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    buyer_name = models.CharField(max_length=150)
    buyer_phone = models.CharField(max_length=16)
    delivery_email = models.EmailField(_("send tickets to"))
    language = models.CharField(max_length=5, default="en")
    payment_method = models.CharField(max_length=20, blank=True)

    currency = models.CharField(max_length=3, default="BDT")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    buyer_fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    organizer_net = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    commission_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    buyer_fee_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0"))
    buyer_fee_flat = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))

    class Meta:
        verbose_name = _("order")
        verbose_name_plural = _("orders")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["event", "status"])]

    def __str__(self):
        return self.reference

    def get_absolute_url(self):
        return reverse("orders:detail", kwargs={"reference": self.reference})

    @property
    def is_free(self) -> bool:
        return self.total == 0

    @property
    def is_hold_expired(self) -> bool:
        return self.status == self.Status.PENDING_PAYMENT and self.expires_at and self.expires_at < timezone.now()

    @property
    def ticket_count(self) -> int:
        return sum(i.quantity for i in self.items.all())


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    ticket_type = models.ForeignKey("events.TicketType", on_delete=models.PROTECT, related_name="order_items")
    quantity = models.PositiveSmallIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["order", "ticket_type"], name="orderitem_unique_type")]

    def __str__(self):
        return f"{self.quantity} × {self.ticket_type.name}"

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity


class PurchaseClaim(models.Model):
    """
    Anti-scalping guard: one identity (email or phone) may hold a given ticket
    type only once, unless the ticket type allows quantity. Enforced by a
    unique constraint so concurrent checkouts cannot both slip through.
    """

    ticket_type = models.ForeignKey("events.TicketType", on_delete=models.CASCADE, related_name="claims")
    identity = models.CharField(max_length=270)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="claims")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ticket_type", "identity"], name="purchaseclaim_unique_identity")
        ]

    def __str__(self):
        return f"{self.identity} → {self.ticket_type_id}"
