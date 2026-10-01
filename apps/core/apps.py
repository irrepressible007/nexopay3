from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"

    def ready(self):
        import warnings

        from . import checks  # noqa: F401  (registers the deploy checks)

        from PIL import Image

        # Last line of defence behind core.security.check_image_size: Pillow refuses to even
        # open anything over 2 × this, and the warning in between becomes an error.
        Image.MAX_IMAGE_PIXELS = 60_000_000
        warnings.simplefilter("error", Image.DecompressionBombWarning)
