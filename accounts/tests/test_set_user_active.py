"""Strict JSON boolean validation for privileged account activation changes."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient


User = get_user_model()


class SetUserActiveBooleanTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            email="admin-activation@example.com", password="test-password-123"
        )
        self.target = User.objects.create_user(
            email="target-activation@example.com", password="test-password-123"
        )
        self.client.force_authenticate(user=self.admin)
        self.url = "/api/auth/set-active/"

    def send(self, value):
        return self.client.post(
            self.url,
            data={"user_public_id": str(self.target.public_id), "is_active": value},
            format="json",
        )

    def test_true_and_false_boolean_values_update_status(self):
        response = self.send(False)
        self.assertEqual(response.status_code, 200, response.data)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)

        response = self.send(True)
        self.assertEqual(response.status_code, 200, response.data)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)
        self.assertTrue(self.target.must_change_password)

    def test_invalid_values_do_not_change_active_status(self):
        invalid_values = ("false", "true", "0", "1", 0, 1, [], {}, "")
        for value in invalid_values:
            with self.subTest(value=value):
                self.target.is_active = True
                self.target.must_change_password = False
                self.target.save(update_fields=["is_active", "must_change_password"])
                response = self.send(value)
                self.assertEqual(response.status_code, 400, response.data)
                self.target.refresh_from_db()
                self.assertTrue(self.target.is_active)
                self.assertFalse(self.target.must_change_password)

    def test_null_is_rejected_and_does_not_modify_account(self):
        self.target.is_active = False
        self.target.save(update_fields=["is_active"])
        response = self.send(None)
        self.assertEqual(response.status_code, 400, response.data)
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)
