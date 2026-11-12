"""
Reusable DRF permission helpers for the Accounts Framework.

Rules:
- The accounts app owns only account/user-management permissions.
- Feature apps define their own model permissions in their own models.py.
- Feature apps keep their own DRF permission classes in their own permissions.py.
- Business logic should check Django permissions with user.has_perm(...).
"""
from __future__ import annotations

from typing import Iterable
from rest_framework.permissions import BasePermission


class HasDjangoPermission(BasePermission):
    """Base DRF permission that checks one Django auth permission."""

    required_permission: str | None = None
    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and self.required_permission
            and request.user.has_perm(self.required_permission)
        )


class HasAnyDjangoPermission(BasePermission):
    """Base DRF permission that checks any one of several Django permissions."""

    required_permissions: Iterable[str] = ()
    message = "You do not have permission to perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and any(
                request.user.has_perm(permission)
                for permission in self.required_permissions
            )
        )


class CanManageUsers(HasDjangoPermission):
    """Allows access to users who can manage accounts, groups, and roles."""

    required_permission = "accounts.manage_users"
    message = "You do not have permission to manage users."


def get_user_permission_codes(user) -> set[str]:
    """Return permission strings granted directly or through groups.

    Superusers receive all available Django permissions.
    """

    if not user or not getattr(user, "is_authenticated", False):
        return set()

    if getattr(user, "is_superuser", False):
        from django.contrib.auth.models import Permission

        return {
            f"{permission.content_type.app_label}.{permission.codename}"
            for permission in Permission.objects.select_related("content_type").all()
        }

    return set(user.get_all_permissions())


def user_has_permission(user, permission_code: str) -> bool:
    """Return True if the user has a specific Django permission."""

    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and user.has_perm(permission_code)
    )


def user_has_any_permission(user, permission_codes: Iterable[str]) -> bool:
    """Return True if the user has at least one permission in permission_codes."""

    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and any(user.has_perm(permission_code) for permission_code in permission_codes)
    )
