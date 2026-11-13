"""Role setup utilities for the Accounts Framework.

The Accounts Framework intentionally does not create roles automatically during
migration or application startup. This module provides an explicit, admin-driven
wizard that can create recommended Django Groups and attach permissions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.conf import settings
from django.contrib.auth.models import Group, Permission


@dataclass(frozen=True)
class RolePreset:
    name: str
    description: str
    permissions: tuple[str, ...]


DEFAULT_ROLE_PRESETS: tuple[RolePreset, ...] = (
    RolePreset(
        name="Administrator",
        description="Full project administrator. This Group receives all currently available permissions.",
        permissions=("__all__",),
    ),
    RolePreset(
        name="User Manager",
        description="Can manage users and roles and open the account admin tools.",
        permissions=(
            "accounts.manage_users",
            "accounts.access_admin_tools",
        ),
    ),
)


def _permission_code(permission: Permission) -> str:
    return f"{permission.content_type.app_label}.{permission.codename}"


def get_role_presets() -> list[RolePreset]:
    """Return role presets from settings or built-in defaults.

    Projects may override the defaults with:

    ACCOUNTS_FRAMEWORK = {
        "ROLE_PRESETS": [
            {"name": "Employee", "description": "...", "permissions": ["app.codename"]},
        ]
    }
    """
    config = getattr(settings, "ACCOUNTS_FRAMEWORK", {}) or {}
    if "ROLE_PRESETS" not in config:
        return list(DEFAULT_ROLE_PRESETS)
    custom = config["ROLE_PRESETS"]
    if custom is None:
        return list(DEFAULT_ROLE_PRESETS)
    # An explicit empty list disables built-in role presets.
    if not isinstance(custom, (tuple, list)):
        raise ValueError("ACCOUNTS_FRAMEWORK['ROLE_PRESETS'] must be a list/tuple.")

    presets: list[RolePreset] = []
    for item in custom:
        presets.append(
            RolePreset(
                name=str(item.get("name", "")).strip(),
                description=str(item.get("description", "")).strip(),
                permissions=tuple(str(code).strip() for code in item.get("permissions", ()) if str(code).strip()),
            )
        )
    return [preset for preset in presets if preset.name]


def resolve_permission_codes(codes: Iterable[str]) -> tuple[list[Permission], list[str]]:
    """Resolve app_label.codename strings to Permission objects.

    The special code "__all__" resolves to every available permission.
    Returns (permissions, missing_codes).
    """
    codes = list(codes)
    if "__all__" in codes:
        return list(Permission.objects.select_related("content_type").all()), []

    permissions: list[Permission] = []
    missing: list[str] = []
    for code in codes:
        if "." not in code:
            missing.append(code)
            continue
        app_label, codename = code.split(".", 1)
        permission = Permission.objects.select_related("content_type").filter(
            content_type__app_label=app_label,
            codename=codename,
        ).first()
        if permission:
            permissions.append(permission)
        else:
            missing.append(code)
    return permissions, missing


def build_role_setup_preview() -> list[dict]:
    """Return preview data for the admin Role Setup Wizard."""
    preview: list[dict] = []
    for preset in get_role_presets():
        group = Group.objects.filter(name=preset.name).first()
        permissions, missing = resolve_permission_codes(preset.permissions)
        existing_codes = set()
        if group:
            existing_codes = {
                _permission_code(permission)
                for permission in group.permissions.select_related("content_type").all()
            }
        resolved_codes = sorted(_permission_code(permission) for permission in permissions)
        preview.append({
            "name": preset.name,
            "description": preset.description,
            "exists": bool(group),
            "permission_codes": resolved_codes,
            "missing_permission_codes": sorted(missing),
            "already_assigned_codes": sorted(existing_codes),
            "will_add_codes": sorted(set(resolved_codes) - existing_codes),
        })
    return preview


def apply_role_setup(reset_existing: bool = False) -> dict:
    """Create/update recommended Groups and attach configured permissions.

    If reset_existing is True, the Group's permissions are replaced with the
    preset permissions. Otherwise, preset permissions are added while existing
    permissions are preserved.
    """
    created = 0
    updated = 0
    missing_permissions: dict[str, list[str]] = {}

    for preset in get_role_presets():
        group, was_created = Group.objects.get_or_create(name=preset.name)
        permissions, missing = resolve_permission_codes(preset.permissions)

        if reset_existing:
            group.permissions.set(permissions)
        else:
            group.permissions.add(*permissions)

        if was_created:
            created += 1
        else:
            updated += 1

        if missing:
            missing_permissions[preset.name] = sorted(missing)

    return {
        "created": created,
        "updated": updated,
        "missing_permissions": missing_permissions,
    }
