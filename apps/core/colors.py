"""Colour contrast (WCAG 2), so admin-chosen brand colours always stay readable."""

LIGHT_TEXT = "#FFFFFF"
DARK_TEXT = "#0B0917"


def luminance(hex_color: str) -> float:
    """Relative luminance of a #RRGGBB colour (0 = black, 1 = white)."""
    value = hex_color.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    """Contrast ratio between two colours, from 1 (none) to 21 (black on white)."""
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def readable_text_on(*backgrounds: str) -> str:
    """White or dark text, whichever reads better on every one of the given backgrounds.

    White is preferred whenever it meets WCAG AA (4.5:1) on all of them.
    """
    worst_light = min(contrast(LIGHT_TEXT, bg) for bg in backgrounds)
    if worst_light >= 4.5:
        return LIGHT_TEXT
    worst_dark = min(contrast(DARK_TEXT, bg) for bg in backgrounds)
    return LIGHT_TEXT if worst_light >= worst_dark else DARK_TEXT
