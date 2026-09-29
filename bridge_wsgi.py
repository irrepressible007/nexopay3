"""Entry point for the always-on app server (gunicorn, deploy/appserver.sh).

Used when the host's web server can't run Python apps itself: deploy/cgi_bridge.sh's
fast mode installs a tiny CGI forwarder that relays each request here over a private
Unix socket. A socket connection has no client address or TLS state, so the forwarder
passes along what the web server saw.
"""
import sys
from io import BytesIO
from urllib.parse import urlsplit

from passenger_wsgi import application as django_app


def application(environ, start_response):
    # Set only by the forwarder (it drops any copy sent by the visitor); the socket is
    # private to this account, so nothing else can reach this server.
    remote_addr = environ.pop("HTTP_X_NEXOPAY_REMOTE_ADDR", "")
    scheme = environ.pop("HTTP_X_NEXOPAY_SCHEME", "")
    if remote_addr:
        environ["REMOTE_ADDR"] = remote_addr
    if scheme in ("http", "https"):
        environ["wsgi.url_scheme"] = scheme
    return django_app(environ, start_response)


def warm_up(paths=("/", "/bn/")):
    """Render a few pages once, so URL routes, templates and translations are loaded."""
    from django.conf import settings

    host = urlsplit(settings.SITE_URL).hostname or "localhost"
    for path in paths:
        environ = {
            "REQUEST_METHOD": "GET", "PATH_INFO": path, "SCRIPT_NAME": "", "QUERY_STRING": "",
            "SERVER_NAME": host, "SERVER_PORT": "443", "SERVER_PROTOCOL": "HTTP/1.1",
            "HTTP_HOST": host, "HTTP_X_FORWARDED_PROTO": "https", "REMOTE_ADDR": "127.0.0.1",
            "wsgi.version": (1, 0), "wsgi.url_scheme": "https", "wsgi.input": BytesIO(),
            "wsgi.errors": sys.stderr, "wsgi.multithread": True, "wsgi.multiprocess": True,
            "wsgi.run_once": False,
        }
        try:
            result = django_app(environ, lambda status, headers, exc_info=None: None)
            for _ in result:
                pass
            if hasattr(result, "close"):
                result.close()
        except Exception:  # best effort: a failure here must not stop the server
            pass
