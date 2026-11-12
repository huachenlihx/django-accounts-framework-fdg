# Accounts — Reusable Django Authentication and Role Framework

A reusable Django app providing email-based user accounts, session authentication, account activation, password recovery, user-profile and administrative APIs, Django Group roles, and a Role Setup Wizard. This document describes the **version packaged with Appointment Booking**; copy or package the `accounts/` directory together with its migrations and templates when adopting it in a *new* Django project.

> **Reuse status:** The forced-password-change middleware no longer contains Appointment Booking-specific URL exemptions. This app is **reusable with configuration**, not a universal plug-and-play drop-in: it defines a custom user model and uses some opinionated API paths, email templates, and role-management behavior. Verify dependencies, URL mounting, and permissions for each host project.

## 1. Features and ownership boundaries

- Email-based login, logout, registration, activation, password reset, and profile/session endpoints.
- A custom `accounts.User` model with a unique, randomly assigned `public_id` UUID. Internal integer primary keys are not exposed as public user identifiers by the Accounts API.
- A forced-password-change middleware policy. Its scope, its exemptions and the account endpoints it must still allow are all derived from Django settings and URL names, not hard-coded paths.
- Django system checks (`manage.py check`) that report a mis-configured host project.
- Django Groups for multiple roles per user; business apps define and enforce their own permissions using `user.has_perm("app_label.codename")`.
- Django Admin views and Role Setup Wizard for permission presets.
- Customizable account emails and frontend links via `ACCOUNTS_FRAMEWORK`.

**Project-specific responsibilities belong outside Accounts:** appointments, calendar routes, business roles, staff schedules, and other domain APIs. `origin_management` is a separate optional app for CORS and is *not* required simply to use Accounts.

## 2. Prerequisites and integrating into a fresh Django project

1. Install the dependencies your project's Accounts code actually imports (including Django, Django REST Framework, and any email/template utilities). The source version should be tested with your chosen Django and database versions; this README is not a claim of standalone packaging or published PyPI support.
2. Copy `accounts/` including `migrations/`, `templates/`, `services/`, and any other files into the Django source tree.
3. **Before the very first migration**, configure the custom user model and installed apps:

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

4. Mount the account URLs under `/api/`, because `accounts.urls` already defines paths beginning with `auth/` (and a `permissions/` route):

   ```python
   from django.urls import include, path

   urlpatterns = [
       path("api/", include("accounts.urls")),
       # Your own app routes go here.
   ]
   ```

   You may mount `accounts.urls` under any prefix (`api/`, `v2/members/`, or the site root). Every route has a stable name (`accounts-login`, `accounts-me`, ...), and the middleware finds its exempt endpoints by reversing those names, so nothing depends on the mount point. The paths *inside* `accounts.urls` (`auth/login/`, `auth/me/`, ...) are fixed; your frontend must use whatever mount point you chose.

5. For forced password changes, install the middleware **after** Django's authentication middleware:

   ```python
   MIDDLEWARE = [
       "django.contrib.sessions.middleware.SessionMiddleware",
       "django.contrib.auth.middleware.AuthenticationMiddleware",
       "accounts.force_password_middleware.ForcePasswordChangeMiddleware",
       # Other middleware appropriate for your project.
   ]
   ```

   This is a minimal ordering illustration; retain the rest of your project's normal middleware (especially security and CSRF middleware).

6. Configure `ACCOUNTS_FRAMEWORK`, database, mail transport, hosts, HTTPS/cookies, and optional frontend/CORS origins for your deployment. Run migrations against a **fresh** database, then create a superuser:

   ```bash
   python manage.py check
   python manage.py migrate
   python manage.py createsuperuser
   ```

   Run the Role Setup Wizard in Django Admin when you want the configured role presets. Do not re-use a consolidated `0001_initial.py` migration to overwrite an established project with existing user records or migration history.

## 3. Configure account branding and behavior

