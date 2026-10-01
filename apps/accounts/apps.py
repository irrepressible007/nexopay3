from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AccountsConfig(AppConfig):
    name = "apps.accounts"
    label = "accounts"
    verbose_name = _("People")

    def ready(self):
        from django.db.models.signals import post_migrate

        post_migrate.connect(_create_staff_roles, dispatch_uid="accounts-staff-roles")


def _create_staff_roles(sender, app_config=None, using="default", **kwargs):
    """After the last app migrates (permissions exist by then), add the ready-made staff roles."""
    from django.apps import apps

    if app_config is None or app_config is not list(apps.get_app_configs())[-1]:
        return
    from .roles import ensure_staff_roles

    ensure_staff_roles(using)
