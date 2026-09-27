from django.db.models.signals import m2m_changed, post_delete, post_migrate, post_save
from django.dispatch import receiver

from apps.core.cache import bump_content_version
from apps.core.images import build_renditions
from apps.events.models import Category, Event, TicketType
from apps.payments.models import PaymentProviderSetting

from .models import FaqItem, FooterColumn, HeroSlide, HomeSection, MenuItem, Page, Partner, SiteSettings, SiteText
from .sitetext import bump_version

CONTENT_MODELS = (
    HomeSection, HeroSlide, Partner, Page, FaqItem, SiteSettings, Category, Event, TicketType,
    MenuItem, FooterColumn, PaymentProviderSetting,
)


def _invalidate(sender, **kwargs):
    bump_content_version()


for _model in CONTENT_MODELS:
    post_save.connect(_invalidate, sender=_model, dispatch_uid=f"cms-invalidate-save-{_model.__name__}")
    post_delete.connect(_invalidate, sender=_model, dispatch_uid=f"cms-invalidate-del-{_model.__name__}")
m2m_changed.connect(_invalidate, sender=Event.categories.through, dispatch_uid="cms-invalidate-event-cats")


@receiver(post_save, sender=SiteText, dispatch_uid="sitetext-changed")
def site_text_changed(sender, **kwargs):
    bump_version()
    bump_content_version()  # cached page fragments may contain the old wording


@receiver(post_migrate, dispatch_uid="sitetext-sync-after-migrate")
def sync_site_texts_after_migrate(sender, app_config=None, using="default", **kwargs):
    """Keep the admin's list of interface texts in step with the code on every deploy."""
    if app_config is None or app_config.label != "cms":
        return
    from .sitetext import sync_from_catalog

    try:
        sync_from_catalog()
    except Exception:  # a missing catalogue must never break migrations
        pass


def _refresh_renditions(instance, field_name: str, store_name: str):
    field_file = getattr(instance, field_name)
    stored = getattr(instance, store_name) or {}
    if not field_file:
        if stored:
            type(instance).objects.filter(pk=instance.pk).update(**{store_name: {}})
        return
    if stored.get("src") == field_file.name:
        return
    renditions = build_renditions(field_file)
    renditions["src"] = field_file.name
    type(instance).objects.filter(pk=instance.pk).update(**{store_name: renditions})
    setattr(instance, store_name, renditions)


@receiver(post_save, sender=Event, dispatch_uid="event-banner-renditions")
def event_banner_renditions(sender, instance, **kwargs):
    _refresh_renditions(instance, "banner", "banner_renditions")


@receiver(post_save, sender=HeroSlide, dispatch_uid="hero-renditions")
def hero_renditions(sender, instance, **kwargs):
    _refresh_renditions(instance, "image", "image_renditions")
