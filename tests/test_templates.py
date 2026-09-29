"""Template hygiene checks."""
import re
from pathlib import Path

from django.conf import settings


def test_template_comments_close_on_the_same_line():
    """Django's {# #} comments are single-line; a multi-line one is printed onto the page as text."""
    root = Path(settings.BASE_DIR) / "templates"
    unclosed = [
        f"{path.relative_to(root)}:{number}"
        for path in root.rglob("*.html")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\{#(?!.*#\})", line)
    ]
    assert not unclosed, f"use {{% comment %}} for multi-line comments: {unclosed}"
