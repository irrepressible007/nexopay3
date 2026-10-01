from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from modeltranslation.admin import TranslationAdmin, TranslationTabularInline
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import AutocompleteSelectFilter, RangeDateTimeFilter
from unfold.decorators import action, display

from apps.core.admin_utils import export_csv, progress_bar
from apps.payments.refunds import cancel_event

from .models import Category, Event, TicketType


@admin.register(Category)
class CategoryAdmin(ModelAdmin, TranslationAdmin):
    list_display = ["name", "slug", "icon", "color", "event_count", "show_on_home", "show_in_hero", "is_active"]
    list_editable = ["show_on_home", "show_in_hero", "is_active"]
    search_fields = ["name_en", "name_bn", "slug"]
    prepopulated_fields = {"slug": ("name_en",)}
    ordering_field = "sort_order"  # drag rows to reorder
    hide_ordering_field = True
    actions = [export_csv]

    def get_queryset(self, request):
        live = Q(events__status__in=("on_sale", "sold_out", "coming_soon"))
        return super().get_queryset(request).annotate(n_events=Count("events", filter=live))

    @display(description=_("Colour"))
    def color(self, obj):
        return format_html('<span class="nx-swatch" style="background:{}"></span>', obj.accent_color)

    @display(description=_("Live events"), ordering="n_events")
    def event_count(self, obj):
        return obj.n_events


class TicketTypeInline(TabularInline, TranslationTabularInline):
    model = TicketType
    extra = 0
    tab = True
    fields = ["name", "price", "stock", "sold_count", "held_count", "is_available", "allow_quantity",
              "max_per_order", "is_bundle", "sort_order"]
    readonly_fields = ["sold_count", "held_count"]
    ordering_field = "sort_order"  # drag rows to reorder
    hide_ordering_field = True
    verbose_name_plural = _("Ticket types")


def _set_status(request, queryset, status, label):
    changed = 0
    for event in queryset.exclude(status__in=(status, Event.Status.CANCELLED)):
        event.status = status
        event.save(update_fields=["status", "published_at", "updated_at"])
        changed += 1
    messages.success(request, _("%(n)s event(s) now %(label)s.") % {"n": changed, "label": label})


