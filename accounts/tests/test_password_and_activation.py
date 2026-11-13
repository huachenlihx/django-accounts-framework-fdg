"""Password-validator enforcement and activation-link expiry."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import PasswordResetToken

User = get_user_model()
GOOD = "Tr1cky-Horse-Battery-7"


VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


@override_settings(ROOT_URLCONF="accounts.tests.urls_api", AUTH_PASSWORD_VALIDATORS=VALIDATORS)
class PasswordValidatorTests(TestCase):
    """AUTH_PASSWORD_VALIDATORS must apply to every endpoint that sets a password."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("pat@example.com", "Initial-Pass-12345", first_name="Pat", is_activated=True)

    def test_registration_rejects_common_numeric_and_similar_passwords(self):
        for weak in ("password123", "1234567890", "new-example-com"):
            r = self.client.post(reverse("accounts-register"), {"email": "new@example.com", "password": weak,
                                 "confirm_password": weak, "first_name": "New"}, format="json")
            self.assertEqual(r.status_code, 400, weak)
            self.assertIn("password", r.json())
        self.assertFalse(User.objects.filter(email="new@example.com").exists())

    def test_registration_accepts_a_strong_password(self):
        r = self.client.post(reverse("accounts-register"), {"email": "new@example.com", "password": GOOD,
                             "confirm_password": GOOD}, format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def test_change_password_rejects_weak_and_accepts_strong(self):
        self.client.force_authenticate(self.user)
        url = reverse("accounts-change-password")
        weak = self.client.post(url, {"current_password": "Initial-Pass-12345", "new_password": "password123",
                                      "confirm_password": "password123"}, format="json")
        self.assertEqual(weak.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Initial-Pass-12345"))
        ok = self.client.post(url, {"current_password": "Initial-Pass-12345", "new_password": GOOD,
                                    "confirm_password": GOOD}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)

    def test_password_reset_rejects_weak_password_and_keeps_token_usable(self):
        token = PasswordResetToken.create_for_user(self.user)
        r = self.client.post(reverse("accounts-password-reset-confirm"), {"token": token.token,
                             "new_password": "password123", "confirm_password": "password123"}, format="json")
        self.assertEqual(r.status_code, 400)
        token.refresh_from_db()
        self.assertFalse(token.used)
        r = self.client.post(reverse("accounts-password-reset-confirm"), {"token": token.token,
                             "new_password": GOOD, "confirm_password": GOOD}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_admin_set_password_applies_validators(self):
        admin = User.objects.create_superuser("root@example.com", GOOD)
        self.client.force_authenticate(admin)
        url = reverse("accounts-admin-set-password")
        weak = self.client.post(url, {"user_public_id": str(self.user.public_id), "new_password": "pat@example.com"}, format="json")
        self.assertEqual(weak.status_code, 400)
        ok = self.client.post(url, {"user_public_id": str(self.user.public_id), "new_password": GOOD}, format="json")
        self.assertEqual(ok.status_code, 200, ok.content)


@override_settings(ROOT_URLCONF="accounts.tests.urls_api",
                   ACCOUNTS_FRAMEWORK={"REQUIRE_EMAIL_ACTIVATION": True, "ACTIVATION_TOKEN_EXPIRY_HOURS": 24})
class ActivationExpiryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.post(reverse("accounts-register"), {"email": "ann@example.com", "password": GOOD,
                         "confirm_password": GOOD}, format="json")
        self.user = User.objects.get(email="ann@example.com")

    def activate(self, token=None):
        return self.client.get(reverse("accounts-activate"), {"token": token or self.user.activation_token})

    def test_registration_stamps_the_token_issue_time(self):
        self.assertIsNotNone(self.user.activation_token_created_at)
        self.assertTrue(self.user.activation_token_is_valid)

    def test_fresh_link_activates_the_account(self):
        self.assertEqual(self.activate().status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_activated)
        self.assertEqual(self.user.activation_token, "")

    def test_expired_link_is_rejected_and_account_stays_inactive(self):
        User.objects.filter(pk=self.user.pk).update(activation_token_created_at=timezone.now() - timedelta(hours=25))
        r = self.activate()
        self.assertEqual(r.status_code, 400)
        self.assertIn("expired", r.json()["error"].lower())
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_activated)

    def test_link_without_a_recorded_issue_time_is_not_accepted(self):
        User.objects.filter(pk=self.user.pk).update(activation_token_created_at=None)
        self.assertEqual(self.activate().status_code, 400)

    def test_lifetime_follows_the_setting(self):
        User.objects.filter(pk=self.user.pk).update(activation_token_created_at=timezone.now() - timedelta(hours=25))
        with override_settings(ACCOUNTS_FRAMEWORK={"ACTIVATION_TOKEN_EXPIRY_HOURS": 48}):
            self.assertEqual(self.activate().status_code, 200)

    def test_resend_issues_a_new_token_with_a_fresh_lifetime(self):
        old = self.user.activation_token
        User.objects.filter(pk=self.user.pk).update(activation_token_created_at=timezone.now() - timedelta(hours=30))
        mail.outbox.clear()
        self.client.post(reverse("accounts-activate-resend"), {"email": "ann@example.com"}, format="json")
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.activation_token, old)
        self.assertTrue(self.user.activation_token_is_valid)
        self.assertEqual(self.activate(old).status_code, 400)
        self.assertEqual(self.activate().status_code, 200)


@override_settings(ROOT_URLCONF="accounts.tests.urls_api", AUTH_PASSWORD_VALIDATORS=[])
class NoValidatorsConfiguredTests(TestCase):
    """The app adds no password rules of its own beyond the 8-character minimum."""

    def test_projects_without_validators_still_get_the_minimum_length(self):
        client = APIClient()
        r = client.post(reverse("accounts-register"), {"email": "a@example.com", "password": "short",
                        "confirm_password": "short"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = client.post(reverse("accounts-register"), {"email": "a@example.com", "password": "password123",
                        "confirm_password": "password123"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
