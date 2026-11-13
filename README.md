# Django Accounts Framework FDG

A reusable Django authentication and role-management application built with **Django REST Framework**. It provides email-based accounts, session authentication, activation and password recovery, a custom user model with public UUIDs, user administration, and Django Group-based roles.

> **Current release:** [Version 0.2.1 on PyPI](https://pypi.org/project/django-accounts-framework-fdg/0.2.1/). This package supplies a custom user model and is intended primarily for new Django projects.

## Features

- Email-based registration, sign-in, sign-out, account activation, and password reset.
- User profile and administrative account APIs.
- A custom `accounts.User` model with a random, unique `public_id` UUID for public API references.
- Forced-password-change middleware with configurable protected paths and exemptions.
- Django Groups, multiple roles per user, permission checks, and a Django Admin Role Setup Wizard.
- Configurable project branding, frontend links, activation behavior, supported locales, and email templates.
- Password validation through the host project’s `AUTH_PASSWORD_VALIDATORS` for account creation and password changes.
- Configurable activation-link expiry and renewal when a new activation link is requested.
- Django system checks for important configuration requirements.

**Security boundary:** UUIDs are opaque identifiers, not authorization. Each project must still enforce authentication, permissions, and object ownership. The Accounts app does not replace a project's CORS, CSRF, HTTPS, or session-cookie configuration.

## Requirements and installation

The package metadata currently declares **Python 3.13+**, **Django 6.x**, and **Django REST Framework 3.16+**. These are declared compatibility ranges, not a claim that all combinations have been independently tested.

To install a local editable copy from the package repository:

```bash
python -m pip install -e .
```

After building a wheel with `python -m build`, you can also install that wheel into a **fresh virtual environment** to validate the packaged distribution:

```bash
python -m pip install path/to/django_accounts_framework_fdg-0.2.1-py3-none-any.whl
```

Install the published package from PyPI:

```bash
python -m pip install django-accounts-framework-fdg
```

> **Import-name note:** The installed distribution is named `django-accounts-framework-fdg`, but the Django application is imported as `accounts`. Avoid installing another package that uses the same top-level Python module name.

## Configure a new Django project

### 1. Install and configure the custom User model

In your project's `settings.py`, add the app and set the custom user model **before running initial migrations**:

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "accounts.apps.AccountsConfig",
]

AUTH_USER_MODEL = "accounts.User"
```

If your project already has users and migrations using a different user model, switching to `accounts.User` is **not** a drop-in operation. Plan a dedicated data and schema migration instead.

### 2. Configure middleware

Keep your project's normal Django security, session, CSRF, authentication, and message middleware. Place the Accounts middleware **after** `AuthenticationMiddleware`:

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.force_password_middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
```

### 3. Mount Accounts URLs

