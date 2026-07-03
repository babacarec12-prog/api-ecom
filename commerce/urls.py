from django.urls import path

from .views import commerce, health

urlpatterns = [
    path("health/", health, name="health"),
    path("commerce/", commerce, name="commerce"),
]
