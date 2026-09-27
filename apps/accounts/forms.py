from allauth.account.forms import SignupForm as AllauthSignupForm
from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin
from apps.core.utils import normalize_phone

from .models import User


class SignupForm(StyledFormMixin, AllauthSignupForm):
    full_name = forms.CharField(label=_("Full name"), max_length=150)
    phone = forms.CharField(label=_("Mobile number"), max_length=20, help_text=_("e.g. 01712345678"))

    field_order = ["full_name", "email", "phone", "password1", "password2"]

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        if User.objects.filter(phone=phone).exists():
            raise ValidationError(_("An account with this mobile number already exists."))
        return phone

    def save(self, request):
        user = super().save(request)
        user.full_name = self.cleaned_data["full_name"]
        user.phone = self.cleaned_data["phone"]
        user.preferred_language = getattr(request, "LANGUAGE_CODE", "en")
        user.save(update_fields=["full_name", "phone", "preferred_language"])
        return user


class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["full_name", "phone", "preferred_language"]
        labels = {"preferred_language": _("Language for emails")}
        widgets = {"preferred_language": forms.Select(choices=[("en", "English"), ("bn", "বাংলা")])}

    def clean_phone(self):
        raw = self.cleaned_data.get("phone")
        if not raw:
            return None
        phone = normalize_phone(raw)
        if User.objects.filter(phone=phone).exclude(pk=self.instance.pk).exists():
            raise ValidationError(_("This mobile number is used by another account."))
        return phone
