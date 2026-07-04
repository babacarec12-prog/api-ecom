from django.urls import path

from .views import commerce, health, paytech_cancel, paytech_ipn, paytech_success

urlpatterns = [
    path("health/", health, name="health"),
    path("commerce/", commerce, name="commerce"),
    path("paytech/ipn/", paytech_ipn, name="paytech-ipn"),
    path("paytech/success/", paytech_success, name="paytech-success"),
    path("paytech/cancel/", paytech_cancel, name="paytech-cancel"),
]
