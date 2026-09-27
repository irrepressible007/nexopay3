"""WebP renditions for uploaded banners, generated once at upload time."""
import io
import logging
from pathlib import PurePosixPath

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

RENDITION_WIDTHS = (480, 960, 1600)


def build_renditions(field_file, widths=RENDITION_WIDTHS) -> dict[str, str]:
    """
    Create WebP copies of an image at the given widths next to the original.

    Returns {"480": "<storage name>", ...}. Widths larger than the source are
    skipped so we never upscale.
    """
    if not field_file:
        return {}
    renditions: dict[str, str] = {}
    try:
        field_file.open("rb")
        with Image.open(field_file) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            base = PurePosixPath(field_file.name)
            stem = str(base.with_suffix(""))
            for width in widths:
                if width > img.width and renditions:
                    continue
                target_w = min(width, img.width)
                target_h = round(img.height * target_w / img.width)
                copy = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                copy.save(buf, "WEBP", quality=80, method=5)
                name = f"{stem}__{width}.webp"
                if default_storage.exists(name):
                    default_storage.delete(name)
                renditions[str(width)] = default_storage.save(name, ContentFile(buf.getvalue()))
    except Exception:  # a bad upload must not break saving the record
        logger.exception("Could not build renditions for %s", field_file.name)
        return {}
    finally:
        try:
            field_file.close()
        except Exception:
            pass
    return renditions


def srcset(renditions: dict[str, str]) -> str:
    return ", ".join(f"{default_storage.url(name)} {w}w" for w, name in sorted(renditions.items(), key=lambda i: int(i[0])))
