from django.urls import path

from . import views

app_name = "cms"

urlpatterns = [
    path("", views.home, name="home"),
    path("faq/", views.faq, name="faq"),
    path("p/<slug:slug>/", views.page, name="page"),
    path("_/nav/", views.nav_fragment, name="nav"),
]
