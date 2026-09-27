from django import forms
from django.contrib import admin, messages
from django.db import models
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.html import format_html
from modeltranslation.admin import TranslationAdmin, TranslationTabularInline
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import action, display

from .models import (
    FaqItem, FooterColumn, HeaderLink, HeroSlide, HomeSection, MenuItem, Page, Partner, SiteSettings, SiteText,
)
from apps.core.cache import bump_content_version

from .sitetext import bump_version


class SiteSettingsForm(forms.ModelForm):
    email_password = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False),
        help_text="Leave empty to keep the saved password.",
    )

    class Meta:
        model = SiteSettings
        fields = "__all__"

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("email_password"):
            obj.email_password = self.cleaned_data["email_password"]
        if commit:
            obj.save()
        return obj


@admin.register(SiteSettings)
class SiteSettingsAdmin(ModelAdmin, TranslationAdmin):
    form = SiteSettingsForm
    fieldsets = (
        ("Brand", {"fields": ("site_name", "tagline", "logo", "logo_on_color", "favicon", "og_image"),
                   "description": "Empty logo fields use the built-in Nexopay logo."}),
        ("Colours", {"fields": ("primary_color", "secondary_color", "accent_color", "background_color"),
                     "description": "Hex colours used across the whole site. Changes apply instantly."}),
        ("Announcement bar", {"fields": ("announcement_enabled", "announcement_text", "announcement_url")}),
        ("Contact & social", {"fields": ("contact_email", "contact_phone", "address", "facebook_url", "instagram_url",
                                          "youtube_url", "tiktok_url", "linkedin_url", "footer_text")}),
        ("SEO", {"fields": ("meta_description",)}),
        ("Checkout", {"fields": ("hold_minutes", "default_commission_pct", "default_buyer_fee_pct",
                                 "default_buyer_fee_flat"),
                      "description": "Default fees apply to organizers without their own fee settings."}),
        ("Outgoing email", {"fields": ("email_from_name", "email_from_address", "email_host", "email_port",
                                       "email_use_ssl", "email_use_tls", "email_username", "email_password"),
                            "description": "Fill in the mailbox that sends tickets (from cPanel › Email Accounts). "
                                           "Leave the host empty to use the server configuration."}),
        ("Operations", {"fields": ("maintenance_mode",)}),
    )

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        return redirect(reverse("admin:cms_sitesettings_change", args=[SiteSettings.load().pk]))


# --- Site texts --------------------------------------------------------------------------
class CustomizedFilter(admin.SimpleListFilter):
    title = "status"
    parameter_name = "customized"

    def lookups(self, request, model_admin):
        return [("yes", "Customised"), ("no", "Using defaults")]

    def queryset(self, request, queryset):
        blank = models.Q(text_en="", text_en_plural="", text_bn="")
        if self.value() == "yes":
            return queryset.exclude(blank)
        if self.value() == "no":
            return queryset.filter(blank)
        return queryset


class GroupFilter(admin.SimpleListFilter):
    title = "page / area"
    parameter_name = "group"

    def lookups(self, request, model_admin):
        groups = SiteText.objects.order_by("group").values_list("group", flat=True).distinct()
        return [(g, g) for g in groups]

    def queryset(self, request, queryset):
        return queryset.filter(group=self.value()) if self.value() else queryset


