# Accounts — Reusable Django Authentication and Role Framework

A Django app that gives a project email-based user accounts and a session-authenticated JSON API for them: registration with email activation, login and logout, password reset, password change, a forced-password-change policy, role management with Django Groups, and a Role Setup Wizard in Django Admin.

It is designed for projects with a separate frontend (a single-page app or mobile client) that talks to Django over `fetch`/XHR with session cookies, but nothing prevents you from using the models, permissions and admin without the API.

## Contents

1. [Features](#1-features)
2. [Requirements and compatibility](#2-requirements-and-compatibility)
3. [Installation](#3-installation)
4. [Setup in a new Django project](#4-setup-in-a-new-django-project)
5. [Configuration reference](#5-configuration-reference)
6. [Forced password change and `ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES`](#6-forced-password-change-and-accounts_force_password_allowed_prefixes)
7. [Roles and permissions](#7-roles-and-permissions)
8. [Public identifiers (`public_id`)](#8-public-identifiers-public_id)
9. [Using the API from a frontend](#9-using-the-api-from-a-frontend)
10. [API reference](#10-api-reference)
11. [Emails](#11-emails)
12. [System checks](#12-system-checks)
13. [Testing](#13-testing)
14. [Limitations](#14-limitations)

---

## 1. Features

- **Email-based accounts.** A custom `accounts.User` model that logs in with an email address, plus optional `first_name`, `last_name`, `department`, `employee_id`, `manager`, `preferred_locale`, `is_activated` and `must_change_password` fields.
- **Self-service flows.** Registration (can be switched off), email activation with expiring links and resend, password reset by emailed link, and password change.
- **Password rules.** Every place that sets a password applies Django's `AUTH_PASSWORD_VALIDATORS` in addition to an 8-character minimum.
- **Roles are Django Groups.** A user can hold several roles. Your own apps check permissions with `user.has_perm("app_label.codename")`; this app only adds two permissions of its own (`accounts.manage_users`, `accounts.access_admin_tools`).
- **Role Setup Wizard** in Django Admin that creates the Groups you describe in settings and assigns their permissions.
- **Administrative API** for users with `accounts.manage_users`: list users, assign roles, set a temporary password, activate or deactivate accounts.
- **Forced password change.** Middleware that blocks a user who holds a temporary password until they set a new one. Its scope and exemptions are settings.
- **Opaque public identifiers.** Users are identified outside the backend by a random UUID (`public_id`), never by the database id.
- **Configurable emails.** Activation, password-reset and welcome emails with overridable templates, branding and frontend links.
- **System checks** (`manage.py check`) that report common configuration mistakes.

## 2. Requirements and compatibility

| Component | Supported |
| --- | --- |
| Python | 3.10 or newer, as far as your Django version supports (tested on 3.10, 3.12 and 3.13) |
| Django | 4.2, 5.2, 6.0 and 6.1 (all tested, each with the Python versions it supports) |
| Django REST Framework | 3.15+ (tested with 3.16) |
| Databases | Any database Django supports for a standard schema. SQLite, PostgreSQL and MariaDB are tested. |

The app has no dependency on other third-party packages. It uses Django's own email, sessions, auth and admin.

## 3. Installation

Install the package that provides the `accounts` Python package, for example:

```bash
pip install <distribution-name>
```

Replace `<distribution-name>` with the name the package is published under. If you vendor the source instead, copy the whole `accounts/` directory (including `migrations/`, `templates/` and `services/`) into your project so that `import accounts` works.

## 4. Setup in a new Django project

Do these steps **before the first `migrate`** of a new project. The user model cannot be swapped once a database has been created with a different one.

### 4.1 Settings

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
    # your apps ...
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Must come AFTER AuthenticationMiddleware. Optional, but required to enforce
    # the forced-password-change policy (see section 6).
    "accounts.force_password_middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
```

Keep the rest of your project's normal middleware; the list above only shows the required ordering.

### 4.2 URLs

Mount `accounts.urls` anywhere you like. The routes inside it start with `auth/` (and one `permissions/` route).

```python
from django.urls import include, path

urlpatterns = [
    path("api/", include("accounts.urls")),   # -> /api/auth/login/, /api/auth/me/, ...
    # your routes ...
]
```

The mount point is entirely your choice: `api/`, `v2/members/` or the site root all work. Every route has a stable name (for example `accounts-login`), so code inside your project should use `reverse("accounts-login")` instead of hard-coded paths. The forced-password-change middleware also finds its exempt endpoints by these names, so it needs no knowledge of the mount point.

### 4.3 Email

The app sends mail through Django's standard mail API. Configure your normal email settings (SMTP backend, `DEFAULT_FROM_EMAIL`, and so on). In development you can use the console backend. See [section 11](#11-emails).

### 4.4 Accounts settings

Add an `ACCOUNTS_FRAMEWORK` dictionary (all keys optional; see [section 5](#5-configuration-reference)):

```python
ACCOUNTS_FRAMEWORK = {
    "SITE_NAME": "Example Application",
    "FRONTEND_URL": "https://app.example.com",
    "SUPPORT_EMAIL": "support@example.com",
}
```

### 4.5 Database and first run

```bash
python manage.py check
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Then open Django Admin, find **Role setup wizard** under *Accounts*, and create the roles you defined in `ROLE_PRESETS` (see [section 7](#7-roles-and-permissions)).

### 4.6 Password rules

Registration, password change, password reset, administrator-set passwords and administrator-created users all run Django's password validators, so configure `AUTH_PASSWORD_VALIDATORS` in your settings (Django's standard four are recommended):

```python
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
```

A rejected password returns HTTP 400 with the validator messages (`{"password": [...]}` for registration, `{"error": "..."}` elsewhere). With no validators configured, only the 8-character minimum applies.

### 4.7 Cookies, CSRF and CORS

The API uses Django's session cookie and CSRF protection. If your frontend runs on a different origin than the API, configure the standard Django settings for it (`CSRF_TRUSTED_ORIGINS`, cookie `SameSite`/`Secure` settings, and a CORS solution of your choice). Accounts does not provide CORS handling.

---

## 5. Configuration reference

### 5.1 `ACCOUNTS_FRAMEWORK`

A dictionary in `settings.py`. Every key is optional.

| Key | Default | Meaning |
| --- | --- | --- |
| `SITE_NAME` | `"Application"` | Name shown in emails. |
| `FRONTEND_URL` | `"http://localhost:3000"` | Base URL of your frontend; used to build the links in emails. |
| `SITE_URL` | `"http://localhost:8000"` | Base URL of the backend, available to email templates. |
| `LOGO_URL` | `""` | Absolute URL of a logo shown in HTML emails (omitted when empty). |
| `SUPPORT_EMAIL` | `""` | Used as the `Reply-To` address and shown in emails. Falls back to the sender address. |
| `BRAND_COLOR` | `"#c41a5a"` | Accent colour (hex) in HTML emails. |
| `ENABLE_SELF_REGISTRATION` | `True` | `False` makes `POST auth/register/` return 403, so accounts can only be created by administrators. |
| `REQUIRE_EMAIL_ACTIVATION` | `True` | `True`: a registered user must follow the emailed link before logging in. `False`: they can log in immediately. |
| `ACTIVATION_PATH` | `"/activate-account"` | Frontend path of the activation page. The email link is `FRONTEND_URL + ACTIVATION_PATH + "?token=..."`. |
| `PASSWORD_RESET_PATH` | `"/reset-password"` | Frontend path of the reset page. The link is `FRONTEND_URL + PASSWORD_RESET_PATH + "?token=..."`. |
| `ACTIVATION_TOKEN_EXPIRY_HOURS` | `24` | Lifetime of an activation link. An expired link is rejected (400) and the user can request a new one with `auth/activate/resend/`. The value is also shown in the email. |
| `PASSWORD_RESET_EXPIRY_HOURS` | `2` | Lifetime of a password-reset link (single use). |
| `ACTIVATION_RESEND_RATE_PER_IP` | `"5/hour"` | Rate limit for `auth/activate/resend/` per client IP (DRF rate format; `None` disables). Exceeding it returns 429. |
| `ACTIVATION_RESEND_RATE_PER_EMAIL` | `"3/hour"` | Same endpoint, per email address, counted whether or not an account exists. Counters use Django's cache — use a shared cache (not the default per-process `LocMemCache`) when running several workers. |
| `SEND_WELCOME_EMAIL` | `False` | Send a welcome email after registration when activation is not required. |
| `ROLE_PRESETS` | `Administrator`, `User Manager` | Roles the Role Setup Wizard can create. See [section 7](#7-roles-and-permissions). |
| `MANAGER_ASSIGNABLE_ROLES` | `()` | Role (Group) names that a non-superuser holding `accounts.manage_users` may assign. Empty means only superusers can assign roles. |
| `SUPPORTED_LOCALES` | `("en", "fr", "de", "zh-Hans-CN")` | Values accepted for `preferred_locale` by `PATCH auth/me/` (max 20 characters each). |

Complete example:

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
    "ROLE_PRESETS": [],
    "MANAGER_ASSIGNABLE_ROLES": [],
    "SUPPORTED_LOCALES": ["en", "fr"],
}
```

### 5.2 Top-level settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES` | `("/",)` | URL prefixes the forced-password-change middleware protects. |
| `ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES` | `()` | URL prefixes exempted from that protection. |

Both are explained in the next section.

---

## 6. Forced password change and `ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES`

### 6.1 What it does

Every user has a `must_change_password` flag. It is set to `True` when an administrator assigns a temporary password (`auth/admin-set-password/`) or re-activates a deactivated account (`auth/set-active/`).

While the flag is `True`, `ForcePasswordChangeMiddleware` answers requests from that authenticated user with:

```http
HTTP/1.1 403 Forbidden
{"error": "You must change your temporary password.", "code": "password_change_required"}
```

The user is released as soon as they change their password with `auth/change-password/`, which clears the flag. Anonymous users and users whose flag is `False` are never affected.

The middleware always lets through, wherever you mounted `accounts.urls`:

- the account endpoints the user needs to fix the situation: `accounts-me`, `accounts-logout`, `accounts-change-password`, `accounts-csrf`, and the three `accounts-password-reset-*` routes;
- `STATIC_URL`;
- anything you list in `ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES`.

### 6.2 The two settings

Both are top-level settings and must be a tuple or list of strings that start with `/`.

**`ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES` — what is protected.** Only request paths beginning with one of these prefixes can be blocked. The default `("/",)` protects the whole site (secure by default), including Django Admin pages. Narrow it if only part of your site should be affected:

```python
# An API-only backend: only /api/ is blocked while a temporary password is active.
ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES = ("/api/",)
```

**`ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES` — exceptions to the protection.** Paths beginning with one of these prefixes are not blocked by this middleware even if they fall under a protected prefix. The default `()` means no extra exceptions.

```python
ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES = (
    "/api/public/downloads/",
    "/api/health/",
)
```

### 6.3 How to decide what to list

1. Start with no exceptions (`()`), and set the protected prefixes to match your URL layout.
2. Test a user with `must_change_password=True` against the pages and endpoints your frontend needs *during* the forced change. The account endpoints in 6.1 are already allowed, so a typical single-page app needs nothing more.
3. Add an exception only for a narrowly defined route that genuinely must work for such a user, for example a token-protected file download opened from an email, or a health check.
4. End each prefix with `/` so it cannot match unrelated paths.

### 6.4 Worked example

```python
ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES = ("/api/",)
ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES = ("/api/public/downloads/",)
```

For an authenticated user with `must_change_password=True` (accounts mounted at `/api/`):

| Request path | Result | Reason |
| --- | --- | --- |
| `/api/orders/` | 403 | Under `/api/`, no exception. |
| `/api/public/downloads/report.pdf` | passes the middleware | Matches an allowed prefix. |
| `/api/public/downloads-private/` | 403 | The prefix ends with `/`, so `downloads-private/` does not match. |
| `/api/auth/change-password/` | passes | Built-in account exemption. |
| `/api/auth/me/` | passes | Built-in account exemption. |
| `/dashboard/` | passes | Outside the protected prefix `/api/`. |

### 6.5 Important notes

- **"Passes the middleware" is not "public".** An allowed prefix only stops *this middleware* from returning 403. Authentication, permissions, token checks and ownership rules in your views still apply, and the user still has `must_change_password=True` until they change their password.
- **Matching is by prefix.** Every URL beginning with the string is exempted, so `"/api/"` as an allowed prefix would disable enforcement for the whole API. Keep exceptions narrow.
- **Validation.** A plain string (instead of a tuple or list), or a prefix that does not start with `/`, is reported by `manage.py check` (`accounts.E002`) and raises `TypeError` at request time.
- **Default scope and Django Admin.** With the default protected prefix `("/",)`, a user holding a temporary password also receives the JSON 403 on admin pages until they change it.
- **Install the middleware** after `AuthenticationMiddleware`. Without it, `must_change_password` is stored but not enforced (`accounts.W001`).

---

## 7. Roles and permissions

Roles are Django Groups; a user may belong to several. Permissions are Django's standard `app_label.codename` permissions, checked in your own code with `user.has_perm("app_label.codename")`.

### 7.1 Permissions defined by this app

| Permission | Grants |
| --- | --- |
| `accounts.manage_users` | Use the administrative user API (list users, assign roles, set passwords, activate/deactivate) and manage users in Django Admin. |
| `accounts.access_admin_tools` | Access the Accounts admin tools. |

Superusers always have every permission. A non-superuser with `manage_users` never sees or manages superuser accounts, and an unknown id and a hidden superuser's id produce the same 404.

### 7.2 Role presets and the Role Setup Wizard

`ROLE_PRESETS` lists the roles the wizard can create. Each item has a `name`, a `description` and a list of `permissions`. Use `"__all__"` for every permission.

```python
ACCOUNTS_FRAMEWORK = {
    "ROLE_PRESETS": [
        {"name": "Administrator", "description": "Everything.", "permissions": ["__all__"]},
        {
            "name": "Support Agent",
            "description": "Can manage user accounts.",
            "permissions": ["accounts.manage_users", "accounts.access_admin_tools"],
        },
        {"name": "Customer", "description": "No special permissions.", "permissions": []},
    ],
}
```

If `ROLE_PRESETS` is **missing** (or `None`), the built-in defaults are used: `Administrator` (all permissions) and `User Manager` (`accounts.manage_users`, `accounts.access_admin_tools`). In Django Admin, open *Accounts → Role setup wizard*, choose the presets and apply. Set `"ROLE_PRESETS": []` to intentionally offer no presets. Permissions that do not exist yet (for example from an app that is not installed) are reported instead of silently ignored.

### 7.3 Who may assign which roles

- A superuser may assign any role.
- A user with `accounts.manage_users` who is **not** a superuser may assign only the roles listed in `ACCOUNTS_FRAMEWORK["MANAGER_ASSIGNABLE_ROLES"]`. The default is empty, so by default only superusers can assign roles. The same allowlist applies to the Django Admin user form; delegated managers cannot edit staff accounts, superusers, or accounts with roles outside this allowlist or direct user permissions.
- List only low-privilege roles. A group can carry administrative permissions, so delegating it delegates those powers. Assigning a group named `Administrator` is always superuser-only.

```python
ACCOUNTS_FRAMEWORK = {
    "MANAGER_ASSIGNABLE_ROLES": ["Customer", "Support Agent"],
}
```

### 7.4 Using roles in your own code

```python
from rest_framework.permissions import BasePermission

class CanRunReports(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.has_perm("reports.run_report")
```

The permissions and role names of the signed-in user are included in the `auth/me/` and `auth/login/` responses (`permissions`, `roles`) so a frontend can show or hide features. The server must still enforce every permission itself.

---

## 8. Public identifiers (`public_id`)

`accounts.User.public_id` is a unique, random UUID (version 4) that is generated automatically and never changes.

- API responses contain `public_id` and **not** the integer primary key.
- The management endpoints (`set-active`, `assign-role`, `admin-set-password`) take the target in `user_public_id`.
- `UserCreateSerializer` takes a manager as that manager's `public_id`.
- Use the helper to validate an id that comes from a client before filtering by it:

```python
from accounts.identifiers import parse_public_id

public_id = parse_public_id(request.query_params.get("user"))   # UUID or None
if public_id is None:
    raise Http404
user = get_object_or_404(User, public_id=public_id)
```

Filtering a UUID field with malformed text raises an error, so always pass client input through `parse_public_id()` first.

A random identifier makes ids hard to guess or count, but it **does not replace** permission and ownership checks; keep those in every view.

If you build your own models that reference users in API payloads, follow the same convention: expose `user.public_id`, accept it in requests, and keep the integer id internal.

---

## 9. Using the API from a frontend

All paths below are relative to the mount point you chose (this guide writes them as `auth/...`; with `path("api/", include("accounts.urls"))` they become `/api/auth/...`).

1. **Fetch a CSRF token** once on startup: `GET auth/csrf/` returns `{"csrfToken": "..."}` and sets the `csrftoken` cookie.
2. **Send credentials and the token** on every state-changing request: use `credentials: "include"` (or `withCredentials: true`) and the `X-CSRFToken` header.
3. **Log in** with `POST auth/login/`. The response is the user (including `must_change_password`). Django sets the session cookie.
4. **Restore a session** on page load with `GET auth/me/`. A 401/403 means nobody is signed in.
5. **React to `password_change_required`.** If any response has status 403 and `code: "password_change_required"`, send the user to your change-password screen.
6. **Log out** with `POST auth/logout/`.

Your frontend must implement the pages the emails link to: `ACTIVATION_PATH` (call `GET auth/activate/?token=...` on load) and `PASSWORD_RESET_PATH` (call `GET auth/password-reset/check/?token=...` on load, then `POST auth/password-reset/confirm/`).

```js
await fetch("/api/auth/login/", {
  method: "POST",
  credentials: "include",
  headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
  body: JSON.stringify({ email, password }),
});
```

---

## 10. API reference

Authentication column: **public** = no login needed; **login** = any signed-in user; **manage** = signed in with `accounts.manage_users`; **superuser** = superusers only. Request and response bodies are JSON.

| Name | Method and path | Auth | Request body / query | Notes |
| --- | --- | --- | --- | --- |
| `accounts-csrf` | `GET auth/csrf/` | public | — | Returns `{csrfToken}` and sets the cookie. |
| `accounts-login` | `POST auth/login/` | public | `email`, `password` | 200 user; 401 bad credentials; 403 not activated or disabled. |
| `accounts-logout` | `POST auth/logout/` | login | — | Ends the session. |
| `accounts-me` | `GET auth/me/` | login | — | Current user, `permissions`, `roles`, `must_change_password`. |
| `accounts-me` | `PATCH auth/me/` | login | `preferred_locale` | Must be one of `SUPPORTED_LOCALES`. |
| `accounts-register` | `POST auth/register/` | public | `email`, `password`, `confirm_password`, `first_name`, `last_name` | 201; 400 for an invalid or weak password; 403 when self-registration is disabled. New users get no roles. |
| `accounts-activate` | `GET auth/activate/?token=` | public | `token` | Activates the account. 400 for an invalid, used or expired link. |
| `accounts-activate-resend` | `POST auth/activate/resend/` | public | `email` | Issues a new link with a fresh lifetime (the old one stops working). Always answers 200 (no account enumeration). |
| `accounts-password-reset-request` | `POST auth/password-reset/request/` | public | `email` | Always answers 200. |
| `accounts-password-reset-check` | `GET auth/password-reset/check/?token=` | public | `token` | Validates a reset link. |
| `accounts-password-reset-confirm` | `POST auth/password-reset/confirm/` | public | `token`, `new_password`, `confirm_password` | Sets the new password; a rejected password leaves the link usable. |
| `accounts-change-password` | `POST auth/change-password/` | login | `current_password`, `new_password`, `confirm_password` | Clears `must_change_password`. |
| `accounts-employees` | `GET auth/employees/` | manage | — | Users the caller may manage (superusers are hidden from non-superusers). |
| `accounts-roles` | `GET auth/roles/` | manage | — | Groups available as roles. |
| `accounts-assign-role` | `POST auth/assign-role/` | manage | `user_public_id`, and `role` or `roles` (+ `action`: `replace`, `add`, `remove`) | Subject to [section 7.3](#73-who-may-assign-which-roles). |
| `accounts-admin-set-password` | `POST auth/admin-set-password/` | manage | `user_public_id`, `new_password` | Sets a temporary password and `must_change_password=True`. |
| `accounts-set-active` | `POST auth/set-active/` | manage | `user_public_id`, `is_active` (**JSON boolean**) | Strings and numbers are rejected with 400. Re-activating forces a password change. Cannot be used on your own account. |
| `accounts-groups-permissions` | `GET auth/admin/groups-permissions/` | superuser | optional `?group=<name>` or `?permission=<app_label.codename>` | Groups and permissions are identified by name and code only. |
| `account-permissions` | `GET permissions/` | login | — | All permissions and the caller's own. |

Error responses use `{"error": "message"}` with an appropriate HTTP status. Do not assume any route is public because it is reachable; the table above is the contract.

---

## 11. Emails

Three emails are sent, each as multipart plain text plus HTML:

| Email | When | Link |
| --- | --- | --- |
| Activation | After registration when `REQUIRE_EMAIL_ACTIVATION` is `True`, and on resend | `FRONTEND_URL + ACTIVATION_PATH + "?token=..."` (valid for `ACTIVATION_TOKEN_EXPIRY_HOURS`) |
| Password reset | After `auth/password-reset/request/` for an eligible account | `FRONTEND_URL + PASSWORD_RESET_PATH + "?token=..."` (valid for `PASSWORD_RESET_EXPIRY_HOURS`) |
| Welcome | After registration when activation is not required and `SEND_WELCOME_EMAIL` is `True` | — |

The sender is `DEFAULT_FROM_EMAIL` (falling back to `EMAIL_HOST_USER`); `Reply-To` is `SUPPORT_EMAIL` when set.

To change the wording or design, override the templates by creating files with the same names in a template directory of your project that comes **before** the app in the template search order:

```text
accounts/emails/activation_email.html     accounts/emails/activation_email.txt
accounts/emails/password_reset_email.html accounts/emails/password_reset_email.txt
accounts/emails/welcome_email.html        accounts/emails/welcome_email.txt
```

For example, with `TEMPLATES[0]["DIRS"] = [BASE_DIR / "templates"]`, put your files in `templates/accounts/emails/`. Test every link against your own frontend routes.

---

## 12. System checks

`python manage.py check` reports these problems:

| ID | Severity | Meaning |
| --- | --- | --- |
| `accounts.E001` | Error | `AUTH_USER_MODEL` is not `"accounts.User"`. |
| `accounts.E002` | Error | A forced-password prefix setting is not a tuple/list of paths starting with `/`. |
| `accounts.E003` | Error | `ACCOUNTS_FRAMEWORK["MANAGER_ASSIGNABLE_ROLES"]` is not a list of strings. |
| `accounts.E004` | Error | `ForcePasswordChangeMiddleware` is listed before `AuthenticationMiddleware`. |
| `accounts.E005` | Error | `ACCOUNTS_FRAMEWORK["SUPPORTED_LOCALES"]` is empty or not a list of short strings. |
| `accounts.E006` | Error | `ACCOUNTS_FRAMEWORK["ROLE_PRESETS"]` must be a list of role dictionaries with names and permission lists. |
| `accounts.W001` | Warning | `ForcePasswordChangeMiddleware` is not installed, so `must_change_password` is not enforced. |

Run `python manage.py check --deploy` before production as well; it covers Django's own HTTPS and cookie recommendations.

---

## 13. Testing

In your project:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run   # should report "No changes detected"
python manage.py test accounts
```

The tests shipped with the app do not depend on your URL layout: they mount `accounts.urls` through their own test URL configurations (under `/api/`, under an unusual prefix and at the site root).

Also verify, in your own project and against your real database engine and frontend origin: registration and activation (including an expired link), login/logout, password reset, a forced password change (create a user, set a temporary password, confirm other endpoints return 403 and `auth/change-password/` works), role setup, CSRF behaviour and the email content and links.

---

## 14. Limitations

- **The user model is fixed.** The app ships a concrete `accounts.User` and requires `AUTH_USER_MODEL = "accounts.User"` from the very first migration. It cannot be added to a project that already has data under a different user model without a hand-written migration.
- **The route layout is part of the contract.** You choose where `accounts.urls` is mounted, but the paths inside it (`auth/login/`, `auth/me/`, ...) and the JSON shapes are fixed.
- **Groups and permissions have no public identifiers.** They are Django's own models and are identified by name and `app_label.codename`.
- **No CORS handling and no frontend.** Cross-origin setups need your own CORS configuration, and the activation/reset pages must be implemented in your frontend.
- **Password rules.** The app enforces a fixed 8-character minimum plus whatever `AUTH_PASSWORD_VALIDATORS` you configure; it has no setting for other policies such as password history or expiry.
- **No built-in rate limiting.** Login, registration and reset endpoints are not throttled by this app; add rate limiting at your proxy or with DRF throttling if the API is public.
