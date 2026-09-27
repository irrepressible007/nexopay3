from django.conf import settings
from django.utils.module_loading import import_string

from .models import PaymentProviderSetting, Provider

PROVIDER_CLASSES = {
    Provider.MOCK: "apps.payments.providers.mock.MockProvider",
    Provider.SSLCOMMERZ: "apps.payments.providers.sslcommerz.SSLCommerzProvider",
    Provider.BKASH: "apps.payments.providers.bkash.BkashProvider",
    Provider.NAGAD: "apps.payments.providers.nagad.NagadProvider",
    Provider.UPAY: "apps.payments.providers.upay.UpayProvider",
    Provider.PATHAOPAY: "apps.payments.providers.pathaopay.PathaoPayProvider",
}


def provider_class(code: str):
    path = PROVIDER_CLASSES.get(code)
    if not path:
        return None
    try:
        return import_string(path)
    except ImportError:
        return None


def mock_allowed() -> bool:
    return settings.DEBUG or getattr(settings, "ALLOW_MOCK_PAYMENTS", False)


def get_provider(code: str, require_enabled: bool = True):
    if code not in PROVIDER_CLASSES:
        return None
    if code == Provider.MOCK and not mock_allowed():
        return None
    setting = PaymentProviderSetting.objects.filter(provider=code).first()
    if setting is None or (require_enabled and not setting.is_enabled):
        return None
    try:
        cls = import_string(PROVIDER_CLASSES[code])
    except ImportError:
        return None
    return cls(setting)


def enabled_methods(user=None):
    """Payment methods offered at checkout, in admin-defined order."""
    methods = []
    for setting in PaymentProviderSetting.objects.filter(is_enabled=True).exclude(provider=Provider.FREE):
        if setting.provider == Provider.MOCK and not mock_allowed():
            continue
        methods.append(setting)
    return methods