@admin.register(Event)
class EventAdmin(ModelAdmin, TranslationAdmin):
    list_display = ["event_header", "status_badge", "starts_at", "sales", "featured", "featured_rank"]
    list_editable = ["featured", "featured_rank"]
    list_filter = [
        "status", "featured", ("starts_at", RangeDateTimeFilter), "categories", "city",
        ("organizer", AutocompleteSelectFilter),
    ]
    list_filter_submit = True
    search_fields = ["title_en", "title_bn", "slug", "organizer__name", "venue_name_en", "city"]
    date_hierarchy = "starts_at"
    autocomplete_fields = ["organizer", "categories"]
    inlines = [TicketTypeInline]
    readonly_fields = ["published_at", "created_at", "updated_at", "banner_preview"]
    list_select_related = ["organizer"]
    warn_unsaved_form = True
    actions = ["put_on_sale", "mark_coming_soon", "mark_ended", "feature", "unfeature", "duplicate", export_csv,
               "cancel_and_refund"]
    actions_row = ["row_view_on_site", "row_duplicate"]
    actions_detail = ["detail_duplicate"]
    export_fields = ["title", "organizer", "status", "starts_at", "venue_name", "city", "sales", "featured"]
    fieldsets = (
        (_("Basics"), {"classes": ["tab"], "fields": ("organizer", "title", "slug", "summary", "categories", "status",
                                                       ("featured", "featured_rank"))}),
        (_("Date & ticket sales"), {"classes": ["tab"], "fields": (("starts_at", "ends_at"),
                                                                   ("sales_start_at", "sales_end_at"),
                                                                   "max_tickets_per_order")}),
        (_("Venue"), {"classes": ["tab"], "fields": ("venue_name", "venue_address", "city", "map_url", "is_online")}),
        (_("Picture & description"), {"classes": ["tab"], "fields": ("banner", "banner_preview", "description",
                                                                     "terms_and_conditions")}),
        (_("Record"), {"classes": ["tab"], "fields": ("published_at", "created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n_sold=Sum("ticket_types__sold_count"),
                                                      n_stock=Sum("ticket_types__stock"))

    @display(description=_("Event"), header=True, ordering="title")
    def event_header(self, obj):
        when = timezone.localtime(obj.starts_at).strftime("%d %b %Y")
        picture = None
        if obj.banner:
            from apps.core.templatetags.nexo import rendition

            url = rendition(obj.banner_renditions, 480) or obj.banner.url
            picture = {"path": url, "squared": True, "width": 64, "height": 40, "borderless": True}
        return [obj.title, f"{obj.organizer.name} · {obj.city} · {when}", obj.title[:1], picture]

    @display(description=_("Status"), ordering="status",
             label={"on_sale": "success", "coming_soon": "info", "sold_out": "warning", "draft": "secondary",
                    "ended": "secondary", "cancelled": "danger"})
    def status_badge(self, obj):
        return obj.status, obj.get_status_display()

    @display(description=_("Tickets sold"), ordering="n_sold")
    def sales(self, obj):
        return progress_bar(obj.n_sold or 0, obj.n_stock or 0)

    @display(description=_("Picture"))
    def banner_preview(self, obj):
        if not obj.banner:
            return _("No picture yet: events with a picture can appear in the home page poster deck.")
        return format_html('<img src="{}" alt="" style="max-width:420px;border-radius:12px">', obj.banner.url)

    # --- list actions ----------------------------------------------------------------
    @action(description=_("Put on sale"))
    def put_on_sale(self, request, queryset):
        _set_status(request, queryset, Event.Status.ON_SALE, _("on sale"))

    @action(description=_("Mark as coming soon"))
    def mark_coming_soon(self, request, queryset):
        _set_status(request, queryset, Event.Status.COMING_SOON, _("coming soon"))

    @action(description=_("Mark as ended"))
    def mark_ended(self, request, queryset):
        _set_status(request, queryset, Event.Status.ENDED, _("ended"))

    @action(description=_("Feature on the homepage"))
    def feature(self, request, queryset):
        for event in queryset:
            event.featured = True
            event.save(update_fields=["featured", "updated_at"])

    @action(description=_("Remove from featured"))
    def unfeature(self, request, queryset):
        for event in queryset:
            event.featured = False
            event.save(update_fields=["featured", "updated_at"])

    @action(description=_("Duplicate as a new draft"))
    def duplicate(self, request, queryset):
        copies = [duplicate_event(e) for e in queryset]
        messages.success(request, _("Created %(n)s draft copy(ies). They stay hidden until you publish them.")
                         % {"n": len(copies)})

    @action(description=_("Cancel event(s) and refund every ticket"))
    def cancel_and_refund(self, request, queryset):
        total = 0
        for event in queryset.exclude(status=Event.Status.CANCELLED):
            total += cancel_event(event, reason=f"{event.title} was cancelled by the organizer.", by=request.user)
        messages.warning(request, _("Cancelled. %(n)s refund(s) created: check Refunds for any needing manual "
                                    "processing.") % {"n": total})

    # --- row and page actions --------------------------------------------------------
    def has_duplicate_permission(self, request, object_id=None):
        return self.has_add_permission(request)

    @action(description=_("View on site"), url_path="view-on-site")
    def row_view_on_site(self, request, object_id):
        return redirect(Event.objects.get(pk=object_id).get_absolute_url())

    @action(description=_("Duplicate"), url_path="duplicate", permissions=["duplicate"])
    def row_duplicate(self, request, object_id):
        copy = duplicate_event(Event.objects.get(pk=object_id))
        messages.success(request, _("Draft copy created. Change its title and date, then publish it."))
        return redirect(reverse("admin:events_event_change", args=[copy.pk]))

    @action(description=_("Duplicate"), url_path="detail-duplicate", icon="content_copy", permissions=["duplicate"])
    def detail_duplicate(self, request, object_id):
        return self.row_duplicate(request, object_id)


@transaction.atomic
def duplicate_event(event: Event) -> Event:
    """A draft copy of an event with its categories and ticket types (no sales, not featured)."""
    types = list(event.ticket_types.all())
    categories = list(event.categories.all())
    base = slugify(f"{event.slug}-copy")[:200]
    slug, n = base, 2
    while Event.objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    event.pk = None
    event.id = None
    event._state.adding = True
    event.slug = slug
    event.status = Event.Status.DRAFT
    event.featured = False
    event.published_at = None
    for attr in ("title_en", "title_bn"):  # each language once (plain `title` is one of these)
        value = getattr(event, attr, "")
        if value:
            setattr(event, attr, f"{value} (copy)"[:200])
    event.save()
    event.categories.set(categories)
    for t in types:
        t.pk = None
        t.id = None
        t._state.adding = True
        t.event = event
        t.sold_count = 0
        t.held_count = 0
        t.save()
    return event
