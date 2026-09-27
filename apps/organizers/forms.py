from django import forms
from django.forms import inlineformset_factory
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.core.forms import StyledFormMixin
from apps.core.utils import normalize_phone
from apps.events.models import Category, Event, TicketType

from .models import OrganizerProfile

DATETIME_WIDGET = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class OrganizerApplicationForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = OrganizerProfile
        fields = [
            "name", "organization_type", "contact_email", "contact_phone", "website", "facebook_url",
            "trade_license_no", "verification_document", "about", "application_note", "logo",
        ]
        widgets = {
            "about": forms.Textarea(attrs={"rows": 3}),
            "application_note": forms.Textarea(attrs={"rows": 4}),
            "verification_document": forms.ClearableFileInput(attrs={"accept": ".pdf,.jpg,.jpeg,.png"}),
            "logo": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }
        labels = {
            "about": _("Short public bio"),
            "verification_document": _("Trade license / NID / registration document"),
        }
        help_texts = {
            "application_note": _("What kind of events do you run, how big, how often? Links to past events help."),
        }

    def clean_contact_phone(self):
        return normalize_phone(self.cleaned_data["contact_phone"]).replace("+88", "")

    def clean_verification_document(self):
        doc = self.cleaned_data.get("verification_document")
        if doc and hasattr(doc, "size") and doc.size > 5 * 1024 * 1024:
            raise forms.ValidationError(_("Please upload a file smaller than 5 MB."))
        return doc


class EventForm(StyledFormMixin, forms.ModelForm):
    categories = forms.ModelMultipleChoiceField(
        queryset=Category.objects.filter(is_active=True), widget=forms.CheckboxSelectMultiple,
        label=_("Categories"), help_text=_("Pick every category that fits — events can have several."),
    )

    class Meta:
        model = Event
        fields = [
            "title_en", "title_bn", "summary_en", "summary_bn", "description_en", "description_bn",
            "terms_and_conditions_en", "terms_and_conditions_bn", "categories",
            "starts_at", "ends_at", "sales_start_at", "sales_end_at",
            "venue_name_en", "venue_name_bn", "venue_address", "city", "map_url", "is_online",
            "banner", "max_tickets_per_order",
        ]
        widgets = {
            "starts_at": DATETIME_WIDGET, "ends_at": DATETIME_WIDGET,
            "sales_start_at": DATETIME_WIDGET, "sales_end_at": DATETIME_WIDGET,
            "description_en": forms.HiddenInput, "description_bn": forms.HiddenInput,
            "terms_and_conditions_en": forms.HiddenInput, "terms_and_conditions_bn": forms.HiddenInput,
            "banner": forms.ClearableFileInput(attrs={"accept": "image/*"}),
        }
        labels = {
            "title_en": _("Event title (English)"), "title_bn": _("Event title (Bangla)"),
            "summary_en": _("One-line summary (English)"), "summary_bn": _("One-line summary (Bangla)"),
            "venue_name_en": _("Venue (English)"), "venue_name_bn": _("Venue (Bangla)"),
            "sales_start_at": _("Ticket sales open"), "sales_end_at": _("Ticket sales close"),
        }
        help_texts = {
            "sales_start_at": _("Leave empty to open sales as soon as you publish."),
            "banner": _("16:9 works best, at least 1600×900 px."),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["title_en"].required = True
        for name in ("starts_at", "ends_at", "sales_start_at", "sales_end_at"):
            self.fields[name].input_formats = ["%Y-%m-%dT%H:%M"]

    def clean(self):
        data = super().clean()
        starts, ends = data.get("starts_at"), data.get("ends_at")
        if starts and ends and ends <= starts:
            self.add_error("ends_at", _("The event must end after it starts."))
        sales_start, sales_end = data.get("sales_start_at"), data.get("sales_end_at")
        if sales_start and sales_end and sales_end <= sales_start:
            self.add_error("sales_end_at", _("Sales must close after they open."))
        if starts and not self.instance.pk and starts < timezone.now():
            self.add_error("starts_at", _("The event date is in the past."))
        return data

    def save(self, commit=True):
        event = super().save(commit=False)
        if not event.slug:
            base = slugify(event.title_en)[:180] or "event"
            slug, n = base, 2
            while Event.objects.filter(slug=slug).exists():
                slug, n = f"{base}-{n}", n + 1
            event.slug = slug
        if commit:
            event.save()
            self.save_m2m()
        return event


class TicketTypeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TicketType
        fields = [
            "name_en", "name_bn", "description_en", "description_bn", "price", "stock",
            "allow_quantity", "max_per_order", "is_bundle", "is_available", "sort_order",
        ]
        widgets = {
            "description_en": forms.Textarea(attrs={"rows": 2}),
            "description_bn": forms.Textarea(attrs={"rows": 2}),
            "sort_order": forms.HiddenInput,
        }
        labels = {"name_en": _("Ticket name"), "name_bn": _("Name (Bangla)"), "stock": _("Quantity")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name_en"].required = True
        self.fields["sort_order"].required = False

    def clean_stock(self):
        stock = self.cleaned_data["stock"]
        if self.instance.pk and stock < self.instance.sold_count + self.instance.held_count:
            raise forms.ValidationError(
                _("Already %(n)s sold or reserved — quantity can't go lower.")
                % {"n": self.instance.sold_count + self.instance.held_count}
            )
        return stock


class BaseTicketTypeFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        live = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        if not live:
            raise forms.ValidationError(_("Add at least one ticket type."))
        for form in self.forms:
            if form.cleaned_data.get("DELETE") and form.instance.pk and form.instance.sold_count:
                raise forms.ValidationError(
                    _("“%(name)s” has sales and can't be deleted — mark it unavailable instead.")
                    % {"name": form.instance.name}
                )


TicketTypeFormSet = inlineformset_factory(
    Event, TicketType, form=TicketTypeForm, formset=BaseTicketTypeFormSet, extra=0, can_delete=True, min_num=0
)


class ScannerInviteForm(StyledFormMixin, forms.Form):
    email = forms.EmailField(label=_("Staff member's account email"))
