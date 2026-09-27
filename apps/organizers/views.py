import csv
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.mail import mail_admins, send_mail
from django.db import transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.http import private_no_store
from apps.events.models import Event
from apps.orders.models import Order, OrderItem
from apps.payments.models import Refund
from apps.payments.refunds import RefundError, process_refund, request_refund
from apps.support.models import Reason, SupportRoute
from apps.tickets.models import ScanLog, ScannerAccess, Ticket

from .forms import EventForm, OrganizerApplicationForm, ScannerInviteForm, TicketTypeFormSet
from .models import OrganizerProfile

PAID_STATES = (Order.Status.PAID, Order.Status.PARTIALLY_REFUNDED)


def organizer_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        profile = getattr(request.user, "organizer_profile", None)
        if not profile or not profile.is_approved:
            return redirect("organizers:apply")
        request.organizer = profile
        return view(request, *args, **kwargs)

    return wrapper


def _own_event(request, slug):
    event = get_object_or_404(Event.objects.select_related("organizer"), slug=slug)
    if event.organizer_id != request.organizer.pk:
        raise Http404
    return event


# --- Application / vetting ----------------------------------------------------------
@private_no_store
def apply(request):
    if not request.user.is_authenticated:
        return render(request, "organizers/apply_landing.html")
    profile = getattr(request.user, "organizer_profile", None)
    if profile and profile.status != OrganizerProfile.Status.REJECTED:
        return render(request, "organizers/apply_status.html", {"profile": profile})

    form = OrganizerApplicationForm(
        request.POST or None,
        request.FILES or None,
        instance=profile,
        initial={"contact_email": request.user.email, "contact_phone": request.user.phone or ""},
    )
    if request.method == "POST" and form.is_valid():
        org = form.save(commit=False)
        org.user = request.user
        org.status = OrganizerProfile.Status.PENDING_REVIEW
        if not org.slug:
            base = slugify(org.name)[:150] or f"organizer-{request.user.pk}"
            slug, n = base, 2
            while OrganizerProfile.objects.filter(slug=slug).exclude(pk=org.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            org.slug = slug
        org.save()
        _notify_new_application(request, org)
        messages.success(request, _("Application received! We'll review it and email you shortly."))
        return redirect("organizers:apply")
    return render(request, "organizers/apply.html", {"form": form, "profile": profile})


def _notify_new_application(request, org):
    route = SupportRoute.objects.filter(reason=Reason.LIST_EVENT).first()
    body = (
        f"New organizer application: {org.name}\n{org.contact_email} · {org.contact_phone}\n\n{org.application_note}\n\n"
        f"Review: {request.build_absolute_uri('/')}"
    )
    try:
        if route:
            send_mail(f"[Organizer application] {org.name}", body, None, [route.email])
        else:
            mail_admins(f"Organizer application: {org.name}", body)
    except Exception:
        pass


# --- Dashboard -------------------------------------------------------------------------
@organizer_required
@private_no_store
def dashboard(request):
    org = request.organizer
    events = (
        Event.objects.filter(organizer=org)
        .annotate(
            sold=Sum("ticket_types__sold_count"),
            capacity=Sum("ticket_types__stock"),
        )
        .order_by("-starts_at")
    )
    paid_orders = Order.objects.filter(event__organizer=org, status__in=PAID_STATES)
    totals = paid_orders.aggregate(gross=Sum("subtotal"), net=Sum("organizer_net"), orders=Count("pk"))
    tickets = Ticket.objects.filter(event__organizer=org).exclude(status=Ticket.Status.REFUNDED)
    stats = {
        "gross": totals["gross"] or 0,
        "net": totals["net"] or 0,
        "orders": totals["orders"] or 0,
        "tickets": tickets.count(),
        "checked_in": tickets.filter(status=Ticket.Status.REDEEMED).count(),
        "upcoming": events.filter(starts_at__gte=timezone.now()).exclude(status__in=("ended", "cancelled")).count(),
    }
    recent = paid_orders.select_related("event").order_by("-paid_at")[:8]
    return render(request, "organizers/dashboard.html", {"org": org, "events": events, "stats": stats, "recent": recent})


# --- Event builder ---------------------------------------------------------------------
MULTI_SEGMENT_PRESET = [
    {"name_en": "Entry", "price": 150, "stock": 300},
    {"name_en": "Entry + Segment A", "price": 250, "stock": 100},
    {"name_en": "Entry + Segment B", "price": 250, "stock": 100},
    {"name_en": "Golden Ticket — all segments", "price": 600, "stock": 50, "is_bundle": True},
]


@organizer_required
@private_no_store
def event_edit(request, slug=None):
    org = request.organizer
    event = _own_event(request, slug) if slug else Event(organizer=org)
    if event.pk and event.status in (Event.Status.ENDED, Event.Status.CANCELLED):
        messages.info(request, _("Ended or cancelled events can't be edited."))
        return redirect("organizers:event", slug=event.slug)

    form = EventForm(request.POST or None, request.FILES or None, instance=event)
    formset = TicketTypeFormSet(request.POST or None, instance=event, prefix="tt")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        action = request.POST.get("action", "draft")
        with transaction.atomic():
            event = form.save(commit=False)
            event.organizer = org
            if action == "publish" and event.status == Event.Status.DRAFT:
                opens_later = event.sales_start_at and event.sales_start_at > timezone.now()
                event.status = Event.Status.COMING_SOON if opens_later else Event.Status.ON_SALE
            event.save()
            form.save_m2m()
            formset.instance = event
            for i, obj in enumerate(formset.save(commit=False)):
                obj.sort_order = obj.sort_order or i
                obj.save()
            for obj in formset.deleted_objects:
                obj.delete()
            event.refresh_sold_out_status()
        messages.success(
            request, _("Event published!") if action == "publish" else _("Saved.")
        )
        return redirect("organizers:event", slug=event.slug)

    return render(
        request,
        "organizers/event_form.html",
        {"form": form, "formset": formset, "event": event, "preset": MULTI_SEGMENT_PRESET},
    )


# --- Per-event dashboard --------------------------------------------------------------
@organizer_required
@private_no_store
def event_detail(request, slug):
    event = _own_event(request, slug)
    types = list(event.ticket_types.all())
    revenue = {
        row["ticket_type"]: row
        for row in OrderItem.objects.filter(order__event=event, order__status__in=PAID_STATES)
        .values("ticket_type")
        .annotate(qty=Sum("quantity"), gross=Sum(ExpressionWrapper(F("unit_price") * F("quantity"), output_field=DecimalField())))
    }
    tickets = Ticket.objects.filter(event=event)
    checkin = tickets.aggregate(
        total=Count("pk", filter=~Q(status=Ticket.Status.REFUNDED)),
        redeemed=Count("pk", filter=Q(status=Ticket.Status.REDEEMED)),
    )
    orders = Order.objects.filter(event=event, status__in=PAID_STATES + (Order.Status.REFUNDED,))
    q = request.GET.get("q", "").strip()
    if q:
        orders = orders.filter(Q(reference__icontains=q) | Q(delivery_email__icontains=q) | Q(buyer_phone__icontains=q)
                               | Q(buyer_name__icontains=q))
    totals = orders.filter(status__in=PAID_STATES).aggregate(gross=Sum("subtotal"), net=Sum("organizer_net"))
    return render(
        request,
        "organizers/event_detail.html",
        {
            "event": event,
            "types": types,
            "revenue": revenue,
            "checkin": checkin,
            "totals": totals,
            "orders": orders.prefetch_related("items__ticket_type").order_by("-paid_at")[:100],
            "query": q,
            "scans": ScanLog.objects.filter(event=event).select_related("ticket__ticket_type", "scanned_by")[:15],
            "staff": ScannerAccess.objects.filter(event=event).select_related("user"),
            "invite_form": ScannerInviteForm(),
            "pending_refunds": Refund.objects.filter(order__event=event, status=Refund.Status.REQUESTED).count(),
        },
    )


@organizer_required
def attendees_csv(request, slug):
    event = _own_event(request, slug)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{event.slug}-attendees.csv"'
    response.write("﻿")  # Excel-friendly UTF-8 (Bangla names)
    writer = csv.writer(response)
    writer.writerow(["Ticket code", "Ticket type", "Status", "Name", "Email", "Phone", "Order", "Paid at", "Checked in at"])
    for t in Ticket.objects.filter(event=event).select_related("ticket_type", "order").order_by("order__paid_at"):
        writer.writerow([
            t.code, t.ticket_type.name, t.get_status_display(), t.holder_name or t.order.buyer_name,
            t.order.delivery_email, t.order.buyer_phone, t.order.reference,
            timezone.localtime(t.order.paid_at).strftime("%Y-%m-%d %H:%M") if t.order.paid_at else "",
            timezone.localtime(t.redeemed_at).strftime("%Y-%m-%d %H:%M") if t.redeemed_at else "",
        ])
    return response


@organizer_required
@require_POST
def scanner_add(request, slug):
    event = _own_event(request, slug)
    form = ScannerInviteForm(request.POST)
    if form.is_valid():
        user = get_user_model().objects.filter(email__iexact=form.cleaned_data["email"]).first()
        if user is None:
            messages.error(request, _("No Nexopay account uses that email. Ask them to sign up first."))
        else:
            ScannerAccess.objects.get_or_create(event=event, user=user, defaults={"granted_by": request.user})
            messages.success(request, _("%(email)s can now scan tickets for this event.") % {"email": user.email})
    return redirect(reverse("organizers:event", kwargs={"slug": slug}) + "#staff")


@organizer_required
@require_POST
def scanner_remove(request, slug, pk):
    event = _own_event(request, slug)
    ScannerAccess.objects.filter(event=event, pk=pk).delete()
    messages.success(request, _("Scanner access removed."))
    return redirect(reverse("organizers:event", kwargs={"slug": slug}) + "#staff")


@organizer_required
@require_POST
def order_refund(request, slug, reference):
    event = _own_event(request, slug)
    order = get_object_or_404(Order, event=event, reference=reference)
    reason = request.POST.get("reason", "").strip() or _("Refund requested by the organizer")
    org = request.organizer
    try:
        refund = request_refund(order=order, reason=reason, by=request.user, approve=org.can_issue_refunds)
    except RefundError as exc:
        messages.error(request, str(exc))
    else:
        if org.can_issue_refunds:
            refund = process_refund(refund, by=request.user)
            if refund.status == Refund.Status.SUCCEEDED:
                messages.success(request, _("Refund issued for %(ref)s.") % {"ref": order.reference})
            else:
                messages.info(request, _("Refund approved — our team will complete it shortly."))
        else:
            messages.success(request, _("Refund requested. Nexopay will review and process it."))
    return redirect(reverse("organizers:event", kwargs={"slug": slug}) + "#orders")
