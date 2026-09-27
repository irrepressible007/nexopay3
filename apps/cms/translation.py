from modeltranslation.translator import TranslationOptions, register

from .models import FaqItem, FooterColumn, HeaderLink, HeroSlide, HomeSection, MenuItem, Page, SiteSettings


@register(SiteSettings)
class SiteSettingsTR(TranslationOptions):
    fields = ("tagline", "address", "footer_text", "meta_description", "announcement_text")


@register(HomeSection)
class HomeSectionTR(TranslationOptions):
    fields = ("title", "subtitle", "cta_label")


@register(HeroSlide)
class HeroSlideTR(TranslationOptions):
    fields = ("title", "subtitle", "cta_label")


@register(Page)
class PageTR(TranslationOptions):
    fields = ("title", "body", "meta_description")


@register(FaqItem)
class FaqItemTR(TranslationOptions):
    fields = ("question", "answer")


@register(FooterColumn)
class FooterColumnTR(TranslationOptions):
    fields = ("title",)


@register(MenuItem)
class MenuItemTR(TranslationOptions):
    fields = ("label",)


@register(HeaderLink)
class HeaderLinkTR(TranslationOptions):
    fields = ("label",)
