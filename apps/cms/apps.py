from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CmsConfig(AppConfig):
    name = "apps.cms"
    label = "cms"
    verbose_name = _("Website content")

    def ready(self):
        from . import signals  # noqa: F401
