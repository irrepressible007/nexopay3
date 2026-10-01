from django.contrib import admin, messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import AutocompleteSelectFilter, RangeDateFilter
from unfold.decorators import action, display

from apps.core.admin_utils import export_csv
from apps.payments.models import PaymentAttempt
from apps.payments.refunds import RefundError, request_refund
from apps.tickets.models import Ticket

from .models import Order, OrderItem

PAID = (Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED)


class OrderItemInline(TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    tab = True
    readonly_fields = ["ticket_type", "quantity", "unit_price"]
    verbose_name_plural = _("Items")


class TicketInline(TabularInline):
    model = Ticket
    extra = 0
    can_delete = False
    tab = True
    fields = ["code", "ticket_type", "status", "redeemed_at"]
    readonly_fields = fields
    show_change_link = True


class AttemptInline(TabularInline):
    model = PaymentAttempt
    extra = 0
    can_delete = False
    tab = True
    fields = ["tran_id", "provider", "amount", "status", "provider_txn_id", "completed_at"]
    readonly_fields = fields
    verbose_name_plural = _("Payment attempts")


def resend_order_tickets(request, orders):
    """Queue the ticket email again for paid orders; returns how many were queued."""
    from apps.tickets.tasks import deliver_order_tickets

    sent = 0
    for order in orders:
        if order.status in PAID:
            deliver_order_tickets.enqueue(order.pk)
            sent += 1
    return sent


def order_pdf_response(order):
    from apps.tickets.rendering import render_tickets_pdf

    tickets = list(order.tickets.exclude(status=Ticket.Status.REFUNDED)
                   .select_related("event", "ticket_type", "order", "owner"))
    response = HttpResponse(render_tickets_pdf(tickets, order.language), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="nexopay-{order.reference}.pdf"'
    return response


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = ["reference", "event", "buyer", "total", "status_badge", "payment_method", "created_at"]
    list_filter = ["status", "payment_method", ("created_at", RangeDateFilter), ("event", AutocompleteSelectFilter)]
    list_filter_submit = True
    search_fields = ["reference", "delivery_email", "buyer_phone", "buyer_name", "user__email"]
    list_select_related = ["event"]
    readonly_fields = [f.name for f in Order._meta.fields]
    inlines = [OrderItemInline, TicketInline, AttemptInline]
    actions = ["resend_tickets", export_csv, "refund_full"]
    actions_detail = ["detail_resend", "detail_pdf", "detail_view_event"]
    date_hierarchy = "created_at"
    export_fields = ["reference", "event", "buyer_name", "delivery_email", "buyer_phone", "subtotal", "buyer_fee",
                     "total", "status", "payment_method", "created_at", "paid_at"]

    def has_add_permission(self, request):
        return False

    @display(description=_("Buyer"), header=True)
    def buyer(self, obj):
        return [obj.buyer_name or obj.delivery_email, obj.delivery_email if obj.buyer_name else obj.buyer_phone,
                (obj.buyer_name or obj.delivery_email or "?")[:1]]

    @display(description=_("Status"), ordering="status",
             label={"paid": "success", "pending_payment": "warning", "expired": "secondary",
                    "cancelled": "secondary", "refunded": "danger", "partially_refunded": "warning"})
    def status_badge(self, obj):
        return obj.status, obj.get_status_display()

    @action(description=_("Email the tickets again"))
    def resend_tickets(self, request, queryset):
        sent = resend_order_tickets(request, queryset)
        messages.success(request, _("Tickets queued for %(n)s order(s); they go out within a minute.") % {"n": sent})

    @action(description=_("Create a full refund request (review under Refunds)"))
    def refund_full(self, request, queryset):
        created = 0
        for order in queryset:
            try:
                request_refund(order=order, reason="Refund issued by Nexopay support", by=request.user, approve=True)
                created += 1
            except RefundError as exc:
                messages.error(request, f"{order.reference}: {exc}")
        if created:
            messages.success(request, _("%(n)s refund(s) approved: process them from Money › Refunds.") % {"n": created})

    @action(description=_("Email the tickets again"), url_path="resend", icon="forward_to_inbox")
    def detail_resend(self, request, object_id):
        order = Order.objects.get(pk=object_id)
        if resend_order_tickets(request, [order]):
            messages.success(request, _("Tickets queued for %(email)s.") % {"email": order.delivery_email})
        else:
            messages.warning(request, _("Only paid orders have tickets to send."))
        return redirect(reverse("admin:orders_order_change", args=[object_id]))

    @action(description=_("Download tickets (PDF)"), url_path="pdf", icon="picture_as_pdf")
    def detail_pdf(self, request, object_id):
        return order_pdf_response(Order.objects.get(pk=object_id))

    @action(description=_("Open the event"), url_path="event", icon="event")
    def detail_view_event(self, request, object_id):
        return redirect(reverse("admin:events_event_change", args=[Order.objects.get(pk=object_id).event_id]))
