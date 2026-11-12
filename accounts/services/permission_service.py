"""Permission helpers using Django's built-in auth permissions and groups."""
from __future__ import annotations

from typing import Iterable


def get_user_role_codes(user) -> set[str]:
    """Return Django Group names. In this project, groups are roles."""
    if not user or not getattr(user, "is_authenticated", False):
        return set()
    return set(user.groups.values_list("name", flat=True))


def get_user_permission_codes(user) -> set[str]:
    """Return Django permission strings granted directly or through groups.

    Superusers receive all permissions from Django's auth system.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return set()
    return set(user.get_all_permissions())


def user_has_permission(user, permission_code: str) -> bool:
    """Return True if user has the specified Django permission."""
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and user.has_perm(permission_code)
    )


def user_has_any_permission(user, permission_codes: Iterable[str]) -> bool:
    """Return True if user has at least one permission in permission_codes."""
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and any(user.has_perm(code) for code in permission_codes)
    )


def get_all_permission_codes() -> list[str]:
    """Return all available Django permission codes as app_label.codename strings."""
    from django.contrib.auth.models import Permission

    return sorted(
        f"{permission.content_type.app_label}.{permission.codename}"
        for permission in Permission.objects.select_related("content_type").all()
    )
