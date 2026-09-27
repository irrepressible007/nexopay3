from modeltranslation.translator import TranslationOptions, register

from .models import PaymentProviderSetting


@register(PaymentProviderSetting)
class PaymentProviderSettingTR(TranslationOptions):
    fields = ("display_name",)
