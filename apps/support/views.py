import logging

from django import forms
from django.contrib import messages
from django.core.mail import EmailMessage
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django_ratelimit.decorators import ratelimit

from apps.cms.models import SiteSettings
from apps.core.forms import StyledFormMixin

from .models import ContactMessage, SupportRoute

logger = logging.getLogger(__name__)


class ContactForm(StyledFormMixin, forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.HiddenInput)  # honeypot

    class Meta:
        model = ContactMessage
        fields = ["reason", "name", "email", "phone", "order_reference", "message"]
        widgets = {"message": forms.Textarea(attrs={"rows": 5})}
        labels = {"order_reference": gettext_lazy("Order reference (if any)")}

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("spam")
        return ""


@ratelimit(key="ip", rate="5/h", method="POST", block=True)
def contact(request):
    initial = {"reason": request.GET.get("reason", "")}
    if request.user.is_authenticated:
        initial.update({"name": request.user.full_name, "email": request.user.email, "phone": request.user.phone})
    form = ContactForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        msg = form.save(commit=False)
        if request.user.is_authenticated:
            msg.user = request.user
        msg.save()
        route = SupportRoute.objects.filter(reason=msg.reason).first()
        inbox = route.email if route else SiteSettings.load().contact_email
        try:
            EmailMessage(
                subject=f"[{msg.get_reason_display()}] {msg.name}" + (f" — {msg.order_reference}" if msg.order_reference else ""),
                body=f"{msg.message}\n\n—\n{msg.name} <{msg.email}> {msg.phone}\nMessage #{msg.pk}",
                to=[inbox],
                reply_to=[msg.email],
            ).send()
        except Exception:  # the message is stored either way; staff can see it in admin
            logger.exception("Could not forward contact message %s", msg.pk)
        messages.success(request, _("Thanks! Our team will get back to you soon."))
        return redirect("support:contact")
    return render(request, "support/contact.html", {"form": form})
