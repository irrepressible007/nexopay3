from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.catalog, name="catalog"),
    path("<slug:slug>/", views.detail, name="detail"),
    path("<slug:slug>/_tickets/", views.ticket_panel, name="ticket_panel"),
    path("<slug:slug>/calendar.ics", views.calendar_ics, name="ics"),
]
