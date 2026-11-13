"""Reusable-account authorization, validation, and token regression coverage."""
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from accounts import checks
from accounts.admin import UserAdmin
from accounts.models import PasswordResetToken
from accounts.role_setup import DEFAULT_ROLE_PRESETS, get_role_presets
from accounts.serializers import UserCreateSerializer

User = get_user_model()
AUTH = "django.contrib.auth.middleware.AuthenticationMiddleware"
FORCE = checks.MIDDLEWARE_PATH


class ReusableSettingsTests(SimpleTestCase):
    @override_settings(ACCOUNTS_FRAMEWORK={})
    def test_missing_role_presets_uses_default(self):
        self.assertEqual(get_role_presets(), list(DEFAULT_ROLE_PRESETS))

    @override_settings(ACCOUNTS_FRAMEWORK={"ROLE_PRESETS": []})
    def test_explicit_empty_role_presets_disables_default(self):
        self.assertEqual(get_role_presets(), [])

    def test_malformed_settings_return_checks_not_exceptions(self):
        cases = (
            ("ACCOUNTS_FRAMEWORK", {"SUPPORTED_LOCALES": None}, "accounts.E005"),
            ("ACCOUNTS_FRAMEWORK", {"SUPPORTED_LOCALES": 7}, "accounts.E005"),
            ("ACCOUNTS_FRAMEWORK", {"MANAGER_ASSIGNABLE_ROLES": None}, "accounts.E003"),
            ("ACCOUNTS_FRAMEWORK", {"ROLE_PRESETS": "bad"}, "accounts.E006"),
            ("ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES", None, "accounts.E002"),
            ("ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES", 9, "accounts.E002"),
        )
        from django.test import override_settings
        for key, value, expected in cases:
            with self.subTest(key=key, value=value):
                with override_settings(**{key: value, "MIDDLEWARE": [AUTH, FORCE]}):
                    self.assertIn(expected, [x.id for x in checks.check_accounts_configuration(None)])


@override_settings(
    ROOT_URLCONF="accounts.tests.urls_api",
    ACCOUNTS_FRAMEWORK={"MANAGER_ASSIGNABLE_ROLES": ["Customer"]},
)
class DelegatedAdminAndRolesTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user("manager@example.com", "Strong-Pass-789", is_staff=True)
        permission = Permission.objects.get(content_type__app_label="accounts", codename="manage_users")
        self.manager.user_permissions.add(permission)
        self.customer_role = Group.objects.create(name="Customer")
        self.privileged_role = Group.objects.create(name="Power User")
        self.target = User.objects.create_user("target@example.com", "Strong-Pass-789")
        self.staff = User.objects.create_user("staff@example.com", "Strong-Pass-789", is_staff=True)
        self.privileged = User.objects.create_user("privileged@example.com", "Strong-Pass-789")
        self.privileged.groups.add(self.privileged_role)
        self.admin = UserAdmin(User, admin.site)
        self.request = RequestFactory().get("/admin/accounts/user/")
        self.request.user = self.manager

    def test_non_superuser_admin_groups_are_allowlisted(self):
        field = self.admin.formfield_for_manytomany(User._meta.get_field("groups"), self.request)
        self.assertEqual(list(field.queryset.values_list("name", flat=True)), ["Customer"])

    def test_non_superuser_admin_cannot_change_privileged_accounts(self):
        self.assertTrue(self.admin.has_change_permission(self.request, self.target))
        self.assertFalse(self.admin.has_change_permission(self.request, self.staff))
        self.assertFalse(self.admin.has_change_permission(self.request, self.privileged))
        ids = set(self.admin.get_queryset(self.request).values_list("pk", flat=True))
        self.assertIn(self.target.pk, ids)
        self.assertNotIn(self.staff.pk, ids)
        self.assertNotIn(self.privileged.pk, ids)
        self.assertIn("is_staff", self.admin.get_readonly_fields(self.request, self.target))

    def test_malformed_role_payloads_are_400(self):
        client = APIClient()
        client.force_authenticate(self.manager)
        url = reverse("accounts-assign-role")
        for roles in (7, True, {"x": "Customer"}, [7], [None]):
            with self.subTest(roles=roles):
                response = client.post(url, {"user_public_id": str(self.target.public_id), "roles": roles}, format="json")
                self.assertEqual(response.status_code, 400, response.content)
                self.assertFalse(self.target.groups.exists())


@override_settings(AUTH_PASSWORD_VALIDATORS=[
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
])
class AdminPasswordSimilarityTests(TestCase):
    def test_admin_creation_password_uses_email_similarity(self):
        serializer = UserCreateSerializer(data={
            "email": "uniqueexample@example.com",
            "first_name": "UniqueExample",
            "password": "uniqueexample123",
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn("password", serializer.errors)


@override_settings(ROOT_URLCONF="accounts.tests.urls_api")
class PasswordResetOneTimeTests(TestCase):
    def test_reset_token_cannot_be_used_again(self):
        user = User.objects.create_user("reset@example.com", "Initial-Pass-789")
        token = PasswordResetToken.create_for_user(user)
        client = APIClient()
        url = reverse("accounts-password-reset-confirm")
        payload = {"token": token.token, "new_password": "Another-Pass-789", "confirm_password": "Another-Pass-789"}
        self.assertEqual(client.post(url, payload, format="json").status_code, 200)
        self.assertEqual(client.post(url, payload, format="json").status_code, 400)
        token.refresh_from_db()
        self.assertTrue(token.used)
        user.refresh_from_db()
        self.assertTrue(user.check_password("Another-Pass-789"))
