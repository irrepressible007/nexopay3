from modeltranslation.translator import TranslationOptions, register

from .models import OrganizerProfile


@register(OrganizerProfile)
class OrganizerProfileTR(TranslationOptions):
    fields = ("about",)
