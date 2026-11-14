"""Regression coverage for backend activation-recovery responses and resend API.

Error messages remain backward-compatible with existing frontend clients; stable
codes enable future clients to avoid brittle English-message matching.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

User = get_user_model()


@override_settings(
    ROOT_URLCONF="accounts.tests.urls_api",
    ACCOUNTS_FRAMEWORK={"REQUIRE_EMAIL_ACTIVATION": True, "ACTIVATION_TOKEN_EXPIRY_HOURS": 1},
)
class AccountActivationRecoveryTests(TestCase):
    def setUp(self):
        cache.clear()  # resend throttle counters live in the cache
        self.addCleanup(cache.clear)
        self.client = APIClient()
        self.user = User.objects.create_user(
            "pending@example.com", "Strong-Pass-12345", is_active=True,
            is_activated=False, activation_token=User.generate_activation_token(),
            activation_token_created_at=timezone.now(),
        )

    def test_inactive_account_login_has_stable_code_and_existing_message(self):
        response = self.client.post(reverse("accounts-login"), {
            "email": self.user.email, "password": "Strong-Pass-12345",
        }, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "account_not_activated")
        self.assertEqual(response.data["error"], "Please activate your account via the link sent to your email.")

    def test_wrong_password_does_not_reveal_activation_status(self):
        response = self.client.post(reverse("accounts-login"), {
            "email": self.user.email, "password": "incorrect",
        }, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("code", response.data)

    def test_expired_token_has_stable_code_and_existing_message(self):
        User.objects.filter(pk=self.user.pk).update(
            activation_token_created_at=timezone.now() - timedelta(hours=2)
        )
        response = self.client.get(reverse("accounts-activate"), {
            "token": self.user.activation_token,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "activation_link_expired")
        self.assertEqual(response.data["error"], "This activation link has expired. Please request a new one.")

    @patch("accounts.views.send_activation_email")
    def test_resend_renews_token_and_does_not_reveal_account_existence(self, send):
        original = self.user.activation_token
        url = reverse("accounts-activate-resend")
        response = self.client.post(url, {"email": self.user.email}, format="json")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertNotEqual(original, self.user.activation_token)
        self.assertTrue(self.user.activation_token_is_valid)
        send.assert_called_once()
        unknown = self.client.post(url, {"email": "missing@example.com"}, format="json")
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(response.data, unknown.data)
        send.assert_called_once()

    @patch("accounts.views.send_activation_email")
    def test_resend_for_activated_account_is_noop(self, send):
        self.user.is_activated = True
        self.user.save(update_fields=["is_activated"])
        response = self.client.post(reverse("accounts-activate-resend"), {
            "email": self.user.email,
        }, format="json")
        self.assertEqual(response.status_code, 200)
        send.assert_not_called()

    def test_malformed_email_inputs_do_not_raise_server_errors(self):
        for value in (None, 123, {}, []):
            with self.subTest(value=value):
                response = self.client.post(reverse("accounts-activate-resend"), {
                    "email": value,
                }, format="json")
                self.assertEqual(response.status_code, 200)
                response = self.client.post(reverse("accounts-login"), {
                    "email": value, "password": "examplepass",
                }, format="json")
                self.assertEqual(response.status_code, 400)

    @patch("accounts.email_utils.send_template_email")
    def test_one_hour_expiry_uses_singular_email_wording(self, send):
        from accounts.email_utils import send_activation_email
        send_activation_email(self.user, self.user.activation_token)
        self.assertEqual(send.call_args.kwargs["context"]["expiry_duration"], "1 hour")
