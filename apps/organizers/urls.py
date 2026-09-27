from django.urls import path

from . import views

app_name = "organizers"

urlpatterns = [
    path("apply/", views.apply, name="apply"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("events/new/", views.event_edit, name="event_new"),
    path("events/<slug:slug>/", views.event_detail, name="event"),
    path("events/<slug:slug>/edit/", views.event_edit, name="event_edit"),
    path("events/<slug:slug>/attendees.csv", views.attendees_csv, name="attendees_csv"),
    path("events/<slug:slug>/scanners/", views.scanner_add, name="scanner_add"),
    path("events/<slug:slug>/scanners/<int:pk>/remove/", views.scanner_remove, name="scanner_remove"),
    path("events/<slug:slug>/orders/<str:reference>/refund/", views.order_refund, name="order_refund"),
]