In the new Django project's `settings.py`, define an app-neutral configuration such as:

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
    "ROLE_PRESETS": [],  # Define project-specific role names/permissions here.
}
```

Avoid copying Appointment Booking's or United Supermarket's URLs, logos, names, and business permissions into unrelated projects. Configure real SMTP credentials and sender information separately; do not commit secrets.

### Email templates

Edit HTML and text messages at:

```text
accounts/templates/accounts/emails/
├── activation_email.html
├── activation_email.txt
├── password_reset_email.html
├── password_reset_email.txt
├── welcome_email.html
└── welcome_email.txt
```

Test activation, reset, and welcome links against your own frontend route configuration.

## 4. Forced password change (`must_change_password`)

`ForcePasswordChangeMiddleware` returns `403 {"code": "password_change_required"}` to an **authenticated** user whose `must_change_password` is true, except for:

1. the account endpoints needed to fix the situation: `accounts-me`, `accounts-logout`, `accounts-change-password`, `accounts-csrf` and the three `accounts-password-reset-*` routes. They are found with `reverse()`, wherever `accounts.urls` is mounted;
2. `STATIC_URL` (static assets);
3. any prefix you list in `ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES`.

Settings (top-level, in the host project's `settings.py`):

| Setting | Default | Meaning |
| --- | --- | --- |
| `ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES` | `("/",)` | Only paths starting with one of these prefixes are blocked. The default protects the **whole site** (fails closed); an API-only project can narrow it, for example `("/api/",)`. |
| `ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES` | `()` | Extra exemptions, for example token-protected downloads. Each prefix exempts **every URL beginning with it**, so keep it narrow and end it with `/`. |

### 4.1 Understanding protected and allowed URL prefixes

These settings apply when an **authenticated user has `must_change_password=True`**. They control which requests the forced-password-change middleware blocks **until the user changes their password**; they do **not** decide whether the user's password-change requirement exists.

- **`ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES` — URLs to protect.** Requests whose paths begin with these prefixes are blocked until the user changes their password, unless an exception applies.
- **`ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES` — exceptions to the protection.** These URLs are allowed through *this middleware* even when they fall under a protected prefix. The user still has `must_change_password=True` and must eventually change their password.

**Example: Appointment Booking** (illustrative host-project configuration, not a default of the reusable Accounts app). Add this in the host project's `settings.py`:

```python
ACCOUNTS_FORCE_PASSWORD_PROTECTED_PREFIXES = (
    "/api/",
)

ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES = (
    "/api/appointments/calendar/",
)
```

With these settings, an authenticated user whose `must_change_password` is `True` experiences the following:

| URL | Access while `must_change_password=True` | Why |
| --- | --- | --- |
| `/api/appointments/book/` | **Blocked (HTTP 403)** | Under `/api/`, with no exception |
| `/api/appointments/mine/` | **Blocked (HTTP 403)** | Under `/api/`, with no exception |
| `/api/appointments/calendar/abc.ics` | **Allowed through** | Matches the explicitly allowed calendar prefix |
| `/api/auth/change-password/` | **Allowed through** | Built-in Accounts exception, so the user can change their password |

**Important:** “Allowed through” means only that this particular middleware does not block the request. Normal authentication, token validation, authorization and view-level rules still apply. An allowed prefix **does not** set `must_change_password=False` or waive the requirement. Once the password is changed successfully and the flag becomes `False`, these forced-password restrictions no longer apply.

For a **new Django project**, choose the protected prefixes to match that project's URL layout (or omit the setting to use the default `("/",)` for whole-site protection). Use allowed prefixes only for narrowly defined routes that genuinely need an exception. If no project-specific exception is needed, omit `ACCOUNTS_FORCE_PASSWORD_ALLOWED_PREFIXES` or leave it as `()`. For example, a project could protect `("/api/", "/dashboard/")` and exempt one specific `/api/public/download/` subtree when appropriate.

**Security:** Prefix matching applies to *all* URLs beginning with the configured string. Avoid broad exemptions such as `"/api/"` unless you intend to bypass enforcement for every API endpoint.

Both settings must be tuples/lists of paths starting with `/`; a plain string is rejected (`TypeError` at request time and a system-check error). With the default scope, a user with a temporary password cannot open Django Admin pages either (they receive the JSON 403) until the password is changed. These exemptions only bypass this middleware; views must still perform authentication, token checks and authorization.

Install the middleware **after** `AuthenticationMiddleware`; `manage.py check` verifies this (see section 7).

## 5. Public identifiers and access control

`accounts.User.public_id` is a unique UUID used by public-facing account APIs. The public user serializer returns `public_id`, not the internal database `id`. The management endpoints below accept `user_public_id` in their request payloads.

```text
/api/auth/set-active/
/api/auth/assign-role/
/api/auth/admin-set-password/
```

`UserCreateSerializer` accepts a manager `public_id`. Use `accounts.identifiers.parse_public_id()` to validate supplied IDs. Malformed, unknown, and unauthorized identifiers should produce appropriate validation errors or 404s, never reveal another user's data. UUIDs reduce identifier enumeration but **do not replace permissions or ownership checks**.

Roles are Django Groups; permission strings use `app_label.codename`. Users can belong to multiple Groups. The account-owned permissions include `accounts.manage_users` and `accounts.access_admin_tools`. Business feature apps define their own permissions.

**Who may assign which roles.** A user holding `accounts.manage_users` who is not a superuser may assign only the roles named in `ACCOUNTS_FRAMEWORK["MANAGER_ASSIGNABLE_ROLES"]`. The default is empty, so out of the box only superusers can assign roles. List only low-privilege roles; other groups may carry administrative permissions. Assigning the `Administrator` group is always superuser-only.

```python
ACCOUNTS_FRAMEWORK = {
    "MANAGER_ASSIGNABLE_ROLES": ["Customer", "Appointment Staff"],  # Appointment Booking
}
```

**Role presets.** The Role Setup Wizard offers `ROLE_PRESETS` from `ACCOUNTS_FRAMEWORK`. The built-in default contains only project-independent presets: `Administrator` (all permissions) and `User Manager` (`accounts.manage_users`, `accounts.access_admin_tools`). Define your own presets for business roles.

## 6. API routes

Because `accounts.urls` is mounted under `/api/`, relevant endpoints include:

```text
/api/auth/csrf/                      accounts-csrf
/api/auth/login/                     accounts-login
/api/auth/logout/                    accounts-logout
/api/auth/me/                        accounts-me
/api/auth/register/                  accounts-register
/api/auth/activate/                  accounts-activate
/api/auth/activate/resend/           accounts-activate-resend
/api/auth/change-password/           accounts-change-password
/api/auth/password-reset/request/    accounts-password-reset-request
/api/auth/password-reset/check/      accounts-password-reset-check
/api/auth/password-reset/confirm/    accounts-password-reset-confirm
/api/auth/roles/                     accounts-roles
/api/auth/assign-role/               accounts-assign-role
/api/auth/admin-set-password/        accounts-admin-set-password
/api/auth/set-active/                accounts-set-active
/api/auth/employees/                 accounts-employees
/api/auth/admin/groups-permissions/  accounts-groups-permissions
/api/permissions/                    account-permissions
```

The `/api/` prefix is only where Appointment Booking mounts `accounts.urls`; use `reverse("accounts-login")` etc. instead of hard-coding paths.

See `accounts/urls.py`, serializers and views for HTTP methods, request fields and permission checks. Don't assume any route is public just because it has an API URL.

## 7. Tests and deployment checklist

Run from the containing Django project root:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test accounts
```

