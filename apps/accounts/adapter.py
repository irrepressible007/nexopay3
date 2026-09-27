from types import SimpleNamespace

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core import context as allauth_context
from django.utils.encoding import force_str


class AccountAdapter(DefaultAccountAdapter):
    """Login-system emails use the brand name admins set in Site settings, not the host name."""

    @staticmethod
    def _site():
        from apps.cms.models import SiteSettings

        return SiteSettings.load()

    def format_email_subject(self, subject: str) -> str:
        return f"{self._site().site_name}: {force_str(subject)}"

    def send_mail(self, template_prefix: str, email: str, context: dict) -> None:
        from apps.cms.sitetext import ensure_applied

        ensure_applied()
        request = allauth_context.request
        ctx = {
            "request": request,
            "email": email,
            "current_site": SimpleNamespace(name=self._site().site_name, domain=request.get_host() if request else ""),
        }
        ctx.update(context)
        self.render_mail(template_prefix, email, ctx).send()
