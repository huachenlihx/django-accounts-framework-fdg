"""Rate limiting of the public activation-resend endpoint."""
from unittest.mock import patch

from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

User = get_user_model()


@override_settings(
    ROOT_URLCONF="accounts.tests.urls_api",
    ACCOUNTS_FRAMEWORK={
        "REQUIRE_EMAIL_ACTIVATION": True,
        "ACTIVATION_RESEND_RATE_PER_IP": "5/hour",
        "ACTIVATION_RESEND_RATE_PER_EMAIL": "3/hour",
    },
)
class ResendActivationThrottleTests(TestCase):
    def setUp(self):
        cache.clear()  # throttle counters live in the cache, which outlives each test
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.url = reverse("accounts-activate-resend")
        self.user = User.objects.create_user(
            "pending@example.com", "Strong-Pass-12345", is_active=True,
            is_activated=False, activation_token=User.generate_activation_token(),
            activation_token_created_at=timezone.now(),
        )

    def post(self, email, ip="10.0.0.1"):
        return self.client.post(self.url, {"email": email}, format="json", REMOTE_ADDR=ip)

    @patch("accounts.views.send_activation_email")
    def test_per_ip_limit_blocks_after_five_requests(self, send):
        for i in range(5):
            self.assertEqual(self.post(f"user{i}@example.com").status_code, 200)
        blocked = self.post("another@example.com")
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.data["detail"], "Too many activation email requests. Please try again later.")
        self.assertIn("Retry-After", blocked)
        # A different client IP is not affected.
        self.assertEqual(self.post("another@example.com", ip="10.0.0.2").status_code, 200)

    @patch("accounts.views.send_activation_email")
    def test_per_email_limit_applies_across_ips_and_stops_sending(self, send):
        for n in range(3):
            self.assertEqual(self.post(self.user.email, ip=f"10.0.1.{n}").status_code, 200)
        self.assertEqual(send.call_count, 3)
        blocked = self.post(self.user.email, ip="10.0.1.99")
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(send.call_count, 3)  # no further email sent
        # Email matching ignores case and surrounding spaces.
        self.assertEqual(self.post("  PENDING@Example.com ", ip="10.0.1.100").status_code, 429)
        # Other addresses are unaffected.
        self.assertEqual(self.post("someone-else@example.com", ip="10.0.1.101").status_code, 200)

    @patch("accounts.views.send_activation_email")
    def test_limit_does_not_reveal_whether_an_account_exists(self, send):
        for email in (self.user.email, "ghost@example.com"):
            statuses = [self.post(email, ip=f"10.0.2.{n}").status_code for n in range(4)]
            self.assertEqual(statuses, [200, 200, 200, 429], email)

    @patch("accounts.views.send_activation_email")
    def test_malformed_email_values_still_hit_ip_limit_without_errors(self, send):
        statuses = []
        for value in (None, 123, {}, [], "", None):
            statuses.append(self.post(value).status_code)
        self.assertEqual(statuses, [200] * 5 + [429])

    @override_settings(ACCOUNTS_FRAMEWORK={
        "REQUIRE_EMAIL_ACTIVATION": True,
        "ACTIVATION_RESEND_RATE_PER_IP": "1/hour",
        "ACTIVATION_RESEND_RATE_PER_EMAIL": None,
    })
    @patch("accounts.views.send_activation_email")
    def test_rates_are_configurable_and_can_be_disabled(self, send):
        self.assertEqual(self.post("a@example.com").status_code, 200)
        self.assertEqual(self.post("a@example.com").status_code, 429)  # per-IP now 1/hour
        for n in range(5):  # per-email disabled: different IPs never hit an email limit
            self.assertEqual(self.post("a@example.com", ip=f"10.0.3.{n}").status_code, 200)

    @patch("accounts.views.send_activation_email")
    def test_login_and_activate_endpoints_are_not_throttled(self, send):
        for _ in range(8):
            r = self.client.post(reverse("accounts-login"), {"email": "x@example.com", "password": "bad"},
                                 format="json", REMOTE_ADDR="10.0.4.1")
            self.assertEqual(r.status_code, 401)
            r = self.client.get(reverse("accounts-activate"), {"token": "nope"}, REMOTE_ADDR="10.0.4.1")
            self.assertEqual(r.status_code, 400)
