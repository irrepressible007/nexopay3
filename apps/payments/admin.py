from django.contrib import admin, messages
from django.db.models import Sum
from unfold.admin import ModelAdmin
from unfold.decorators import action, display

from .models import PaymentAttempt, PaymentProviderSetting, Payout, Refund
from .refunds import mark_refunded_manually, process_refund


@admin.register(PaymentProviderSetting)
class PaymentProviderSettingAdmin(ModelAdmin):
    list_display = ["provider", "display_name", "is_enabled", "is_sandbox", "sort_order"]
    list_editable = ["display_name", "is_enabled", "is_sandbox", "sort_order"]


@admin.register(PaymentAttempt)
class PaymentAttemptAdmin(ModelAdmin):
    list_display = ["tran_id", "order", "provider", "amount", "status_badge", "provider_txn_id", "created_at"]
    list_filter = ["provider", "status", "created_at"]
    search_fields = ["tran_id", "provider_txn_id", "provider_ref", "order__reference"]
    readonly_fields = [f.name for f in PaymentAttempt._meta.fields]
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    @display(description="Status", label={"succeeded": "success", "initiated": "warning", "failed": "danger",
                                          "cancelled": "secondary"})
    def status_badge(self, obj):
        return obj.status


@admin.register(Refund)
class RefundAdmin(ModelAdmin):
    list_display = ["order", "amount", "status_badge", "provider", "requested_by", "created_at", "completed_at"]
    list_filter = ["status", "attempt__provider"]
    search_fields = ["order__reference", "provider_refund_id", "manual_reference"]
    readonly_fields = ["order", "attempt", "amount", "tickets", "requested_by", "approved_by", "provider_refund_id",
                       "raw", "completed_at", "created_at"]
    fields = ["order", "attempt", "amount", "tickets", "reason", "status", "manual_reference", "requested_by",
              "approved_by", "provider_refund_id", "raw", "completed_at", "created_at"]
    actions = ["send_via_provider", "mark_manual", "reject"]

    def has_add_permission(self, request):
        return False

    @display(description="Status", label={"requested": "warning", "approved": "info", "succeeded": "success",
                                          "failed": "danger", "rejected": "secondary"})
    def status_badge(self, obj):
        return obj.status

    @display(description="Paid via")
    def provider(self, obj):
        return obj.attempt.get_provider_display() if obj.attempt else "—"

    @action(description="Approve & send via payment provider API")
    def send_via_provider(self, request, queryset):
        done, pending = 0, 0
        for refund in queryset.filter(status__in=(Refund.Status.REQUESTED, Refund.Status.APPROVED)):
            refund = process_refund(refund, by=request.user)
            if refund.status == Refund.Status.SUCCEEDED:
                done += 1
            else:
                pending += 1
        messages.success(request, f"{done} refunded.")
        if pending:
            messages.warning(request, f"{pending} need manual processing: refund in the provider portal, enter the "
                                      "reference in 'Manual reference', save, then use 'Mark as refunded manually'.")

    @action(description="Mark as refunded manually (requires Manual reference)")
    def mark_manual(self, request, queryset):
        for refund in queryset.filter(status__in=(Refund.Status.REQUESTED, Refund.Status.APPROVED)):
            if not refund.manual_reference:
                messages.error(request, f"Refund {refund.pk}: enter the manual reference first.")
                continue
            mark_refunded_manually(refund, refund.manual_reference, by=request.user)
        messages.success(request, "Done.")

    @action(description="Reject selected refund requests")
    def reject(self, request, queryset):
        queryset.filter(status=Refund.Status.REQUESTED).update(status=Refund.Status.REJECTED)


@admin.register(Payout)
class PayoutAdmin(ModelAdmin):
    list_display = ["organizer", "event", "amount", "method", "reference", "paid_at"]
    list_filter = ["organizer", "method"]
    search_fields = ["organizer__name", "reference"]
    autocomplete_fields = ["organizer", "event"]
    readonly_fields = ["created_by"]

    def save_model(self, request, obj, form, change):
        obj.created_by = obj.created_by or request.user
        super().save_model(request, obj, form, change)

    def changelist_view(self, request, extra_context=None):
        response = super().changelist_view(request, extra_context)
        try:
            qs = response.context_data["cl"].queryset
            response.context_data["subtitle"] = f"Total shown: ৳{qs.aggregate(t=Sum('amount'))['t'] or 0:,.0f}"
        except (AttributeError, KeyError):
            pass
        return response
