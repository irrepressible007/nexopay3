from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.http import private_no_store
from apps.orders.models import Order
from apps.tickets.models import Ticket
from apps.tickets.rendering import qr_svg, render_tickets_pdf

from .forms import ProfileForm


@login_required
@private_no_store
def my_tickets(request):
    now = timezone.now()
    tickets = (
        Ticket.objects.filter(owner=request.user)
        .exclude(status=Ticket.Status.REFUNDED)
        .select_related("event", "ticket_type", "order")
        .order_by("event__starts_at")
    )
    upcoming, past = {}, {}
    for t in tickets:
        bucket = upcoming if (t.event.ends_at or t.event.starts_at) >= now - timedelta(hours=12) else past
        bucket.setdefault(t.event, []).append(t)
    return render(
        request,
        "accounts/tickets.html",
        {"upcoming": list(upcoming.items()), "past": list(reversed(list(past.items())))},
    )


def _own_ticket(request, code):
    return get_object_or_404(
        Ticket.objects.select_related("event", "event__organizer", "ticket_type", "order", "owner"),
        code=code,
        owner=request.user,
    )


@login_required
@private_no_store
def ticket_detail(request, code):
    ticket = _own_ticket(request, code)
    share_url = request.build_absolute_uri(ticket.get_share_url())
    return render(
        request,
        "accounts/ticket_detail.html",
        {"ticket": ticket, "qr": qr_svg(ticket.token, scale=7), "share_url": share_url},
    )


@login_required
@private_no_store
def ticket_pdf(request, code):
    ticket = _own_ticket(request, code)
    pdf = render_tickets_pdf([ticket], request.LANGUAGE_CODE)
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="nexopay-ticket-{ticket.code}.pdf"'
    return response


@login_required
@private_no_store
def order_pdf(request, reference):
    order = get_object_or_404(Order, reference=reference, user=request.user, status=Order.Status.PAID)
    tickets = list(
        order.tickets.exclude(status=Ticket.Status.REFUNDED).select_related("event", "ticket_type", "order", "owner")
    )
    response = HttpResponse(render_tickets_pdf(tickets, request.LANGUAGE_CODE), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="nexopay-{order.reference}.pdf"'
    return response


@login_required
@private_no_store
def orders(request):
    qs = (
        Order.objects.filter(user=request.user)
        .exclude(status=Order.Status.CANCELLED)
        .select_related("event")
        .prefetch_related("items__ticket_type")
    )
    return render(request, "accounts/orders.html", {"orders": qs})


@login_required
@private_no_store
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Profile updated."))
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})
