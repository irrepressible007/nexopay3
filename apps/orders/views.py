from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import get_language
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from apps.core.http import private_no_store
from apps.events.models import Event
from apps.payments.registry import enabled_methods
from apps.payments.views import start_payment

from .forms import CheckoutForm, RetryPaymentForm
from .models import Order
from .services import CheckoutError, calculate_fees, start_checkout

MAX_LINE_QTY = 50


def _selection(source, event):
    """Parse q_<ticket_type_id>=<qty> pairs into ({id: qty}, display lines)."""
    wanted = {}
    for key, value in source.items():
        if key.startswith("q_") and key[2:].isdigit() and str(value).isdigit() and int(value) > 0:
            wanted[int(key[2:])] = min(int(value), MAX_LINE_QTY)
    types = {t.pk: t for t in event.ticket_types.filter(pk__in=wanted.keys())}
    lines = [
        {"ticket_type": types[pk], "quantity": qty, "total": types[pk].price * qty}
        for pk, qty in wanted.items()
        if pk in types
    ]
    return {line["ticket_type"].pk: line["quantity"] for line in lines}, lines


@login_required
@private_no_store
@ratelimit(key="user", rate="20/m", method="POST", block=True)
def checkout(request, slug):
    event = get_object_or_404(Event.objects.select_related("organizer").exclude(status="draft"), slug=slug)
    source = request.POST if request.method == "POST" else request.GET
    quantities, lines = _selection(source, event)
    if not lines:
        return redirect(event.get_absolute_url() + "#tickets")

    subtotal = sum((line["total"] for line in lines), Decimal("0"))
    fees = calculate_fees(subtotal, event.organizer)
    methods = enabled_methods(request.user)
    user = request.user
    form = CheckoutForm(
        request.POST or None,
        methods=methods,
        requires_payment=fees.total > 0,
        initial={"buyer_name": user.full_name, "buyer_phone": user.phone or "", "delivery_email": user.email},
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            order = start_checkout(
                user=user,
                event=event,
                quantities=quantities,
                buyer_name=data["buyer_name"],
                buyer_phone=data["buyer_phone"],
                delivery_email=data["delivery_email"],
                language=get_language(),
            )
        except CheckoutError as exc:
            form.add_error(None, str(exc))
        else:
            if not user.phone and not type(user).objects.filter(phone=data["buyer_phone"]).exists():
                user.phone = data["buyer_phone"]
                user.save(update_fields=["phone"])
            if order.status == Order.Status.PAID:
                return redirect(order.get_absolute_url() + "?paid=1")
            return start_payment(request, order, data["payment_method"])

    return render(
        request,
        "orders/checkout.html",
        {"event": event, "lines": lines, "fees": fees, "form": form, "methods": methods, "quantities": quantities},
    )


@login_required
@private_no_store
def order_detail(request, reference):
    order = get_object_or_404(
        Order.objects.select_related("event", "event__organizer").prefetch_related(
            "items__ticket_type", "tickets__ticket_type"
        ),
        reference=reference,
    )
    if order.user_id != request.user.pk and not request.user.is_staff:
        raise Http404
    methods = enabled_methods(request.user)
    return render(
        request,
        "orders/detail.html",
        {
            "order": order,
            "retry_form": RetryPaymentForm(methods=methods),
            "methods": methods,
            "just_paid": request.GET.get("paid") == "1" and order.status == Order.Status.PAID,
        },
    )


@login_required
@require_POST
@ratelimit(key="user", rate="10/m", method="POST", block=True)
def order_pay(request, reference):
    order = get_object_or_404(Order, reference=reference, user=request.user)
    if order.status != Order.Status.PENDING_PAYMENT or order.is_hold_expired:
        return redirect(order.get_absolute_url())
    form = RetryPaymentForm(request.POST, methods=enabled_methods(request.user))
    if not form.is_valid():
        return redirect(order.get_absolute_url())
    return start_payment(request, order, form.cleaned_data["payment_method"])
