"""
Apply locale/bn_translations.py to the Bangla .po file and compile the .mo —
works without GNU gettext (useful on Windows and on hosts without msgfmt).

    python manage.py fill_translations
"""
import importlib.util
from pathlib import Path

import polib
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Fill Bangla translations into django.po and compile django.mo."

    def handle(self, *args, **options):
        base = Path(settings.BASE_DIR) / "locale"
        spec = importlib.util.spec_from_file_location("bn_translations", base / "bn_translations.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        po_path = base / "bn" / "LC_MESSAGES" / "django.po"
        po = polib.pofile(str(po_path))
        po.metadata["Language"] = "bn"
        po.metadata["Plural-Forms"] = "nplurals=2; plural=(n != 1);"
        missing = []
        for entry in po:
            if entry.msgid_plural:
                text = module.PLURALS.get(entry.msgid)
                if text:
                    entry.msgstr_plural = {0: text, 1: text}
                else:
                    missing.append(entry.msgid)
            elif entry.msgid in module.TR:
                entry.msgstr = module.TR[entry.msgid]
            else:
                missing.append(entry.msgid)
            if "fuzzy" in entry.flags:
                entry.flags.remove("fuzzy")
        po.save(str(po_path))
        po.save_as_mofile(str(po_path.with_suffix(".mo")))
        self.stdout.write(self.style.SUCCESS(f"Translated {po.percent_translated()}% — compiled django.mo"))
        for msgid in missing:
            self.stdout.write(f"  missing: {msgid!r}")
