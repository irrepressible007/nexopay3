"""Entry point for the always-on app server (gunicorn, deploy/appserver.sh).

Used when the host's web server can't run Python apps itself: deploy/cgi_bridge.sh's
fast mode installs a tiny CGI forwarder that relays each request here over a private
Unix socket. A socket connection has no client address or TLS state, so the forwarder
passes along what the web server saw.
"""
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
