"""
Reusable email helpers for the accounts app.

This version is project-friendly:
- Email content lives in Django templates under accounts/templates/accounts/emails/.
- Branding comes from settings.ACCOUNTS_FRAMEWORK, with fallbacks to SITE_NAME and FRONTEND_URL.
- The app does not depend on any project-specific mail app.
"""
from __future__ import annotations

import datetime
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from .conf import DEFAULT_ACCOUNTS_FRAMEWORK, accounts_setting  # noqa: F401  (re-exported)


def _now_str() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _site_name() -> str:
    return str(accounts_setting("SITE_NAME", "Application"))


def _frontend_url() -> str:
    return str(accounts_setting("FRONTEND_URL", "http://localhost:3000")).rstrip("/")


def _from_email() -> str:
    return (
        getattr(settings, "DEFAULT_FROM_EMAIL", "")
        or getattr(settings, "EMAIL_HOST_USER", "")
        or "no-reply@example.com"
    )


def _common_context(user=None, **extra) -> dict[str, Any]:
    display_name = ""
    if user is not None:
        display_name = getattr(user, "first_name", "") or getattr(user, "email", "")
    context = {
        "site_name": _site_name(),
        "frontend_url": _frontend_url(),
        "site_url": accounts_setting("SITE_URL", ""),
        "logo_url": accounts_setting("LOGO_URL", ""),
        "support_email": accounts_setting("SUPPORT_EMAIL", ""),
        "brand_color": accounts_setting("BRAND_COLOR", "#c41a5a"),
        "default_from_email": _from_email(),
        "timestamp": _now_str(),
        "user": user,
        "display_name": display_name,
    }
    context.update(extra)
    return context


def send_template_email(*, subject: str, to_email: str, template_base: str, context: dict[str, Any]) -> None:
    """
    Send a multipart plain-text + HTML email using accounts email templates.

    template_base examples:
    - activation_email
    - password_reset_email
    - welcome_email
    """
    text_template = f"accounts/emails/{template_base}.txt"
    html_template = f"accounts/emails/{template_base}.html"

    context = {**context, "subject": subject}
    plain_body = render_to_string(text_template, context)
    html_body = render_to_string(html_template, context)

    if not plain_body.strip():
        plain_body = strip_tags(html_body)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=plain_body,
        from_email=_from_email(),
        to=[to_email],
        reply_to=[accounts_setting("SUPPORT_EMAIL", _from_email()) or _from_email()],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()


ACTIVATION_TOKEN_EXPIRY_HOURS = int(accounts_setting("ACTIVATION_TOKEN_EXPIRY_HOURS", 24))


def send_activation_email(user, token: str) -> None:
    """
    Send account activation email.

    Front-end URL:
    {FRONTEND_URL}{ACTIVATION_PATH}?token=<token>
    """
    activation_path = str(accounts_setting("ACTIVATION_PATH", "/activate-account"))
    activation_url = f"{_frontend_url()}{activation_path}?token={token}"
    expiry_hours = int(accounts_setting("ACTIVATION_TOKEN_EXPIRY_HOURS", ACTIVATION_TOKEN_EXPIRY_HOURS))
    expiry_duration = f"{expiry_hours} {'hour' if expiry_hours == 1 else 'hours'}"
    context = _common_context(user, activation_url=activation_url, expiry_hours=expiry_hours,
                              expiry_duration=expiry_duration)
    subject = f"{_site_name()} — Please activate your account"
    send_template_email(
        subject=subject,
        to_email=user.email,
        template_base="activation_email",
        context=context,
    )


def send_password_reset_email(user, token_obj) -> None:
    """
    Send password reset email for a PasswordResetToken instance.

    Front-end URL:
    {FRONTEND_URL}{PASSWORD_RESET_PATH}?token=<token>
    """
    reset_path = str(accounts_setting("PASSWORD_RESET_PATH", "/reset-password"))
    reset_url = f"{_frontend_url()}{reset_path}?token={token_obj.token}"
    expiry_hours = int(accounts_setting("PASSWORD_RESET_EXPIRY_HOURS", getattr(token_obj, "TOKEN_EXPIRY_HOURS", 2)))
    context = _common_context(user, reset_url=reset_url, expiry_hours=expiry_hours)
    subject = f"{_site_name()} — Password Reset"
    send_template_email(
        subject=subject,
        to_email=user.email,
        template_base="password_reset_email",
        context=context,
    )


def send_welcome_email(user) -> None:
    """Optional welcome email after activation or account creation."""
    context = _common_context(user)
    subject = f"Welcome to {_site_name()}"
    send_template_email(
        subject=subject,
        to_email=user.email,
        template_base="welcome_email",
        context=context,
    )
