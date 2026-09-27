from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Reason(models.TextChoices):
    PAYMENT_ISSUE = "payment_issue", _("Payment issue")
    TICKET_ISSUE = "ticket_issue", _("Purchased ticket issue")
    ACCOUNT = "account", _("Account management")
    LIST_EVENT = "list_event", _("List an event / event promotion")
    TECHNICAL = "technical", _("Technical assistance")
    FEEDBACK = "feedback", _("Feedback and suggestions")


class SupportRoute(models.Model):
    """Which inbox receives each contact reason — separate queues from day one."""

    reason = models.CharField(max_length=20, choices=Reason.choices, unique=True)
    email = models.EmailField(help_text=_("Inbox that receives this type of message."))

    class Meta:
        verbose_name = _("support route")
        verbose_name_plural = _("support routes")

    def __str__(self):
        return f"{self.get_reason_display()} → {self.email}"


class ContactMessage(models.Model):
    class Status(models.TextChoices):
        NEW = "new", _("New")
        IN_PROGRESS = "in_progress", _("In progress")
        RESOLVED = "resolved", _("Resolved")

    reason = models.CharField(_("reason"), max_length=20, choices=Reason.choices, db_index=True)
    name = models.CharField(_("name"), max_length=150)
    email = models.EmailField(_("email"))
    phone = models.CharField(_("phone"), max_length=20, blank=True)
    order_reference = models.CharField(_("order reference"), max_length=20, blank=True)
    message = models.TextField(_("message"))
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    internal_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("contact message")
        verbose_name_plural = _("contact messages")
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_reason_display()}] {self.name}"
