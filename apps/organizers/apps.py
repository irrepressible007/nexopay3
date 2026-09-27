from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class OrganizersConfig(AppConfig):
    name = "apps.organizers"
    label = "organizers"
    verbose_name = _("Organizers")
