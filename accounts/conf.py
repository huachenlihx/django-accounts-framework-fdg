"""Configuration for the accounts app.

Everything project-specific comes from Django settings; the defaults below are
project-independent and deliberately conservative.

ACCOUNTS_FRAMEWORK (dict) keys - see README.md for the full description:
    SITE_NAME, FRONTEND_URL, SITE_URL, LOGO_URL, SUPPORT_EMAIL, BRAND_COLOR,
    ACTIVATION_PATH, PASSWORD_RESET_PATH, ACTIVATION_TOKEN_EXPIRY_HOURS,
    PASSWORD_RESET_EXPIRY_HOURS, SEND_WELCOME_EMAIL, ENABLE_SELF_REGISTRATION,
    REQUIRE_EMAIL_ACTIVATION, ROLE_PRESETS, MANAGER_ASSIGNABLE_ROLES, SUPPORTED_LOCALES

Top-level settings read by the forced-password-change middleware:
    ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES  (default ("/",): the whole site)
    ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES    (default (): no extra exemptions)
"""
from __future__ import annotations

from typing import Any

from django.conf import settings

DEFAULT_ACCOUNTS_FRAMEWORK = {
    "SITE_NAME": "Application",
    "FRONTEND_URL": "http://localhost:3000",
    "SITE_URL": "http://localhost:8000",
    "LOGO_URL": "",
    "SUPPORT_EMAIL": "",
    "BRAND_COLOR": "#c41a5a",
    "ACTIVATION_PATH": "/activate-account",
    "PASSWORD_RESET_PATH": "/reset-password",
    "ACTIVATION_TOKEN_EXPIRY_HOURS": 24,
    "PASSWORD_RESET_EXPIRY_HOURS": 2,
    "SEND_WELCOME_EMAIL": False,
    # Roles (Django Group names) that a user holding accounts.manage_users, but who is not a
    # superuser, may assign to others. Empty by default: only superusers can assign roles
    # until the project lists the low-privilege roles it is happy to delegate.
    "MANAGER_ASSIGNABLE_ROLES": (),
    # Locale codes a user may store as preferred_locale (PATCH auth/me/). Max 20 characters each.
    "SUPPORTED_LOCALES": ("en", "fr", "de", "zh-Hans-CN"),
}


def accounts_setting(name: str, default: Any = None) -> Any:
    """Read an Accounts Framework setting from settings.ACCOUNTS_FRAMEWORK."""
    config = getattr(settings, "ACCOUNTS_FRAMEWORK", {}) or {}
    if name in config:
        return config[name]
    if hasattr(settings, name):
        return getattr(settings, name)
    return DEFAULT_ACCOUNTS_FRAMEWORK.get(name, default)


def path_prefixes_setting(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Read a top-level setting that must be a tuple/list of URL path prefixes."""
    value = getattr(settings, name, default)
    if isinstance(value, str):
        raise TypeError(f"{name} must be a tuple/list of paths, not a string")
    return tuple(value)
