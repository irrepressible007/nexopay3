from django.urls import path

from . import views

app_name = "support"

urlpatterns = [
    path("contact/", views.contact, name="contact"),
]
