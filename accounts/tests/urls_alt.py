"""Test urlconf: accounts mounted somewhere unusual, to prove nothing hardcodes /api/auth/."""
from django.urls import include, path

urlpatterns = [path("v2/members/", include("accounts.urls"))]
