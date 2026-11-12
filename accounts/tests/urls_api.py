"""Test urlconf: accounts mounted under /api/ (the common REST layout)."""
from django.urls import include, path

urlpatterns = [path("api/", include("accounts.urls"))]
