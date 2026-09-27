from django.urls import path

from . import scan_views

app_name = "scan"

urlpatterns = [
    path("", scan_views.home, name="home"),
    path("<slug:slug>/", scan_views.event, name="event"),
    path("<slug:slug>/redeem/", scan_views.redeem, name="redeem"),
]
