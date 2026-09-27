from django.urls import path

from . import views

app_name = "tickets"

urlpatterns = [
    path("t/<str:token>/", views.share, name="share"),
    path("t/<str:token>/qr.png", views.share_qr_png, name="share_qr"),
]
