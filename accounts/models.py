import secrets
import uuid
from datetime import timedelta
from django.db import models
from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group
from django.contrib.auth.base_user import BaseUserManager
from django.utils import timezone


class UserManager(BaseUserManager):
    """
    Custom user manager for email-based authentication.

    The framework uses email as the login identifier. The inherited
    AbstractUser.username field is kept only for Django compatibility and is
    automatically populated from email when users are created through the
    manager.
    """

    use_in_migrations = True

    def _normalize_email_for_username(self, email):
        if not email:
            raise ValueError('The email address is required.')
        return self.normalize_email(email).strip().lower()

    def create_user(self, email, password=None, **extra_fields):
        email = self._normalize_email_for_username(email)
        extra_fields['username'] = email
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        email = self._normalize_email_for_username(email)
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_activated', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email=email, password=password, **extra_fields)


class User(AbstractUser):
    # Identifier exposed outside the backend (API, URLs). The integer primary key is internal.
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # email is the unique login identifier — not username
    email = models.EmailField(unique=True)
    username = models.CharField(
        max_length=150, unique=True, blank=True,
        help_text='Auto-populated from email. Do not edit manually.',
    )

    employee_id = models.CharField(max_length=50, unique=True, null=True, blank=True)
    department = models.CharField(max_length=100, blank=True)
    manager = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='reports'
    )
    preferred_locale = models.CharField(max_length=20, default='en')
    must_change_password = models.BooleanField(
        default=False,
        help_text='If True, employee is forced to change password on next login.'
    )
    activation_token = models.CharField(max_length=64, blank=True, default='')
    # When the current activation token was issued; the link expires ACTIVATION_TOKEN_EXPIRY_HOURS later.
    activation_token_created_at = models.DateTimeField(null=True, blank=True)
    is_activated = models.BooleanField(
        default=False,
        help_text='Set to True after the user clicks the activation link in their email.'
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        roles = ', '.join(self.role_codes) or 'no roles'
        return f"{self.email} ({roles})"

    @property
    def role_codes(self):
        """Return role codes. Internally, roles are backed by Django Groups."""
        return list(self.groups.values_list('name', flat=True))

    @property
    def primary_role(self):
        """Display helper only. Authorization always uses all assigned roles."""
        return self.role_codes[0] if self.role_codes else 'no-role'

    class Meta:
        permissions = [
            ("manage_users", "Can manage users and roles"),
            ("access_admin_tools", "Can access admin tools"),
        ]

    @classmethod
    def generate_activation_token(cls):
        return secrets.token_urlsafe(48)

    @property
    def activation_token_is_valid(self):
        """True while the stored activation token is within its lifetime."""
        if not self.activation_token or self.activation_token_created_at is None:
            return False
        from .conf import accounts_setting
        hours = int(accounts_setting('ACTIVATION_TOKEN_EXPIRY_HOURS', 24))
        return timezone.now() < self.activation_token_created_at + timedelta(hours=hours)


class PasswordResetToken(models.Model):
    """
    One-time token for self-service password reset via email link.
    Expires after TOKEN_EXPIRY_HOURS hours. Invalidated after first use.
    """
    TOKEN_EXPIRY_HOURS = 2

    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='password_reset_tokens'
    )
    token      = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used       = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    @classmethod
    def create_for_user(cls, user):
        """Invalidate any existing tokens for this user, then create a fresh one."""
        cls.objects.filter(user=user, used=False).update(used=True)
        return cls.objects.create(
            user=user,
            token=secrets.token_urlsafe(48),
        )

    @property
    def is_valid(self):
        if self.used:
            return False
        try:
            from .email_utils import accounts_setting
            expiry_hours = int(accounts_setting('PASSWORD_RESET_EXPIRY_HOURS', self.TOKEN_EXPIRY_HOURS))
        except Exception:
            expiry_hours = self.TOKEN_EXPIRY_HOURS
        expiry = self.created_at + timedelta(hours=expiry_hours)
        return timezone.now() < expiry

    def __str__(self):
        return f"PasswordResetToken({self.user.email}, used={self.used})"


class Role(Group):
    """
    Admin-facing proxy for Django's built-in Group model.

    No new database table is created. A Role is exactly a Django Group,
    renamed in the admin and documentation to match business language.
    """

    class Meta:
        proxy = True
        verbose_name = "Role"
        verbose_name_plural = "Roles"


class RoleSetupWizard(Group):
    """
    Admin navigation proxy for the Role Setup Wizard.

    This does not create a new database table. It exists only so Django Admin
    can show a clear "Role Setup Wizard" link under the Accounts app.
    """

    class Meta:
        proxy = True
        verbose_name = "Role Setup Wizard"
        verbose_name_plural = "Role Setup Wizard"