@admin.register(SiteText)
class SiteTextAdmin(ModelAdmin):
    list_display = ["original", "text_en", "text_bn", "group"]
    list_editable = ["text_en", "text_bn"]
    list_filter = [GroupFilter, CustomizedFilter]
    search_fields = ["msgid", "text_en", "text_bn", "default_bn"]
    list_per_page = 50
    readonly_fields = ["msgid", "msgid_plural", "default_bn", "placeholders", "group", "location", "updated_at"]
    fieldsets = (
        ("Original", {"fields": ("msgid", "msgid_plural", "default_bn", "placeholders", "group", "location")}),
        ("Your wording", {"fields": ("text_en", "text_en_plural", "text_bn"),
                          "description": "Leave a field empty to keep the default. Words like %(name)s are filled in "
                                         "automatically. Keep them exactly as they are."}),
    )
    actions = ["reset_to_default"]
    formfield_overrides = {models.TextField: {"widget": forms.Textarea(attrs={"rows": 2, "cols": 38})}}

    def has_add_permission(self, request):
        return False  # texts come from the code; run sync_site_texts after updates

    def has_delete_permission(self, request, obj=None):
        return False

    @display(description="Original text")
    def original(self, obj):
        if obj.default_bn:
            return format_html(
                "<div style='white-space:normal;max-width:28rem'>{}<br><small style='opacity:.6'>{}</small></div>",
                obj.msgid, obj.default_bn,
            )
        return format_html("<div style='white-space:normal;max-width:28rem'>{}</div>", obj.msgid)

    def save_model(self, request, obj, form, change):
        obj.full_clean()
        super().save_model(request, obj, form, change)

    @action(description="Reset selected texts to default")
    def reset_to_default(self, request, queryset):
        count = queryset.update(text_en="", text_en_plural="", text_bn="")
        bump_version()
        bump_content_version()
        messages.success(request, f"{count} text(s) reset.")

    def get_changelist_formset(self, request, **kwargs):
        formset_class = super().get_changelist_formset(request, **kwargs)

        class ValidatingFormSet(formset_class):
            def clean(self):
                super().clean()
                for form in self.forms:
                    if form.instance.pk and form.has_changed():
                        try:
                            form.instance.full_clean()
                        except forms.ValidationError as exc:
                            for field, errors in exc.message_dict.items():
                                form.add_error(field if field in form.fields else None, errors)

        return ValidatingFormSet


# --- Homepage & navigation ------------------------------------------------------------
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


@admin.register(HeaderLink)
class HeaderMenuAdmin(ModelAdmin, TranslationAdmin):
    list_display = ["label", "url", "sort_order", "is_enabled", "open_in_new_tab"]
    list_editable = ["sort_order", "is_enabled"]
    fields = ["label", "url", "open_in_new_tab", "sort_order", "is_enabled"]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(location=MenuItem.Location.HEADER)

    def save_model(self, request, obj, form, change):
        obj.location = MenuItem.Location.HEADER
        obj.column = None
        super().save_model(request, obj, form, change)


class FooterLinkInline(TabularInline, TranslationTabularInline):
    model = MenuItem
    fk_name = "column"
    extra = 0
    fields = ["label", "url", "open_in_new_tab", "sort_order", "is_enabled"]


@admin.register(FooterColumn)
class FooterColumnAdmin(ModelAdmin, TranslationAdmin):
    list_display = ["title", "link_count", "sort_order", "is_enabled"]
    list_editable = ["sort_order", "is_enabled"]
    inlines = [FooterLinkInline]

    @display(description="Links")
    def link_count(self, obj):
        return obj.items.count()

    def save_formset(self, request, form, formset, change):
        for obj in formset.save(commit=False):
            obj.location = MenuItem.Location.FOOTER
            obj.save()
        for obj in formset.deleted_objects:
            obj.delete()


@admin.register(Partner)
class PartnerAdmin(ModelAdmin):
    list_display = ["name", "url", "sort_order", "is_enabled"]
    list_editable = ["sort_order", "is_enabled"]


@admin.register(Page)
class PageAdmin(ModelAdmin, TranslationAdmin):
    list_display = ["title", "slug", "is_published", "has_content", "sort_order", "updated_at"]
    list_editable = ["is_published", "sort_order"]
    prepopulated_fields = {"slug": ("title_en",)}

    @display(description="Written", boolean=True)
    def has_content(self, obj):
        return bool(obj.body_en or obj.body_bn)


@admin.register(FaqItem)
class FaqItemAdmin(ModelAdmin, TranslationAdmin):
    list_display = ["question", "show_on_home", "is_published", "sort_order"]
    list_editable = ["show_on_home", "is_published", "sort_order"]
