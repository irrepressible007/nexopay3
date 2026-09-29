from django import forms
from django.contrib import admin, messages
from django.db.models import Sum
from django.utils.html import format_html
from modeltranslation.admin import TranslationAdmin
from unfold.admin import ModelAdmin
from unfold.decorators import action, display
from unfold.widgets import UnfoldAdminPasswordToggleWidget, UnfoldAdminTextareaWidget, UnfoldAdminTextInputWidget

from .models import PaymentAttempt, PaymentProviderSetting, Payout, Refund
from .registry import provider_class
from .refunds import mark_refunded_manually, process_refund


class ProviderSettingForm(forms.ModelForm):
    """Adds one field per credential the provider needs; secrets are write-only."""

    clear_credentials = forms.BooleanField(required=False, label="Remove all saved credentials")

    class Meta:
        model = PaymentProviderSetting
        fields = ["display_name_en", "display_name_bn", "is_enabled", "is_sandbox", "logo", "brand_color",
                  "show_in_footer", "sort_order"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cls = provider_class(self.instance.provider) if self.instance.pk else None
        self.credential_specs = list(getattr(cls, "CREDENTIALS", []))
        saved = self.instance.get_credentials() if self.instance.pk else {}
        for spec in self.credential_specs:
            name = f"cred_{spec.name}"
            has_value = bool(saved.get(spec.name))
            # autocomplete: these are the provider's credentials - the browser must not fill in a saved login.
            if spec.secret:
                widget = (UnfoldAdminTextareaWidget(attrs={"rows": 3, "autocomplete": "off"}) if spec.multiline
                          else UnfoldAdminPasswordToggleWidget(attrs={"autocomplete": "new-password"}))
                help_text = ("Saved ✓ — leave empty to keep it. " if has_value else "") + spec.help
            else:
                widget = (UnfoldAdminTextareaWidget(attrs={"rows": 3, "autocomplete": "off"}) if spec.multiline
                          else UnfoldAdminTextInputWidget(attrs={"autocomplete": "off"}))
                help_text = spec.help
            self.fields[name] = forms.CharField(
                label=spec.label, required=False, widget=widget, help_text=help_text,
                initial="" if spec.secret else saved.get(spec.name, ""),
            )

    def save(self, commit=True):
        obj = super().save(commit=False)
        creds = {} if self.cleaned_data.get("clear_credentials") else obj.get_credentials()
        for spec in self.credential_specs:
            value = (self.cleaned_data.get(f"cred_{spec.name}") or "").strip()
            if value:
                creds[spec.name] = value
            elif not spec.secret:
                creds.pop(spec.name, None)
        obj.set_credentials(creds)
        if commit:
            obj.save()
        return obj


@admin.register(PaymentProviderSetting)
class PaymentProviderSettingAdmin(ModelAdmin, TranslationAdmin):
    form = ProviderSettingForm
    list_display = ["provider", "display_name", "is_enabled", "is_sandbox", "credentials_status", "sort_order"]
    list_editable = ["is_enabled", "is_sandbox", "sort_order"]
    readonly_fields = ["provider"]

    def has_add_permission(self, request):
        return False

    def get_form(self, request, obj=None, **kwargs):
        # Declare this provider's credential fields so the admin accepts them in fieldsets.
        specs = getattr(provider_class(obj.provider), "CREDENTIALS", []) if obj else []
        declared = {f"cred_{s.name}": forms.CharField(required=False) for s in specs}
        kwargs["form"] = type("ProviderSettingForm", (ProviderSettingForm,), declared)
        return super().get_form(request, obj, **kwargs)

    def get_fieldsets(self, request, obj=None):
        base = [
            (None, {"fields": ["provider", "display_name_en", "display_name_bn", "is_enabled", "is_sandbox"]}),
            ("Appearance", {"fields": ["logo", "brand_color", "show_in_footer", "sort_order"]}),
        ]
        cls = provider_class(obj.provider) if obj else None
        specs = getattr(cls, "CREDENTIALS", [])
        if specs:
            base.append(("Merchant credentials", {
                "fields": [f"cred_{s.name}" for s in specs] + ["clear_credentials"],
                "description": "Paste the values from the provider's merchant panel. They are stored encrypted "
                               "and never shown again. Keep 'Sandbox' ticked until live credentials are entered.",
            }))
        return base

    @display(description="Credentials")
    def credentials_status(self, obj):
        cls = provider_class(obj.provider)
        specs = [s for s in getattr(cls, "CREDENTIALS", []) if s.required]
        if not specs:
            return "—"
        from .providers.base import BasePaymentProvider

        missing = [s.label for s in specs if not BasePaymentProvider.resolve_credential(obj, s.name)]
        if missing:
            return format_html('<span style="color:#f87171">Missing: {}</span>', ", ".join(missing))
        return format_html('<span style="color:#34d399">Complete ✓</span>')


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
