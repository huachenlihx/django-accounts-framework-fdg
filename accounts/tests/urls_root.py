"""Test urlconf: accounts mounted at the site root."""
from django.urls import include, path

urlpatterns = [path("", include("accounts.urls"))]
