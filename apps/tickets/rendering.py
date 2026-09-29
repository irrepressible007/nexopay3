"""
Renderers for the one canonical Ticket record: inline QR (web), PNG QR (share
image) and PDF (email attachment / re-download). Nothing is stored — every
channel renders from the same signed token on demand.
"""
import io
from functools import lru_cache
from pathlib import Path

import segno
from django.conf import settings
from django.utils import timezone, translation
from django.utils.formats import date_format
from fpdf import FPDF
from fpdf.pattern import LinearGradient

FONT_DIR = Path(settings.BASE_DIR) / "assets" / "fonts"


def qr_svg(data: str, scale: int = 6) -> str:
    return segno.make(data, error="m").svg_inline(scale=scale, border=2, dark="#0B0A10", light="#FFFFFF")


def qr_png(data: str, scale: int = 10) -> bytes:
    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="png", scale=scale, border=2)
    return buf.getvalue()


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _header_logo():
    """Raster logo for the coloured PDF header: the admin's upload, else the bundled white logo."""
    from apps.cms.models import SiteSettings

    site = SiteSettings.load()
    if site.logo_on_color and site.logo_on_color.name.lower().endswith((".png", ".jpg", ".jpeg")):
        try:
            with site.logo_on_color.open("rb") as fh:
                return io.BytesIO(fh.read())
        except Exception:
            pass
    return str(Path(settings.BASE_DIR) / "static" / "img" / "logo-white.png")


@lru_cache(maxsize=1)
def _font_paths():
    return FONT_DIR / "HindSiliguri-Regular.ttf", FONT_DIR / "HindSiliguri-Bold.ttf"


class _TicketPDF(FPDF):
    def __init__(self):
        # A tall, phone-shaped page reads well both printed and on screen.
        super().__init__(orientation="P", unit="mm", format=(105, 190))
        regular, bold = _font_paths()
        self.add_font("Hind", "", str(regular))
        self.add_font("Hind", "B", str(bold))
        self.set_text_shaping(True)  # correct Bangla conjuncts via HarfBuzz
        self.set_auto_page_break(False)
        self.set_margins(8, 8, 8)


def render_tickets_pdf(tickets, language: str = "en") -> bytes:
    """Render one page per ticket and return the PDF bytes."""
    from apps.cms.models import SiteSettings

    from apps.cms.sitetext import ensure_applied

    ensure_applied()
    site = SiteSettings.load()
    logo = _header_logo()
    primary = _hex_to_rgb(site.primary_color)
    secondary = _hex_to_rgb(site.secondary_color)
    pdf = _TicketPDF()

    with translation.override(language):
        for ticket in tickets:
            event = ticket.event
            pdf.add_page()
            w = pdf.w

            # Header band in the brand gradient.
            with pdf.use_pattern(LinearGradient(0, 0, w, 34, [primary, secondary])):
                pdf.rect(0, 0, w, 34, "F")
            pdf.set_text_color(*_hex_to_rgb(site.on_brand_color))
            try:
                if hasattr(logo, "seek"):
                    logo.seek(0)
                pdf.image(logo, x=8, y=6, h=6.5)
            except Exception:
                pdf.set_font("Hind", "B", 11)
                pdf.set_xy(8, 7)
                pdf.cell(0, 5, site.site_name)
            pdf.set_font("Hind", "B", 15)
            pdf.set_xy(8, 14)
            pdf.multi_cell(w - 16, 7, event.title, align="L")

            pdf.set_text_color(20, 20, 28)
            y = 40
            local_start = timezone.localtime(event.starts_at)
            rows = [
                (translation.gettext("Date & time"), date_format(local_start, "l, j F Y · g:i A")),
                (translation.gettext("Venue"), event.venue_name or translation.gettext("Online")),
                (translation.gettext("Ticket"), ticket.ticket_type.name),
                (translation.gettext("Name"), ticket.holder_name or ticket.owner.get_full_name()),
            ]
            for label, value in rows:
                pdf.set_xy(8, y)
                pdf.set_font("Hind", "", 8)
                pdf.set_text_color(110, 110, 125)
                pdf.cell(0, 4, label.upper())
                pdf.set_xy(8, y + 4)
                pdf.set_font("Hind", "B", 11)
                pdf.set_text_color(20, 20, 28)
                pdf.multi_cell(w - 16, 5.5, value, align="L")
                y = pdf.get_y() + 2.5

            # Perforation line.
            pdf.set_draw_color(200, 200, 210)
            pdf.set_dash_pattern(dash=1.5, gap=1.5)
            pdf.line(6, y + 1, w - 6, y + 1)
            pdf.set_dash_pattern()

            qr_size = 62
            qr_y = y + 6
            pdf.image(io.BytesIO(qr_png(ticket.token)), x=(w - qr_size) / 2, y=qr_y, w=qr_size, h=qr_size)
            pdf.set_xy(8, qr_y + qr_size + 2)
            pdf.set_font("Hind", "B", 13)
            pdf.cell(w - 16, 6, ticket.code, align="C")
            pdf.set_xy(8, qr_y + qr_size + 9)
            pdf.set_font("Hind", "", 8)
            pdf.set_text_color(110, 110, 125)
            pdf.multi_cell(
                w - 16,
                4,
                translation.gettext(
                    "Show this QR code at the entrance. It can be scanned only once — do not share it."
                ),
                align="C",
            )
            pdf.set_xy(8, pdf.h - 12)
            pdf.cell(w - 16, 4, f"{translation.gettext('Order')} {ticket.order.reference}", align="C")

    return bytes(pdf.output())
