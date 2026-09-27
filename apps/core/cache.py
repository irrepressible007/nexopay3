"""Tiny helpers for version-keyed fragment caching (no Redis needed)."""
from django.core.cache import cache

CONTENT_VERSION_KEY = "content:version"


def content_version() -> int:
    version = cache.get(CONTENT_VERSION_KEY)
    if version is None:
        version = 1
        cache.set(CONTENT_VERSION_KEY, version, None)
    return version


def bump_content_version() -> None:
    """Invalidate every cached public fragment at once."""
    try:
        cache.incr(CONTENT_VERSION_KEY)
    except ValueError:
        cache.set(CONTENT_VERSION_KEY, 2, None)


def versioned_key(name: str, *parts) -> str:
    suffix = ":".join(str(p) for p in parts)
    return f"frag:{content_version()}:{name}:{suffix}"
