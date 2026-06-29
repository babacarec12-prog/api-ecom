from django.urls import path

from .views import commerce

urlpatterns = [
    path("commerce/", commerce, name="commerce"),
]
