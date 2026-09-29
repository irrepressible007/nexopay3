"""
Outgoing email, configured in the admin (Site settings › Outgoing email).

- Email host filled in: sent over SMTP with those settings.
- Email host empty: handed to this server's own mail program (sendmail). On cPanel that is
  Exim, which signs and delivers it: no mailbox password, and nothing a hosting firewall
  blocks (many hosts stop websites from connecting to mail servers). Where there is no mail
  program (local development), the EMAIL_* settings are used instead.
"""
import os
import shutil
import subprocess
from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail.backends.smtp import EmailBackend as SMTPBackend


class MailProgramError(Exception):
    """The server's mail program didn't accept a message."""


def mail_program() -> list[str] | None:
    command = list(getattr(settings, "SENDMAIL_COMMAND", ["/usr/sbin/sendmail"]))
    return command if command and (os.path.isfile(command[0]) or shutil.which(command[0])) else None


class SiteEmailBackend(SMTPBackend):
    def __init__(self, **kwargs):
        from apps.cms.models import SiteSettings

        site = SiteSettings.load()
        self._site = site
        self._program = None if site.email_host else mail_program()
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
        if self._program:
            return self._send_with_program(email_messages)
        return super().send_messages(email_messages)

    def _send_with_program(self, email_messages) -> int:
        sent = 0
        for message in email_messages:
            recipients = message.recipients()
            if not recipients:
                continue
            envelope_sender = parseaddr(message.from_email)[1]
            command = [*self._program, "-i", *(["-f", envelope_sender] if envelope_sender else []), "--", *recipients]
            try:
                result = subprocess.run(command, input=message.message().as_bytes(), capture_output=True,
                                        timeout=self.timeout or 30)
            except (OSError, subprocess.TimeoutExpired) as exc:
                if not self.fail_silently:
                    raise MailProgramError(f"couldn't run the mail program: {exc}") from exc
                continue
            if result.returncode != 0:
                if not self.fail_silently:
                    reason = result.stderr.decode(errors="replace").strip() or f"exit code {result.returncode}"
                    raise MailProgramError(reason)
                continue
            sent += 1
        return sent

    def default_sender(self) -> str:
        site = self._site
        if site.email_from_address:
            return formataddr((site.email_from_name or site.site_name, site.email_from_address))
        return ""
