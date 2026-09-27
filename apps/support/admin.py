from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.decorators import display

from .models import ContactMessage, SupportRoute


@admin.register(ContactMessage)
class ContactMessageAdmin(ModelAdmin):
    list_display = ["created_at", "reason_badge", "name", "email", "order_reference", "status", "assigned_to"]
    list_editable = ["status", "assigned_to"]
    list_filter = ["reason", "status", "created_at"]
    search_fields = ["name", "email", "phone", "order_reference", "message"]
    readonly_fields = ["reason", "name", "email", "phone", "order_reference", "message", "user", "created_at"]
    fields = readonly_fields + ["status", "assigned_to", "internal_note"]

    @display(description="Reason", label=True)
    def reason_badge(self, obj):
        return obj.get_reason_display()


@admin.register(SupportRoute)
class SupportRouteAdmin(ModelAdmin):
    list_display = ["reason", "email"]
    list_editable = ["email"]
    list_display_links = ["reason"]
