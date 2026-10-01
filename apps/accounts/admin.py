from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm as BaseChangeForm
from django.contrib.auth.forms import UserCreationForm as BaseCreationForm
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import RangeDateFilter
from unfold.decorators import display
from unfold.forms import AdminPasswordChangeForm

from apps.core.admin_utils import export_csv

from .models import User

admin.site.unregister(Group)


class UserCreationForm(BaseCreationForm):
    class Meta:
        model = User
        fields = ("email",)


class UserChangeForm(BaseChangeForm):
    class Meta:
        model = User
        fields = "__all__"


class RoleFilter(admin.SimpleListFilter):
    title = _("role")
    parameter_name = "role"

    def lookups(self, request, model_admin):
        return [("buyer", _("Buyers")), ("organizer", _("Organizers")), ("staff", _("Staff")), ("inactive", _("Blocked"))]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "buyer":
            return queryset.filter(is_staff=False, organizer_profile__isnull=True)
        if value == "organizer":
            return queryset.filter(organizer_profile__isnull=False)
        if value == "staff":
            return queryset.filter(is_staff=True)
        if value == "inactive":
            return queryset.filter(is_active=False)
        return queryset


@admin.register(Group)
class GroupAdmin(ModelAdmin):
    list_display = ["name", "member_count"]
    search_fields = ["name"]
    filter_horizontal = ["permissions"]

    @display(description=_("Members"))
    def member_count(self, obj):
        return obj.user_set.count()


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    ordering = ["-date_joined"]
    list_display = ["person", "phone", "role", "is_active", "date_joined"]
    list_filter = [RoleFilter, "groups", ("date_joined", RangeDateFilter)]
    list_filter_submit = True
    actions = [export_csv]
    export_fields = ["email", "full_name", "phone", "role", "is_active", "date_joined"]
    search_fields = ["email", "full_name", "phone"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "phone", "preferred_language")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)
    formfield_overrides = {}

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("organizer_profile")  # the Role column

    @display(description=_("Person"), header=True, ordering="email")
    def person(self, obj):
        return [obj.full_name or obj.email, obj.email if obj.full_name else "", (obj.full_name or obj.email)[:1]]

    @display(description=_("Role"), label={"Staff": "danger", "Organizer": "info", "Buyer": "secondary"})
    def role(self, obj):
        if obj.is_staff:
            return "Staff"
        return "Organizer" if hasattr(obj, "organizer_profile") else "Buyer"

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "phone" in form.base_fields:
            form.base_fields["phone"].widget = forms.TextInput()
        return form
