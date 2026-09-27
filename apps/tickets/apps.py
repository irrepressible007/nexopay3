from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class TicketsConfig(AppConfig):
    name = "apps.tickets"
    label = "tickets"
    verbose_name = _("Tickets")
