from urllib.parse import quote

from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import RangeDateFilter
from unfold.decorators import action, display

from apps.core.admin_utils import export_csv

from .models import ContactMessage, SupportRoute


@admin.register(ContactMessage)
class ContactMessageAdmin(ModelAdmin):
    list_display = ["created_at", "reason_badge", "sender", "order_reference", "status", "assigned_to"]
    list_editable = ["status", "assigned_to"]
    list_filter = ["status", "reason", ("created_at", RangeDateFilter)]
    list_filter_submit = True
    search_fields = ["name", "email", "phone", "order_reference", "message"]
    readonly_fields = ["reason", "name", "email", "reply_link", "phone", "order_reference", "message", "user",
                       "created_at"]
    fields = readonly_fields + ["status", "assigned_to", "internal_note"]
    actions = ["mark_in_progress", "mark_resolved", export_csv]
    export_fields = ["created_at", "reason", "name", "email", "phone", "order_reference", "message", "status"]

    @display(description=_("Reason"), label=True)
    def reason_badge(self, obj):
        return obj.get_reason_display()

    @display(description=_("From"), header=True)
    def sender(self, obj):
        return [obj.name, obj.email, (obj.name or "?")[:1]]

    @display(description=_("Reply"))
    def reply_link(self, obj):
        subject = quote(f"Re: {obj.get_reason_display()}" + (f" ({obj.order_reference})" if obj.order_reference else ""))
        return format_html('<a href="mailto:{}?subject={}" class="text-primary-600 hover:underline">{}</a>',
                           obj.email, subject, _("Reply by email"))

    @action(description=_("Mark as in progress"))
    def mark_in_progress(self, request, queryset):
        n = queryset.update(status="in_progress", assigned_to=request.user)
        messages.success(request, _("%(n)s message(s) assigned to you.") % {"n": n})

    @action(description=_("Mark as resolved"))
    def mark_resolved(self, request, queryset):
        n = queryset.update(status="resolved")
        messages.success(request, _("%(n)s message(s) resolved.") % {"n": n})


@admin.register(SupportRoute)
class SupportRouteAdmin(ModelAdmin):
    list_display = ["reason", "email"]
    list_editable = ["email"]
    list_display_links = ["reason"]
