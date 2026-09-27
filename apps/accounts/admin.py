from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm as BaseChangeForm
from django.contrib.auth.forms import UserCreationForm as BaseCreationForm
from django.contrib.auth.models import Group
from unfold.admin import ModelAdmin
from unfold.forms import AdminPasswordChangeForm

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


@admin.register(Group)
class GroupAdmin(ModelAdmin):
    search_fields = ["name"]
    filter_horizontal = ["permissions"]


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    ordering = ["-date_joined"]
    list_display = ["email", "full_name", "phone", "is_staff", "is_active", "date_joined"]
    list_filter = ["is_staff", "is_active", "date_joined"]
    search_fields = ["email", "full_name", "phone"]
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profile", {"fields": ("full_name", "phone", "preferred_language")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)
    formfield_overrides = {}

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "phone" in form.base_fields:
            form.base_fields["phone"].widget = forms.TextInput()
        return form
