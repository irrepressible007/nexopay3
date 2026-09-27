from django.contrib import admin, messages
from django.utils.html import format_html
from modeltranslation.admin import TranslationAdmin, TranslationTabularInline
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display

from apps.payments.refunds import cancel_event

from .models import Category, Event, TicketType


@admin.register(Category)
class CategoryAdmin(ModelAdmin, TranslationAdmin):
    list_display = ["name", "slug", "icon", "color", "sort_order", "show_on_home", "is_active"]
    list_editable = ["sort_order", "show_on_home", "is_active"]
    prepopulated_fields = {"slug": ("name_en",)}

    @display(description="Colour")
    def color(self, obj):
        return format_html('<span style="display:inline-block;width:18px;height:18px;border-radius:6px;background:{}"></span>',
                           obj.accent_color)


class TicketTypeInline(TabularInline, TranslationTabularInline):
    model = TicketType
    extra = 0
    fields = ["name", "price", "stock", "sold_count", "held_count", "is_available", "allow_quantity",
              "max_per_order", "is_bundle", "sort_order"]
    readonly_fields = ["sold_count", "held_count"]


@admin.register(Event)
class EventAdmin(ModelAdmin, TranslationAdmin):
    list_display = ["title", "organizer", "status_badge", "featured", "featured_rank", "starts_at", "sold"]
    list_editable = ["featured", "featured_rank"]
    list_filter = ["status", "featured", "categories", "city"]
    search_fields = ["title_en", "title_bn", "organizer__name", "venue_name_en"]
    date_hierarchy = "starts_at"
    filter_horizontal = ["categories"]
    inlines = [TicketTypeInline]
    readonly_fields = ["published_at", "created_at", "updated_at"]
    actions = ["feature", "unfeature", "cancel_and_refund"]
    list_select_related = ["organizer"]
    fieldsets = (
        (None, {"fields": ("organizer", "title", "slug", "summary", "status", "featured", "featured_rank", "categories")}),
        ("When", {"fields": ("starts_at", "ends_at", "sales_start_at", "sales_end_at")}),
        ("Where", {"fields": ("venue_name", "venue_address", "city", "map_url", "is_online")}),
        ("Content", {"fields": ("banner", "description", "terms_and_conditions", "max_tickets_per_order")}),
        ("Meta", {"fields": ("published_at", "created_at", "updated_at")}),
    )

    @display(description="Status", label={"on_sale": "success", "coming_soon": "info", "sold_out": "warning",
                                          "draft": "secondary", "ended": "secondary", "cancelled": "danger"})
    def status_badge(self, obj):
        return obj.status

    @display(description="Sold")
    def sold(self, obj):
        types = obj.ticket_types.all()
        return f"{sum(t.sold_count for t in types)} / {sum(t.stock for t in types)}"

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("ticket_types")

    @action(description="Feature on the homepage")
    def feature(self, request, queryset):
        queryset.update(featured=True)

    @action(description="Remove from featured")
    def unfeature(self, request, queryset):
        queryset.update(featured=False)

    @action(description="Cancel event(s) and refund every ticket")
    def cancel_and_refund(self, request, queryset):
        total = 0
        for event in queryset.exclude(status=Event.Status.CANCELLED):
            total += cancel_event(event, reason=f"{event.title} was cancelled by the organizer.", by=request.user)
        messages.warning(request, f"Cancelled. {total} refund(s) created — check Refunds for any needing manual processing.")
