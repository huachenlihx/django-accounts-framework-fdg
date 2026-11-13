"""Django system checks that catch a mis-configured host project early (``manage.py check``)."""
from django.conf import settings
from django.core.checks import Error, Warning, register

MIDDLEWARE_PATH = "accounts.force_password_middleware.ForcePasswordChangeMiddleware"
AUTH_MIDDLEWARE_PATH = "django.contrib.auth.middleware.AuthenticationMiddleware"


@register()
def check_accounts_configuration(app_configs, **kwargs):
    problems = []

    if settings.AUTH_USER_MODEL != "accounts.User":
        problems.append(Error(
            "accounts requires AUTH_USER_MODEL = 'accounts.User' (found %r)." % settings.AUTH_USER_MODEL,
            hint="Set AUTH_USER_MODEL = 'accounts.User' before the first migration.",
            id="accounts.E001",
        ))

    for name in ("ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES", "ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES"):
        value = getattr(settings, name, ())
        if not isinstance(value, (tuple, list)) or not all(isinstance(item, str) and item.startswith("/") for item in value):
            problems.append(Error(
                f"{name} must be a tuple/list of URL path prefixes that start with '/'.",
                id="accounts.E002",
            ))

    config = getattr(settings, "ACCOUNTS_FRAMEWORK", {}) or {}
    roles = config.get("MANAGER_ASSIGNABLE_ROLES", ())
    if not isinstance(roles, (tuple, list)) or not all(isinstance(item, str) for item in roles):
        problems.append(Error(
            "ACCOUNTS_FRAMEWORK['MANAGER_ASSIGNABLE_ROLES'] must be a tuple/list of role (group) names.",
            id="accounts.E003",
        ))

    locales = config.get("SUPPORTED_LOCALES", ("en",))
    if (not isinstance(locales, (tuple, list)) or not locales
            or not all(isinstance(item, str) and 0 < len(item) <= 20 for item in locales)):
        problems.append(Error(
            "ACCOUNTS_FRAMEWORK['SUPPORTED_LOCALES'] must be a non-empty tuple/list of locale codes (max 20 characters).",
            id="accounts.E005",
        ))

    presets = config.get("ROLE_PRESETS", None)
    if presets is not None and (
        not isinstance(presets, (tuple, list))
        or not all(
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("permissions", ()), (tuple, list))
            and all(isinstance(code, str) for code in item.get("permissions", ()))
            for item in presets
        )
    ):
        problems.append(Error(
            "ACCOUNTS_FRAMEWORK['ROLE_PRESETS'] must be a list of role dictionaries.",
            id="accounts.E006",
        ))

    middleware = list(getattr(settings, "MIDDLEWARE", ()))
    if MIDDLEWARE_PATH not in middleware:
        problems.append(Warning(
            "ForcePasswordChangeMiddleware is not installed, so User.must_change_password is not enforced.",
            hint=f"Add '{MIDDLEWARE_PATH}' to MIDDLEWARE after AuthenticationMiddleware.",
            id="accounts.W001",
        ))
    elif AUTH_MIDDLEWARE_PATH in middleware and middleware.index(MIDDLEWARE_PATH) < middleware.index(AUTH_MIDDLEWARE_PATH):
        problems.append(Error(
            "ForcePasswordChangeMiddleware must come after AuthenticationMiddleware in MIDDLEWARE.",
            id="accounts.E004",
        ))
    return problems