In the host project's `urls.py`:

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("accounts.urls")),
]
```

The `/api/` mount point is only an example. Accounts' own routes use `auth/…` and a `permissions/` endpoint relative to wherever you mount them. Named URLs let the forced-password middleware identify its essential account exemptions even when the mount point changes. Ensure your frontend calls the corresponding paths.

### 4. Configure branding and account behavior

Add an application-specific `ACCOUNTS_FRAMEWORK` dictionary to `settings.py`:

```python
ACCOUNTS_FRAMEWORK = {
    "SITE_NAME": "Example Application",
    "FRONTEND_URL": "https://app.example.com",
    "SITE_URL": "https://api.example.com/",
    "LOGO_URL": "https://example.com/static/logo.png",
    "SUPPORT_EMAIL": "support@example.com",
    "BRAND_COLOR": "#0F766E",
    "ENABLE_SELF_REGISTRATION": True,
    "REQUIRE_EMAIL_ACTIVATION": True,
    "ACTIVATION_PATH": "/activate-account",
    "PASSWORD_RESET_PATH": "/reset-password",
    "ACTIVATION_TOKEN_EXPIRY_HOURS": 24,
    "PASSWORD_RESET_EXPIRY_HOURS": 2,
    "SEND_WELCOME_EMAIL": False,
    "SUPPORTED_LOCALES": ["en", "fr"],  # Example: choose languages supported by your project.
    "ROLE_PRESETS": [],  # Define the new project's groups/permissions.
    "MANAGER_ASSIGNABLE_ROLES": [],
}
```

The `SUPPORTED_LOCALES` value above is an example, not a required default. Configure only locales your project supports; invalid values are reported by the Accounts configuration checks. Passwords are validated against your project’s `AUTH_PASSWORD_VALIDATORS`, so configure those validators in Django settings as well.

Set up a working Django email backend and sender identity in the host project. Ensure activation and reset paths exist in your frontend. Never commit SMTP credentials, database passwords, or Django secret keys.

### 5. Run initial setup

With your database configured, run:

```bash
python manage.py check
python manage.py migrate
python manage.py createsuperuser
```

Sign in to Django Admin and open the **Role Setup Wizard** to create your configured Groups. Business apps should define their own permissions and use `user.has_perm("app_label.codename")`; keep those domain-specific permission definitions outside Accounts.

## Forced password changes: protected paths versus allowed paths

When a signed-in user has `must_change_password=True`, `ForcePasswordChangeMiddleware` restricts access until their password is changed. Two settings let each project control the scope:

| Setting | Default | Purpose |
| --- | --- | --- |
| `ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES` | `("/",)` | **Where to enforce** the password-change restriction. The default covers the whole website. |
| `ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES` | `()` | **Exceptions** that the user may still reach before changing their password. |

For example, a project might enforce the rule for API routes while allowing a token-based public download endpoint:

```python
ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES = (
    "/api/",
)

ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES = (
    "/api/public-downloads/",
)
```

With `must_change_password=True`:

| Example request | Middleware behavior |
| --- | --- |
| `/api/private-data/` | Blocked with HTTP 403 |
| `/api/public-downloads/file-token/` | Permitted past this middleware |
| `/api/auth/change-password/` | Permitted by Accounts' built-in account-route exception |
| `/dashboard/` | Outside the configured protected scope |

**Important:** Allowed paths **do not clear** `must_change_password`; they only bypass this middleware check. Views must still enforce their own authentication, token validation, and permissions. Keep prefix exemptions narrow, because a prefix also exempts all paths underneath it. Necessary built-in account endpoints and static assets are also exempted so users can complete the password-change flow.

## Public identifiers and account administration

- `accounts.User.public_id` is the UUID intended for public account identifiers; internal integer database primary keys remain an implementation detail.
- Administration endpoints that target users accept `user_public_id` rather than exposing a database ID.
- Django Groups and permissions are referenced by Group name and permission code (`app_label.codename`), not public numeric IDs.
- A non-superuser holding `accounts.manage_users` may assign only Groups listed in `MANAGER_ASSIGNABLE_ROLES`. Keep this allowlist limited to low-privilege roles; the `Administrator` role is superuser-only to assign. Delegated user management in Django Admin should follow the same restriction.

Representative routes when mounted under `/api/`:

| Endpoint | Purpose |
| --- | --- |
| `/api/auth/csrf/` | Obtain CSRF cookie/token support |
| `/api/auth/register/` | Register account |
| `/api/auth/activate/` | Activate account |
| `/api/auth/login/`, `/api/auth/logout/` | Session authentication |
| `/api/auth/me/` | Current user/profile |
| `/api/auth/change-password/` | Change password |
| `/api/auth/password-reset/request/` | Start password reset |
| `/api/auth/password-reset/check/` | Validate reset flow |
| `/api/auth/password-reset/confirm/` | Complete reset |
| `/api/auth/roles/`, `/api/auth/assign-role/` | Roles and assignments |
| `/api/auth/set-active/` | User active status |
| `/api/auth/admin-set-password/` | Administrative password action |

See `accounts/urls.py` and the corresponding serializers/views for supported methods, request payloads, and permission requirements.

## Email templates

The package includes text and HTML templates under:

```text
accounts/templates/accounts/emails/
├── activation_email.html
├── activation_email.txt
├── password_reset_email.html
├── password_reset_email.txt
├── welcome_email.html
└── welcome_email.txt
```

Confirm these templates are present in the built wheel. The containing Django project must enable app template loading (`APP_DIRS=True`) or configure equivalent template loaders.

## Testing and release preparation

In a newly created Django integration project (with **no** business-specific apps installed), run:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate
python manage.py test accounts
```

Test registration, session login, activation expiry and resend, password validation and recovery, CSRF/cookies, forced password changes, delegated administrative permissions, and the Role Setup Wizard. Validate against each database engine and Python/Django version you intend to support.

To build and validate the distribution from this repository:

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
unzip -l dist/*.whl
```

Verify that the wheel includes `accounts/migrations/` and email templates, and that the metadata contains this README as its long description. **Passing package checks does not replace clean-install integration tests.**

## Scope and compatibility notes

- This package ships a concrete custom User model. Adopt it at project initialization, not as an unplanned replacement for an established user schema.
- The account API's JSON shapes and internal route names are part of its public integration contract.
- The package does not host your frontend, configure SMTP credentials, or automatically manage allowed cross-origin browser requests.
- **Migration compatibility:** Version `0.2.1` retains a regenerated `accounts/migrations/0001_initial.py` instead of an incremental `0002` migration. It is intended for fresh databases. Do **not** assume an existing database migrated under `0.1.0` can upgrade directly; a separate schema/data migration plan is required. Never delete an existing database to upgrade without preserving its data.
- Published release: [`0.2.1` on PyPI](https://pypi.org/project/django-accounts-framework-fdg/0.2.1/).

## Contact

**Email:** `huachenlihx@gmail.com` (plain text for copying)

**Source code:** [GitHub repository](https://github.com/huachenlihx/django-accounts-framework-fdg)

## License

This project is licensed under the **MIT License**. See the [LICENSE](https://github.com/huachenlihx/django-accounts-framework-fdg/blob/main/LICENSE) file for the full license text.
