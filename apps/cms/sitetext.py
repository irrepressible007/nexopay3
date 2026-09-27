"""
Admin-editable interface texts.

Every string the code marks for translation is mirrored as a SiteText row
(`sync_site_texts`). When an admin overrides the English or Bangla wording, the
override is written into Django's in-memory translation catalogs, so templates,
forms, messages, emails and PDFs all show it — no code change, no deploy.

Overrides are re-applied lazily in every process (web workers and cron) when
the shared version number in the cache changes.
"""
import hashlib
import logging
import re
import uuid
from pathlib import Path

import nh3
from django.conf import settings
from django.core.cache import cache
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

VERSION_KEY = "sitetext:version"
_PLACEHOLDER = re.compile(r"%\(\w+\)[sd]|%[sd]|\{\w+\}")
_MISSING = object()
_state = {"version": None, "originals": {}, "catalog_ids": {}}

# Where a string lives in the code → the group admins see it under.
GROUPS = [
    ("templates/cms/sections/", "Homepage"),
    ("templates/cms/home", "Homepage"),
    ("templates/partials/event_card", "Event cards"),
    ("templates/partials/", "Header, footer & menus"),
    ("templates/base.html", "Header, footer & menus"),
    ("templates/events/catalog", "Events list & filters"),
    ("templates/events/", "Event page & tickets panel"),
    ("templates/orders/", "Checkout & orders"),
    ("apps/orders/", "Checkout & orders"),
    ("templates/payments/", "Checkout & orders"),
    ("apps/payments/views", "Checkout & orders"),
    ("templates/account/", "Log in & sign up"),
    ("templates/accounts/", "My tickets & account"),
    ("templates/tickets/", "My tickets & account"),
    ("apps/accounts/", "My tickets & account"),
    ("templates/emails/", "Emails & PDF tickets"),
    ("apps/tickets/tasks", "Emails & PDF tickets"),
    ("apps/tickets/rendering", "Emails & PDF tickets"),
    ("apps/payments/tasks", "Emails & PDF tickets"),
    ("templates/organizers/", "Organizer area"),
    ("apps/organizers/", "Organizer area"),
    ("templates/scan/", "Gate scanner"),
    ("apps/tickets/scan", "Gate scanner"),
    ("templates/support/", "Contact & support"),
    ("apps/support/", "Contact & support"),
    ("templates/cms/", "Pages & FAQ"),
    ("apps/core/", "General"),
    ("apps/accounts/allauth_texts", "Log in & sign up"),
]


def group_for(path: str) -> str:
    path = path.replace("\\", "/")
    if path.startswith("apps/accounts/allauth_texts"):
        return "Log in & sign up"
    if path.endswith("models.py"):
        return "Field labels (forms & admin)"
    for prefix, group in GROUPS:
        if path.startswith(prefix):
            return group
    return "General"


def make_key(msgid: str, msgid_plural: str = "") -> str:
    return hashlib.sha1(f"{msgid}\x00{msgid_plural}".encode()).hexdigest()


def placeholder_set(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text or ""))


def clean_override(value: str, allow_html: bool) -> str:
    value = value.strip()
    if allow_html:
        return nh3.clean(value, tags={"strong", "b", "em", "i", "br", "span", "a"},
                         attributes={"span": {"class"}, "strong": {"class"}, "a": {"href"}})
    return strip_tags(value)


# --- sync from the .po catalogue ------------------------------------------------------
def po_path() -> Path:
    return Path(settings.BASE_DIR) / "locale" / "bn" / "LC_MESSAGES" / "django.po"


def sync_from_catalog(verbosity: int = 0) -> dict:
    import polib

    from .models import SiteText

    path = po_path()
    if not path.exists():
        return {"created": 0, "updated": 0, "obsolete": 0}
    po = polib.pofile(str(path))
    existing = {row.key: row for row in SiteText.objects.all()}
    seen, created, updated = set(), 0, 0
    for entry in po:
        if entry.obsolete or not entry.msgid:
            continue
        key = make_key(entry.msgid, entry.msgid_plural)
        seen.add(key)
        location = entry.occurrences[0][0] if entry.occurrences else ""
        default_bn = entry.msgstr_plural.get(0, "") if entry.msgid_plural else entry.msgstr
        values = {
            "msgid": entry.msgid,
            "msgid_plural": entry.msgid_plural or "",
            "group": group_for(location),
            "location": location[:255],
            "default_bn": default_bn,
            "placeholders": ", ".join(sorted(placeholder_set(entry.msgid + " " + (entry.msgid_plural or ""))))[:255],
            "is_obsolete": False,
        }
        row = existing.get(key)
        if row is None:
            SiteText.objects.create(key=key, **values)
            created += 1
        elif any(getattr(row, k) != v for k, v in values.items()):
            SiteText.objects.filter(pk=row.pk).update(**values)
            updated += 1
    stale = [k for k in existing if k not in seen]
    # Keep stale rows that carry an admin override (the text may come back); drop the rest.
    SiteText.objects.filter(key__in=stale, text_en="", text_en_plural="", text_bn="").delete()
    SiteText.objects.filter(key__in=stale).update(is_obsolete=True)
    bump_version()
    return {"created": created, "updated": updated, "obsolete": len(stale)}


# --- applying overrides ------------------------------------------------------------------
def bump_version() -> None:
    # A random token (not a counter) so a cleared cache can never repeat an old version.
    cache.set(VERSION_KEY, uuid.uuid4().hex, None)


def _current_version():
    version = cache.get(VERSION_KEY)
    if version is None:
        version = uuid.uuid4().hex
        cache.set(VERSION_KEY, version, None)
    return version


def ensure_applied() -> None:
    """Cheap per-request check; rebuilds overrides only when an admin changed something."""
    from django.utils.translation import trans_real

    version = _current_version()
    languages = [code for code, _name in settings.LANGUAGES]
    catalogs_same = all(
        _state["catalog_ids"].get(lang) == id(trans_real.translation(lang)) for lang in languages
    )
    if version == _state["version"] and catalogs_same:
        return
    try:
        _apply(languages)
    except Exception:  # never take the site down over a text override
        logger.exception("Could not apply site text overrides")
    _state["version"] = version


def _apply(languages):
    from django.utils.translation import trans_real

    from .models import SiteText

    rows = list(
        SiteText.objects.exclude(text_en="", text_en_plural="", text_bn="").values_list(
            "msgid", "msgid_plural", "text_en", "text_en_plural", "text_bn"
        )
    )
    for lang in languages:
        translation = trans_real.translation(lang)
        catalog = translation._catalog._catalogs[0]
        # Undo what we applied last time (only if it's still the same catalog object).
        if _state["catalog_ids"].get(lang) == id(translation):
            for key, original in _state["originals"].get(lang, {}).items():
                if original is _MISSING:
                    catalog.pop(key, None)
                else:
                    catalog[key] = original
        originals = {}

        def put(key, value):
            if key not in originals:
                originals[key] = catalog.get(key, _MISSING)
            catalog[key] = value

        for msgid, msgid_plural, text_en, text_en_plural, text_bn in rows:
            if lang == "en":
                singular, plural = text_en, text_en_plural or text_en
            else:
                singular = plural = text_bn
            if msgid_plural:
                if singular:
                    put((msgid, 0), singular)
                if plural:
                    put((msgid, 1), plural)
            elif singular:
                put(msgid, singular)
        _state["originals"][lang] = originals
        _state["catalog_ids"][lang] = id(translation)
