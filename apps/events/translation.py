from modeltranslation.translator import TranslationOptions, register

from .models import Category, Event, TicketType


@register(Category)
class CategoryTR(TranslationOptions):
    fields = ("name",)


@register(Event)
class EventTR(TranslationOptions):
    fields = ("title", "summary", "description", "terms_and_conditions", "venue_name")


@register(TicketType)
class TicketTypeTR(TranslationOptions):
    fields = ("name", "description")
