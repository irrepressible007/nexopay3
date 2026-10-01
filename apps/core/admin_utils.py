"""Shared admin tools: CSV export of any list, and small display helpers."""
import csv
import re

from django.contrib.admin.utils import label_for_field, lookup_field
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import format_html, strip_tags
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _
from unfold.decorators import action

_SPACES = re.compile(r"\s+")


def _plain(value) -> str:
    """A list cell as plain text (labels and links lose their HTML)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):  # header columns: [title, subtitle, ...]
        value = " - ".join(str(v) for v in value[:2] if v)
    return _SPACES.sub(" ", strip_tags(str(value))).strip()


def export_rows(modeladmin, request, queryset, fields=None):
    """Header row + one row per object, using the admin's export_fields or its list columns."""
    fields = list(fields or getattr(modeladmin, "export_fields", None) or modeladmin.get_list_display(request))
    fields = [f for f in fields if f != "action_checkbox"]
    yield [capfirst(_plain(label_for_field(f, modeladmin.model, modeladmin))) for f in fields]
    for obj in queryset:
        row = []
        for f in fields:
            try:
                _field, _attr, value = lookup_field(f, obj, modeladmin)
            except Exception:  # a column that can't be read for this row stays empty
                value = ""
            row.append(_plain(value))
        yield row


@action(description=_("Export selected to CSV (opens in Excel)"))
def export_csv(modeladmin, request, queryset):
    name = modeladmin.model._meta.verbose_name_plural.replace(" ", "-")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="nexopay-{name}-{timezone.localdate():%Y-%m-%d}.csv"'
    response.write("﻿")  # BOM: Excel then reads Bangla correctly
    writer = csv.writer(response)
    for row in export_rows(modeladmin, request, queryset):
        writer.writerow(row)
    return response


def progress_bar(done: int, total: int):
    """A small bar with "done / total" beside it, for list columns."""
    pct = round(done / total * 100) if total else 0
    return format_html('<span style="display:flex;align-items:center;gap:.6rem"><span class="nx-bar"><span style="width:{}%"></span></span>'
                       '<span style="white-space:nowrap">{} / {}</span></span>', pct, done, total)
