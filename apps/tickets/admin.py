from django.contrib import admin, messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import AutocompleteSelectFilter, RangeDateTimeFilter
from unfold.decorators import action, display

from apps.core.admin_utils import export_csv

from .models import ScanLog, ScannerAccess, Ticket


@admin.register(Ticket)
class TicketAdmin(ModelAdmin):
    list_display = ["code", "event", "ticket_type", "holder", "status_badge", "redeemed_at"]
    list_filter = ["status", ("event", AutocompleteSelectFilter), ("redeemed_at", RangeDateTimeFilter)]
    list_filter_submit = True
    search_fields = ["code", "owner__email", "order__reference", "holder_name"]
    list_select_related = ["event", "ticket_type", "owner"]
    readonly_fields = ["id", "code", "order", "order_item", "ticket_type", "event", "owner", "redeemed_at", "redeemed_by",
                       "created_at"]
    fields = readonly_fields[:7] + ["holder_name", "status"] + readonly_fields[7:]
    actions = ["resend", export_csv]
    actions_detail = ["detail_pdf", "detail_resend", "detail_order"]
    export_fields = ["code", "event", "ticket_type", "holder", "status", "redeemed_at"]

    def has_add_permission(self, request):
        return False

    @display(description=_("Holder"))
    def holder(self, obj):
        return obj.holder_name or (obj.owner.get_full_name() if obj.owner else "")

    @display(description=_("Status"), ordering="status", label={"valid": "success", "redeemed": "info", "refunded": "danger"})
    def status_badge(self, obj):
        return obj.status, obj.get_status_display()

    @action(description=_("Email these tickets' orders again"))
    def resend(self, request, queryset):
        from apps.orders.admin import resend_order_tickets

        orders = {t.order for t in queryset.select_related("order")}
        n = resend_order_tickets(request, orders)
        messages.success(request, _("Tickets queued for %(n)s order(s).") % {"n": n})

    @action(description=_("Download (PDF)"), url_path="pdf", icon="picture_as_pdf")
    def detail_pdf(self, request, object_id):
        from apps.tickets.rendering import render_tickets_pdf

        ticket = Ticket.objects.select_related("event", "ticket_type", "order", "owner").get(pk=object_id)
        response = HttpResponse(render_tickets_pdf([ticket], ticket.order.language), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="nexopay-ticket-{ticket.code}.pdf"'
        return response

    @action(description=_("Email the ticket again"), url_path="resend", icon="forward_to_inbox")
    def detail_resend(self, request, object_id):
        from apps.orders.admin import resend_order_tickets

        ticket = Ticket.objects.select_related("order").get(pk=object_id)
        resend_order_tickets(request, [ticket.order])
        messages.success(request, _("Tickets queued for %(email)s.") % {"email": ticket.order.delivery_email})
        return redirect(reverse("admin:tickets_ticket_change", args=[object_id]))

    @action(description=_("Open the order"), url_path="order", icon="receipt_long")
    def detail_order(self, request, object_id):
        return redirect(reverse("admin:orders_order_change", args=[Ticket.objects.get(pk=object_id).order_id]))


@admin.register(ScannerAccess)
class ScannerAccessAdmin(ModelAdmin):
    list_display = ["user", "event", "granted_by", "created_at"]
    list_filter = [("event", AutocompleteSelectFilter)]
    list_filter_submit = True
    search_fields = ["user__email", "event__title_en"]
    autocomplete_fields = ["user", "event"]
    readonly_fields = ["granted_by"]

    def save_model(self, request, obj, form, change):
        obj.granted_by = obj.granted_by or request.user
        super().save_model(request, obj, form, change)


@admin.register(ScanLog)
class ScanLogAdmin(ModelAdmin):
    list_display = ["created_at", "event", "result_badge", "ticket", "scanned_by"]
    list_filter = ["result", ("event", AutocompleteSelectFilter), ("created_at", RangeDateTimeFilter)]
    list_filter_submit = True
    readonly_fields = ["event", "ticket", "scanned_by", "result", "created_at"]
    actions = [export_csv]

    def has_add_permission(self, request):
        return False

    @display(description=_("Result"), ordering="result", label=True)
    def result_badge(self, obj):
        return obj.get_result_display() if hasattr(obj, "get_result_display") else obj.result
