from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import cache_control

from apps.core.http import private_no_store

from .models import Ticket
from .rendering import qr_png, qr_svg


def _ticket_from_token(token):
    ticket_id = Ticket.id_from_token(token)
    if ticket_id is None:
        raise Http404
    try:
        return Ticket.objects.select_related("event", "ticket_type").get(pk=ticket_id)
    except Ticket.DoesNotExist:
        raise Http404


@private_no_store
def share(request, token):
    """
    The WhatsApp-shareable ticket view. Anyone holding the signed link can show
    the QR — exactly like forwarding the PDF — and it still scans only once.
    """
    ticket = _ticket_from_token(token)
    return render(request, "tickets/share.html", {"ticket": ticket, "qr": qr_svg(ticket.token, scale=7)})


@cache_control(private=True, max_age=3600)
def share_qr_png(request, token):
    ticket = _ticket_from_token(token)
    return HttpResponse(qr_png(ticket.token), content_type="image/png")
