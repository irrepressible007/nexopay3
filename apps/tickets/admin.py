from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.decorators import display

from .models import ScanLog, ScannerAccess, Ticket


@admin.register(Ticket)
class TicketAdmin(ModelAdmin):
    list_display = ["code", "event", "ticket_type", "owner", "status_badge", "redeemed_at"]
    list_filter = ["status", "event"]
    search_fields = ["code", "owner__email", "order__reference", "holder_name"]
    list_select_related = ["event", "ticket_type", "owner"]
    readonly_fields = ["id", "code", "order", "order_item", "ticket_type", "event", "owner", "redeemed_at", "redeemed_by",
                       "created_at"]
    fields = readonly_fields[:7] + ["holder_name", "status"] + readonly_fields[7:]

    def has_add_permission(self, request):
        return False

    @display(description="Status", label={"valid": "success", "redeemed": "info", "refunded": "danger"})
    def status_badge(self, obj):
        return obj.status


@admin.register(ScannerAccess)
class ScannerAccessAdmin(ModelAdmin):
    list_display = ["user", "event", "granted_by", "created_at"]
    search_fields = ["user__email", "event__title_en"]
    autocomplete_fields = ["user", "event"]
    readonly_fields = ["granted_by"]

    def save_model(self, request, obj, form, change):
        obj.granted_by = obj.granted_by or request.user
        super().save_model(request, obj, form, change)


@admin.register(ScanLog)
class ScanLogAdmin(ModelAdmin):
    list_display = ["created_at", "event", "result", "ticket", "scanned_by"]
    list_filter = ["result", "event"]
    readonly_fields = ["event", "ticket", "scanned_by", "result", "created_at"]

    def has_add_permission(self, request):
        return False
