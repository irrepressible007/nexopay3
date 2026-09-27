from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("test-gateway/<str:tran_id>/", views.mock_gateway, name="mock_gateway"),
    path("<str:provider>/return/", views.payment_return, name="return"),
    path("<str:provider>/ipn/", views.payment_ipn, name="ipn"),
]
