from .sitetext import ensure_applied


class SiteTextMiddleware:
    """Make sure this worker process shows the latest admin-edited interface texts."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ensure_applied()
        return self.get_response(request)
