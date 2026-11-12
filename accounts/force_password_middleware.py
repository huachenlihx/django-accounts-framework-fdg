"""Deny sensitive requests until a temporary password has been changed.

Nothing here assumes where ``accounts.urls`` is mounted or that the project is an API:

* The account endpoints a forced user must still reach (profile, logout, change password,
  CSRF, password reset) are found by reversing the named routes in ``accounts.urls``, so they
  stay exempt wherever the host project mounts them.
* Which part of the site is protected is a setting. The default protects every path, which
  fails closed; an API-only project can narrow it with
  ``ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES = ("/api/",)``.
* Extra exemptions (for example token-protected downloads) are listed in
  ``ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES``. Each prefix exempts every URL beginning with it.
"""
from django.conf import settings
from django.http import JsonResponse
from django.urls import NoReverseMatch, reverse

from .conf import path_prefixes_setting

# Routes of accounts.urls that a user with a temporary password must still be able to use.
EXEMPT_URL_NAMES = (
    "accounts-me",
    "accounts-logout",
    "accounts-change-password",
    "accounts-csrf",
    "accounts-password-reset-request",
    "accounts-password-reset-check",
    "accounts-password-reset-confirm",
)


def exempt_account_paths() -> frozenset:
    """Paths of the exempt account routes, wherever the project mounted accounts.urls."""
    paths = set()
    for name in EXEMPT_URL_NAMES:
        try:
            paths.add(reverse(name))
        except NoReverseMatch:  # accounts.urls not mounted (or mounted without these routes)
            continue
    return frozenset(paths)


class ForcePasswordChangeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (user is not None and user.is_authenticated
                and getattr(user, "must_change_password", False)
                and self._is_blocked(request.path)):
            return JsonResponse({"error": "You must change your temporary password.",
                                 "code": "password_change_required"}, status=403)
        return self.get_response(request)

    @staticmethod
    def _is_blocked(path: str) -> bool:
        protected = path_prefixes_setting("ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES", ("/",))
        if not path.startswith(protected):
            return False
        allowed = path_prefixes_setting("ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES", ())
        static_url = getattr(settings, "STATIC_URL", None)
        if isinstance(static_url, str) and static_url.startswith("/"):
            allowed = allowed + (static_url,)  # static assets are harmless
        if path.startswith(allowed):
            return False
        return path not in exempt_account_paths()
