"""
Deploy-time safety checks (`manage.py check --deploy`, run by deploy/deploy.sh).

Errors stop a deploy; warnings are printed. They catch settings that are fine on a
laptop or on staging but dangerous on the live site.
"""
from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

LIVE_HOSTS = {"nexopay.com.bd", "www.nexopay.com.bd"}


def _live_site() -> bool:
    return urlparse(settings.SITE_URL).hostname in LIVE_HOSTS


@register(Tags.security, deploy=True)
def nexopay_deploy_checks(app_configs, **kwargs):
    issues = []
    if settings.DEBUG:
        return issues
    if settings.SECRET_KEY.startswith("dev-insecure") or len(set(settings.SECRET_KEY)) < 10:
        issues.append(Error("SECRET_KEY is the development default or too simple.",
                            hint="Set a long random SECRET_KEY in the environment.", id="nexopay.E001"))
    if getattr(settings, "ALLOW_MOCK_PAYMENTS", False) and _live_site():
        issues.append(Error("The test payment gateway is allowed on the live site: anyone could get tickets for free.",
                            hint="Remove ALLOW_MOCK_PAYMENTS from the live environment.", id="nexopay.E002"))
    if settings.ACCOUNT_EMAIL_VERIFICATION != "mandatory" and _live_site():
        issues.append(Warning("Email verification is not mandatory on the live site.",
                              hint="Set ACCOUNT_EMAIL_VERIFICATION=mandatory.", id="nexopay.W001"))
    if settings.ADMIN_URL.strip("/") in ("admin", "control-room"):
        issues.append(Warning("The control room is at a well-known address.",
                              hint="Set ADMIN_URL to something only staff know, e.g. ops-7k2q/.", id="nexopay.W002"))
    return issues
