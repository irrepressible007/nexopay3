from django.conf import settings
from django.contrib import admin, messages
from django.core.mail import send_mail
from django.utils.html import format_html
from modeltranslation.admin import TranslationAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action, display

from .models import OrganizerProfile


def _email(org, subject, body):
    try:
        send_mail(subject, body, None, [org.user.email, org.contact_email])
    except Exception:
        pass


@admin.register(OrganizerProfile)
class OrganizerProfileAdmin(ModelAdmin, TranslationAdmin):
    list_display = ["name", "user", "status_badge", "event_count", "commission_pct", "created_at"]
    list_filter = ["status", "can_issue_refunds"]
    search_fields = ["name", "user__email", "contact_email", "contact_phone", "trade_license_no"]
    readonly_fields = ["user", "reviewed_at", "reviewed_by", "document_link", "created_at"]
    prepopulated_fields = {"slug": ("name",)}
    actions = ["approve", "reject"]
    fieldsets = (
        ("Review", {"fields": ("status", "review_note", "reviewed_at", "reviewed_by")}),
        ("Public profile", {"fields": ("user", "name", "slug", "logo", "about", "contact_email", "contact_phone",
                                       "website", "facebook_url")}),
        ("Verification (private)", {"fields": ("organization_type", "trade_license_no", "document_link",
                                                "application_note")}),
        ("Fees & permissions", {"fields": ("commission_pct", "buyer_fee_pct", "buyer_fee_flat", "can_issue_refunds"),
                                "description": "Leave fees empty to use the platform defaults from Site settings."}),
    )

    @display(description="Status", label={"pending_review": "warning", "approved": "success", "rejected": "danger"})
    def status_badge(self, obj):
        return obj.status

    @display(description="Events")
    def event_count(self, obj):
        return obj.events.count()

    @display(description="Document")
    def document_link(self, obj):
        if not obj.verification_document:
            return "—"
        return format_html('<a href="{}" target="_blank" rel="noopener">Open document</a>', obj.verification_document.url)

    @action(description="Approve selected organizers")
    def approve(self, request, queryset):
        for org in queryset.exclude(status=OrganizerProfile.Status.APPROVED):
            org.approve(request.user)
            _email(org, "Your Nexopay organizer account is approved 🎉",
                   f"Hi {org.name},\n\nYou're approved! Create your first event here:\n"
                   f"{settings.SITE_URL}/organizers/events/new/\n\n— Nexopay")
        messages.success(request, "Approved and notified.")

    @action(description="Reject selected organizers (uses the review note)")
    def reject(self, request, queryset):
        for org in queryset:
            org.reject(request.user, org.review_note)
            _email(org, "Your Nexopay organizer application",
                   f"Hi {org.name},\n\nUnfortunately we couldn't approve your application this time."
                   f"\n\n{org.review_note}\n\nYou can update your details and re-apply at "
                   f"{settings.SITE_URL}/organizers/apply/\n\n— Nexopay")
        messages.info(request, "Rejected and notified.")