In the Appointment Booking host project, also run its existing middleware/integration tests:

```bash
python manage.py test accounts.tests appointments.tests.test_password_change_middleware
```

`manage.py check` reports configuration problems: `accounts.E001` (`AUTH_USER_MODEL` is not `accounts.User`), `E002` (bad prefix settings), `E003` (bad `MANAGER_ASSIGNABLE_ROLES`), `E004` (middleware placed before `AuthenticationMiddleware`) and `W001` (forced-password middleware not installed, so `must_change_password` is not enforced).

The `accounts` tests are self-contained: they mount `accounts.urls` through their own test URL configurations (`accounts/tests/urls_*.py`), under `/api/`, under an unusual prefix and at the site root.

Verify session login/logout, registration/activation, reset, forced password change, role setup, public UUIDs, CSRF, and email content in the new project. Test against its actual database engine and frontend origin.

**Operational boundaries:** Django must apply initial Accounts migrations before creating users. Switching an existing project from another user model may require a careful migration and cannot be treated as copying source files. If using a separate frontend origin, configure CORS, CSRF, cookies and credentials correctly; the optional `origin_management` app can help manage CORS but is not an authentication substitute.

## 8. Reuse maturity and remaining limits

Configurable through settings, with project-independent defaults: the mount point of `accounts.urls`, the forced-password scope and exemptions, which roles managers may assign, role presets, branding and email links, activation/reset behavior, and registration.

Still fixed by design:

- **The user model.** The app ships a concrete `accounts.User` and requires `AUTH_USER_MODEL = "accounts.User"` before the first migration (checked by `accounts.E001`). A host that needs its own user model cannot use the app as-is; the next step would be an abstract base user class plus `get_user_model()` throughout the views, serializers and admin.
- **Route layout.** Paths inside `accounts.urls` (`auth/...`) and the JSON request/response shapes are part of the app's contract.
- **Packaging.** The app is copied into each project; it is not a published, versioned package and is tested here only through Appointment Booking plus its own `accounts/tests`.

If you maintain it across several products, extract it into a private versioned Python package after an independent integration test with a minimal Django project, and write release notes whenever you change public serializers, routes, settings keys or the user model.
