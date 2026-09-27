from django.contrib import admin, messages
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display

from apps.payments.models import PaymentAttempt
from apps.payments.refunds import RefundError, request_refund
from apps.tickets.models import Ticket

from .models import Order, OrderItem


class OrderItemInline(TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = ["ticket_type", "quantity", "unit_price"]


class TicketInline(TabularInline):
    model = Ticket
    extra = 0
    can_delete = False
    fields = ["code", "ticket_type", "status", "redeemed_at"]
    readonly_fields = fields
    show_change_link = True


class AttemptInline(TabularInline):
    model = PaymentAttempt
    extra = 0
    can_delete = False
    fields = ["tran_id", "provider", "amount", "status", "provider_txn_id", "completed_at"]
    readonly_fields = fields


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = ["reference", "event", "buyer_name", "delivery_email", "total", "status_badge", "payment_method", "created_at"]
    list_filter = ["status", "payment_method", "created_at"]
    search_fields = ["reference", "delivery_email", "buyer_phone", "buyer_name", "user__email"]
    list_select_related = ["event"]
    readonly_fields = [f.name for f in Order._meta.fields]
    inlines = [OrderItemInline, TicketInline, AttemptInline]
    actions = ["refund_full"]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    @display(description="Status", label={"paid": "success", "pending_payment": "warning", "expired": "secondary",
                                          "cancelled": "secondary", "refunded": "danger", "partially_refunded": "warning"})
    def status_badge(self, obj):
        return obj.status

    @action(description="Create a full refund request (review under Refunds)")
    def refund_full(self, request, queryset):
        created = 0
        for order in queryset:
            try:
                request_refund(order=order, reason="Refund issued by Nexopay support", by=request.user, approve=True)
                created += 1
            except RefundError as exc:
                messages.error(request, f"{order.reference}: {exc}")
        if created:
            messages.success(request, f"{created} refund(s) approved — process them from Payments › Refunds.")
