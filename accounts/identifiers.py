"""Helpers for the opaque ``public_id`` (UUID) that identifies records outside the backend.

Database integer primary keys are internal. API responses, URLs, query parameters and
request bodies use ``public_id`` instead, so ids cannot be counted or guessed.
"""
from __future__ import annotations

import uuid


def parse_public_id(value) -> uuid.UUID | None:
    """Return ``value`` as a UUID, or None when it is missing or not a valid UUID.

    Filtering a UUIDField with malformed text raises a ValidationError, so every place that
    accepts a public_id from a client should pass it through here first.
    """
    if isinstance(value, uuid.UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value.strip())
    except ValueError:
        return None
