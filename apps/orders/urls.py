from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("checkout/<slug:slug>/", views.checkout, name="checkout"),
    path("orders/<str:reference>/", views.order_detail, name="detail"),
    path("orders/<str:reference>/pay/", views.order_pay, name="pay"),
]
