from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin
from apps.core.utils import normalize_phone


class CheckoutForm(StyledFormMixin, forms.Form):
    buyer_name = forms.CharField(label=_("Full name"), max_length=150)
    buyer_phone = forms.CharField(label=_("Mobile number"), max_length=20)
    delivery_email = forms.EmailField(
        label=_("Send tickets to"), help_text=_("Tickets also stay in your account, always.")
    )
    payment_method = forms.ChoiceField(label=_("Pay with"), widget=forms.RadioSelect, required=False)
    agree = forms.BooleanField(
        label=_("I agree to the event's terms and Nexopay's terms of service."),
        error_messages={"required": _("Please accept the terms to continue.")},
    )

    def __init__(self, *args, methods=(), requires_payment=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.requires_payment = requires_payment
        self.fields["payment_method"].choices = [(m.provider, str(m)) for m in methods]
        if methods:
            self.fields["payment_method"].initial = methods[0].provider

    def clean_buyer_phone(self):
        return normalize_phone(self.cleaned_data["buyer_phone"])

    def clean(self):
        data = super().clean()
        if self.requires_payment and not data.get("payment_method"):
            raise ValidationError(_("Choose a payment method."))
        return data


class RetryPaymentForm(forms.Form):
    payment_method = forms.ChoiceField(widget=forms.RadioSelect)

    def __init__(self, *args, methods=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payment_method"].choices = [(m.provider, str(m)) for m in methods]
        if methods:
            self.fields["payment_method"].initial = methods[0].provider
