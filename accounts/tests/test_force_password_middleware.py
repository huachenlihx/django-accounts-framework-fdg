"""Independent regression tests for project-configurable password-change exemptions."""
import json

from types import SimpleNamespace

from django.conf import settings
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from accounts.force_password_middleware import ForcePasswordChangeMiddleware


@override_settings(ROOT_URLCONF="accounts.tests.urls_api",
                   ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES=("/api/",))
class ForcePasswordChangeConfigurationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = ForcePasswordChangeMiddleware(
            lambda request: HttpResponse("allowed", status=200)
        )

    def response(self, path, *, authenticated=True, force_change=True):
        request = self.factory.get(path)
        request.user = SimpleNamespace(
            is_authenticated=authenticated, must_change_password=force_change
        )
        return self.middleware(request)

    @override_settings(ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES=(
        "/api/appointments/calendar/",
    ))
    def test_configured_calendar_prefix_is_exempt(self):
        self.assertEqual(
            self.response("/api/appointments/calendar/token.ics").status_code, 200
        )

    @override_settings(ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES=(
        "/api/appointments/calendar/",
    ))
    def test_unrelated_api_remains_blocked(self):
        response = self.response("/api/appointments/mine/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            json.loads(response.content)["code"],
            "password_change_required",
        )

    @override_settings(ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES=())
    def test_no_project_exemption_blocks_calendar_prefix(self):
        self.assertEqual(
            self.response("/api/appointments/calendar/token.ics").status_code, 403
        )

    @override_settings(ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES=(
        "/api/appointments/calendar/",
    ))
    def test_prefix_must_match_exact_segment(self):
        self.assertEqual(
            self.response("/api/appointments/calendar-other/").status_code, 403
        )

    @override_settings(ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES=())
    def test_accounts_password_change_endpoint_is_always_allowed(self):
        self.assertEqual(
            self.response("/api/auth/change-password/").status_code, 200
        )

    @override_settings(ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES=())
    def test_unauthenticated_request_is_not_blocked(self):
        self.assertEqual(
            self.response("/api/appointments/mine/", authenticated=False).status_code, 200
        )

    @override_settings(ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES=())
    def test_user_without_force_flag_is_not_blocked(self):
        self.assertEqual(
            self.response("/api/appointments/mine/", force_change=False).status_code, 200
        )


@override_settings(ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES=())
class ForcePasswordChangePortabilityTests(SimpleTestCase):
    """The middleware must not assume /api/ or where accounts.urls is mounted."""

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = ForcePasswordChangeMiddleware(lambda request: HttpResponse("allowed"))
        # Start from the app's own default: the host project may have set a narrower scope.
        ctx = override_settings()
        ctx.enable()
        self.addCleanup(ctx.disable)
        if hasattr(settings, "ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES"):
            del settings.ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES

    def status(self, path, *, authenticated=True, force_change=True):
        request = self.factory.get(path)
        request.user = SimpleNamespace(is_authenticated=authenticated, must_change_password=force_change)
        return self.middleware(request).status_code

    @override_settings(ROOT_URLCONF="accounts.tests.urls_alt")
    def test_account_endpoints_stay_exempt_wherever_they_are_mounted(self):
        for path in ("/v2/members/auth/me/", "/v2/members/auth/logout/", "/v2/members/auth/change-password/",
                     "/v2/members/auth/csrf/", "/v2/members/auth/password-reset/request/",
                     "/v2/members/auth/password-reset/check/", "/v2/members/auth/password-reset/confirm/"):
            self.assertEqual(self.status(path), 200, path)
        # ...and the usual /api/auth/ location is NOT special when it is not where they live.
        self.assertEqual(self.status("/api/auth/change-password/"), 403)
        # Other account routes (for example admin actions) remain blocked.
        self.assertEqual(self.status("/v2/members/auth/assign-role/"), 403)

    @override_settings(ROOT_URLCONF="accounts.tests.urls_root")
    def test_mounted_at_site_root(self):
        self.assertEqual(self.status("/auth/change-password/"), 200)
        self.assertEqual(self.status("/auth/employees/"), 403)

    @override_settings(ROOT_URLCONF="accounts.tests.urls_api")
    def test_default_protects_the_whole_site_not_just_api(self):
        self.assertEqual(self.status("/dashboard/"), 403)
        self.assertEqual(self.status("/admin/"), 403)
        self.assertEqual(self.status("/api/anything/"), 403)

    @override_settings(ROOT_URLCONF="accounts.tests.urls_api", ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES=("/api/",))
    def test_protected_prefixes_can_narrow_the_policy(self):
        self.assertEqual(self.status("/api/anything/"), 403)
        self.assertEqual(self.status("/dashboard/"), 200)

    @override_settings(ROOT_URLCONF="accounts.tests.urls_api", STATIC_URL="/static/")
    def test_static_files_are_never_blocked(self):
        self.assertEqual(self.status("/static/admin/css/base.css"), 200)

    @override_settings(ROOT_URLCONF="accounts.tests.urls_api")
    def test_users_without_a_temporary_password_are_unaffected(self):
        self.assertEqual(self.status("/dashboard/", force_change=False), 200)

    @override_settings(ROOT_URLCONF="accounts.tests.urls_api", ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES="/api/")
    def test_string_instead_of_tuple_is_rejected(self):
        with self.assertRaises(TypeError):
            self.status("/api/x/")
