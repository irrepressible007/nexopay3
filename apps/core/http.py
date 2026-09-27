from functools import wraps

from django.utils.cache import patch_cache_control


def public_cache(s_maxage: int = 60):
    """
    Mark a view's HTML as identical for every visitor so Cloudflare can serve it
    from the edge. Templates check `request.public_cache` and load per-user bits
    (account menu, flash messages, live ticket panel) as small HTMX fragments.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            request.public_cache = True
            response = view(request, *args, **kwargs)
            if response.status_code == 200 and not response.cookies:
                patch_cache_control(response, public=True, max_age=0, s_maxage=s_maxage)
            return response

        return wrapper

    return decorator


def private_no_store(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        patch_cache_control(response, private=True, no_store=True)
        return response

    return wrapper


def is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"
