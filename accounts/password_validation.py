"""Run Django's AUTH_PASSWORD_VALIDATORS for every place the API sets a password."""
from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError


def password_errors(password: str, user=None) -> list[str]:
    """Return the validator messages for ``password`` (an empty list when it is acceptable).

    ``user`` may be saved or unsaved; validators such as UserAttributeSimilarityValidator use
    its email and name to reject passwords that resemble them.
    """
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        return list(exc.messages)
    return []
