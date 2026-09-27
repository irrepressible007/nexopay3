"""
SMTP backend configured from the admin (Site settings › Outgoing email).
Falls back to the EMAIL_* settings/env when no host is entered in the admin.
"""
from email.utils import formataddr

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend


class SiteEmailBackend(SMTPBackend):
    def __init__(self, **kwargs):
        from apps.cms.models import SiteSettings

        site = SiteSettings.load()
        self._site = site
        if site.email_host:
            kwargs.setdefault("host", site.email_host)
            kwargs.setdefault("port", site.email_port)
            kwargs.setdefault("username", site.email_username)
            kwargs.setdefault("password", site.email_password)
            kwargs.setdefault("use_ssl", site.email_use_ssl)
            kwargs.setdefault("use_tls", site.email_use_tls and not site.email_use_ssl)
        super().__init__(**kwargs)

    def send_messages(self, email_messages):
        sender = self.default_sender()
        if sender:
            for message in email_messages:
                if not message.from_email or message.from_email == settings.DEFAULT_FROM_EMAIL:
                    message.from_email = sender
        return super().send_messages(email_messages)

    def default_sender(self) -> str:
        site = self._site
        if site.email_from_address:
            return formataddr((site.email_from_name or site.site_name, site.email_from_address))
        return ""
