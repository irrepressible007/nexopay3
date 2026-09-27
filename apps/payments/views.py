import logging

from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt

from .models import PaymentAttempt
from .registry import get_provider
from .services import PaymentError, new_attempt

logger = logging.getLogger(__name__)


def start_payment(request, order, provider_code):
    """Create an attempt for `order` and send the buyer to the provider."""
    provider = get_provider(provider_code)
    if provider is None:
        messages.error(request, _("That payment method is not available right now."))
        return redirect(order.get_absolute_url())
    attempt = new_attempt(order, provider_code)
    try:
        url = provider.initiate(attempt, request)
    except PaymentError as exc:
        logger.warning("Payment initiation failed for %s: %s", attempt.tran_id, exc)
        attempt.status = PaymentAttempt.Status.FAILED
        attempt.save(update_fields=["status", "updated_at"])
        messages.error(request, _("We could not reach the payment provider. Please try again or choose another method."))
        return redirect(order.get_absolute_url())
    return redirect(url)


@csrf_exempt  # providers post back from their own domain; we verify server-side instead
def payment_return(request, provider):
    handler = get_provider(provider, require_enabled=False)
    if handler is None:
        raise Http404
    try:
        attempt = handler.handle_return(request)
    except PaymentError as exc:
        logger.warning("Return handling failed (%s): %s", provider, exc)
        attempt = None
    if attempt is None:
        messages.error(request, _("We could not confirm that payment. If money was deducted, please contact support."))
        return redirect("accounts:orders")
    attempt.refresh_from_db()
    order_url = attempt.order.get_absolute_url()
    if attempt.status == PaymentAttempt.Status.SUCCEEDED:
        return redirect(order_url + "?paid=1")
    if attempt.status == PaymentAttempt.Status.CANCELLED:
        messages.info(request, _("Payment cancelled. Your tickets are still held for a few minutes."))
    elif attempt.status == PaymentAttempt.Status.FAILED:
        messages.error(request, _("The payment did not go through. You can try again or use another method."))
    return redirect(order_url)


@csrf_exempt
def payment_ipn(request, provider):
    handler = get_provider(provider, require_enabled=False)
    if handler is None:
        raise Http404
    try:
        handler.handle_ipn(request)
    except PaymentError as exc:
        logger.warning("IPN rejected (%s): %s", provider, exc)
        return HttpResponseBadRequest("rejected")
    return HttpResponse("OK")


def mock_gateway(request, tran_id):
    """Fake checkout page for development and staging."""
    provider = get_provider("mock")
    attempt = PaymentAttempt.objects.select_related("order__event").filter(tran_id=tran_id).first()
    if provider is None or attempt is None:
        raise Http404
    return render(
        request,
        "payments/mock_gateway.html",
        {
            "attempt": attempt,
            "success_url": provider.return_url(attempt, "success"),
            "cancel_url": provider.return_url(attempt, "cancel"),
        },
    )
