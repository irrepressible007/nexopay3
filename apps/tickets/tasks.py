import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import translation
from django_tasks import task

logger = logging.getLogger(__name__)


@task()
def deliver_order_tickets(order_id: int) -> None:
    """Email a paid order's tickets as one PDF attachment."""
    from apps.orders.models import Order

    from .rendering import render_tickets_pdf

    order = Order.objects.select_related("event", "user").get(pk=order_id)
    tickets = list(order.tickets.select_related("ticket_type", "event", "owner", "order"))
    if not tickets:
        return
    with translation.override(order.language):
        context = {"order": order, "event": order.event, "tickets": tickets, "site_url": settings.SITE_URL}
        subject = translation.gettext("Your tickets for %(event)s") % {"event": order.event.title}
        text = render_to_string("emails/tickets.txt", context)
        html = render_to_string("emails/tickets.html", context)
        message = EmailMultiAlternatives(subject, text, to=[order.delivery_email])
        message.attach_alternative(html, "text/html")
        message.attach(f"nexopay-{order.reference}.pdf", render_tickets_pdf(tickets, order.language), "application/pdf")
        message.send()
    logger.info("Delivered %s tickets for order %s to %s", len(tickets), order.reference, order.delivery_email)
