from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("tickets/", views.my_tickets, name="tickets"),
    path("tickets/<str:code>/", views.ticket_detail, name="ticket"),
    path("tickets/<str:code>/pdf/", views.ticket_pdf, name="ticket_pdf"),
    path("orders/", views.orders, name="orders"),
    path("orders/<str:reference>/pdf/", views.order_pdf, name="order_pdf"),
    path("profile/", views.profile, name="profile"),
]
