"""
Addresses from Nexopay 2 (the Laravel site that used to run on nexopay.com.bd).

Bookmarks, old emails and search results still point at them; send people to the
matching page of this site instead of a "page not found".
"""
from django.http import HttpResponsePermanentRedirect
from django.shortcuts import resolve_url
from django.urls import re_path

from apps.events.models import Event


def _to(url_name):
    def view(request, *args, **kwargs):
        return HttpResponsePermanentRedirect(resolve_url(url_name))

    return view


def old_event(request, slug):
    event = Event.objects.public().filter(slug=slug).first()
    return HttpResponsePermanentRedirect(event.get_absolute_url() if event else resolve_url("events:catalog"))


urlpatterns = [
    re_path(r"^login/?$", _to("account_login")),
    re_path(r"^register/?$", _to("account_signup")),
    re_path(r"^forgot-password/?$", _to("account_reset_password")),
    re_path(r"^dashboard/?$", _to("accounts:tickets")),
    re_path(r"^profile/?$", _to("accounts:profile")),
    re_path(r"^event/(?P<slug>[-\w]+)/?$", old_event),
]
