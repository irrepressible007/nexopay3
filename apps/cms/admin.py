from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from modeltranslation.admin import TranslationAdmin
from unfold.admin import ModelAdmin

from .models import FaqItem, HeroSlide, HomeSection, Page, Partner, SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(ModelAdmin, TranslationAdmin):
    fieldsets = (
        ("Brand", {"fields": ("site_name", "tagline", "logo", "logo_on_light", "favicon", "og_image")}),
        ("Colours", {"fields": ("primary_color", "secondary_color", "accent_color", "background_color"),
                     "description": "Hex colours used across the whole site — changes apply instantly."}),
        ("Announcement bar", {"fields": ("announcement_enabled", "announcement_text", "announcement_url")}),
        ("Contact & social", {"fields": ("contact_email", "contact_phone", "address", "facebook_url", "instagram_url",
                                          "youtube_url", "tiktok_url", "linkedin_url", "footer_text")}),
        ("SEO", {"fields": ("meta_description",)}),
        ("Default fees", {"fields": ("default_commission_pct", "default_buyer_fee_pct", "default_buyer_fee_flat"),
                          "description": "Used for organizers without their own fee overrides."}),
        ("Operations", {"fields": ("maintenance_mode",)}),
    )

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = SiteSettings.load()
        return redirect(reverse("admin:cms_sitesettings_change", args=[obj.pk]))


@admin.register(HomeSection)
class HomeSectionAdmin(ModelAdmin, TranslationAdmin):
    list_display = ["__str__", "kind", "sort_order", "is_enabled", "starts_at", "ends_at"]
    list_editable = ["sort_order", "is_enabled"]
    list_filter = ["kind", "is_enabled"]
    fields = ["kind", "title", "subtitle", "category", "image", "link_url", "cta_label", "item_limit", "sort_order",
              "is_enabled", "starts_at", "ends_at"]


@admin.register(HeroSlide)
class HeroSlideAdmin(ModelAdmin, TranslationAdmin):
    list_display = ["title", "event", "sort_order", "is_enabled", "starts_at", "ends_at"]
    list_editable = ["sort_order", "is_enabled"]
    autocomplete_fields = ["event"]


@admin.register(Partner)
class PartnerAdmin(ModelAdmin):
    list_display = ["name", "url", "sort_order", "is_enabled"]
    list_editable = ["sort_order", "is_enabled"]


@admin.register(Page)
class PageAdmin(ModelAdmin, TranslationAdmin):
    list_display = ["title", "slug", "show_in_footer", "is_published", "sort_order", "updated_at"]
    list_editable = ["show_in_footer", "is_published", "sort_order"]
    prepopulated_fields = {"slug": ("title_en",)}


@admin.register(FaqItem)
class FaqItemAdmin(ModelAdmin, TranslationAdmin):
    list_display = ["question", "show_on_home", "is_published", "sort_order"]
    list_editable = ["show_on_home", "is_published", "sort_order"]
