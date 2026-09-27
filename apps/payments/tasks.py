from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import translation
from django_tasks import task


@task()
def notify_refund(refund_id: int) -> None:
    from apps.cms.models import SiteSettings
    from apps.cms.sitetext import ensure_applied

    from .models import Refund

    ensure_applied()
    refund = Refund.objects.select_related("order", "order__event").get(pk=refund_id)
    order = refund.order
    with translation.override(order.language):
        subject = translation.gettext("Your refund for %(event)s") % {"event": order.event.title}
        body = render_to_string(
            "emails/refund.txt", {"refund": refund, "order": order, "site_url": settings.SITE_URL, "sitecfg": SiteSettings.load()}
        )
        send_mail(subject, body, None, [order.delivery_email])
