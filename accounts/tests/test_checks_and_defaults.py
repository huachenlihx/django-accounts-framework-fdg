"""System checks and project-independent defaults of the accounts app."""
from django.test import SimpleTestCase, override_settings

from accounts import checks
from accounts.conf import accounts_setting
from accounts.role_setup import DEFAULT_ROLE_PRESETS

AUTH = "django.contrib.auth.middleware.AuthenticationMiddleware"
FORCE = checks.MIDDLEWARE_PATH


def ids():
    return sorted(problem.id for problem in checks.check_accounts_configuration(None))


class AccountsChecksTests(SimpleTestCase):
    @override_settings(MIDDLEWARE=[AUTH, FORCE], ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES=("/",),
                       ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES=(), ACCOUNTS_FRAMEWORK={})
    def test_clean_configuration_has_no_problems(self):
        self.assertEqual(ids(), [])

    @override_settings(AUTH_USER_MODEL="auth.User", MIDDLEWARE=[AUTH, FORCE])
    def test_wrong_user_model_is_an_error(self):
        self.assertIn("accounts.E001", ids())

    @override_settings(MIDDLEWARE=[AUTH, FORCE], ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES="/api/x/")
    def test_prefix_string_is_an_error(self):
        self.assertIn("accounts.E002", ids())

    @override_settings(MIDDLEWARE=[AUTH, FORCE], ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES=("api/",))
    def test_prefix_without_leading_slash_is_an_error(self):
        self.assertIn("accounts.E002", ids())

    @override_settings(MIDDLEWARE=[AUTH, FORCE], ACCOUNTS_FRAMEWORK={"MANAGER_ASSIGNABLE_ROLES": "Customer"})
    def test_assignable_roles_must_be_a_list(self):
        self.assertIn("accounts.E003", ids())

    @override_settings(MIDDLEWARE=[AUTH])
    def test_missing_middleware_is_a_warning(self):
        self.assertIn("accounts.W001", ids())

    @override_settings(MIDDLEWARE=[FORCE, AUTH])
    def test_middleware_before_authentication_is_an_error(self):
        self.assertIn("accounts.E004", ids())


class ProjectIndependentDefaultsTests(SimpleTestCase):
    def test_default_role_presets_reference_no_other_apps(self):
        allowed_apps = {"accounts", "__all__"}
        for preset in DEFAULT_ROLE_PRESETS:
            for code in preset.permissions:
                self.assertIn(code.split(".")[0], allowed_apps, f"{preset.name}: {code}")

    @override_settings(ACCOUNTS_FRAMEWORK={})
    def test_managers_may_assign_no_roles_by_default(self):
        self.assertEqual(tuple(accounts_setting("MANAGER_ASSIGNABLE_ROLES", ("x",))), ())


class SupportedLocalesTests(SimpleTestCase):
    def valid(self, value):
        from accounts.serializers import PreferredLocaleUpdateSerializer
        return PreferredLocaleUpdateSerializer(data={"preferred_locale": value}).is_valid()

    @override_settings(ACCOUNTS_FRAMEWORK={})
    def test_default_locales(self):
        self.assertTrue(self.valid("fr"))
        self.assertFalse(self.valid("es"))

    @override_settings(ACCOUNTS_FRAMEWORK={"SUPPORTED_LOCALES": ["en", "es"]})
    def test_locales_are_configurable(self):
        self.assertTrue(self.valid("es"))
        self.assertFalse(self.valid("fr"))

    @override_settings(MIDDLEWARE=[AUTH, FORCE], ACCOUNTS_FRAMEWORK={"SUPPORTED_LOCALES": []})
    def test_empty_locale_list_is_a_check_error(self):
        self.assertIn("accounts.E005", ids())
