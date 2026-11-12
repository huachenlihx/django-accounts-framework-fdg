from django.contrib import admin, messages
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin, GroupAdmin
from django.contrib.auth.models import Group
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from .models import User, Role, RoleSetupWizard
from .role_setup import apply_role_setup, build_role_setup_preview


try:
    # Hide Django's technical "Groups" admin entry and expose the same table as
    # "Roles" instead. This does not create a custom role table.
    admin.site.unregister(Group)
except NotRegistered:
    pass


@admin.register(Role)
class RoleAdmin(GroupAdmin):
    """Admin-facing name for Django Groups used as business roles."""
    search_fields = ("name",)
    ordering = ("name",)
    change_list_template = "admin/accounts/role/change_list.html"

    def get_model_perms(self, request):
        # Show this proxy model in the admin index as "Roles".
        return super().get_model_perms(request)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "setup-wizard/",
                self.admin_site.admin_view(self.role_setup_wizard_view),
                name="accounts_role_setup_wizard",
            ),
        ]
        return custom_urls + urls

    def role_setup_wizard_link(self):
        url = reverse("admin:accounts_role_setup_wizard")
        return format_html('<a class="button" href="{}">Role Setup Wizard</a>', url)

    def role_setup_wizard_view(self, request):
        if not request.user.is_superuser:
            messages.error(request, "Only superusers can use the Role Setup Wizard.")
            return redirect("admin:accounts_role_changelist")

        if request.method == "POST":
            reset_existing = request.POST.get("reset_existing") == "1"
            result = apply_role_setup(reset_existing=reset_existing)
            messages.success(
                request,
                f"Role setup completed. Created {result['created']} role(s), updated {result['updated']} role(s).",
            )
            if result.get("missing_permissions"):
                messages.warning(
                    request,
                    "Some permissions were not found. Run migrations for feature apps first, then run the wizard again.",
                )
            return redirect("admin:accounts_role_setup_wizard")

        context = {
            **self.admin_site.each_context(request),
            "title": "Role Setup Wizard",
            "role_preview": build_role_setup_preview(),
            "opts": self.model._meta,
        }
        return render(request, "admin/accounts/role/setup_wizard.html", context)


@admin.register(RoleSetupWizard)
class RoleSetupWizardAdmin(admin.ModelAdmin):
    """Admin index entry that redirects directly to the Role Setup Wizard."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        return redirect("admin:accounts_role_setup_wizard")

    def get_model_perms(self, request):
        if request.user and request.user.is_superuser:
            return {"view": True}
        return {}



MANAGE_USERS_PERMISSION = "accounts.manage_users"


def _can_manage_users_in_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.has_perm(MANAGE_USERS_PERMISSION))
    )


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """User admin with superuser visibility restricted to superusers.

    This does not change the database or Django's superuser model. It only
    prevents non-superuser staff from seeing superuser accounts in the user
    changelist, direct object lookups, and the Manager relationship dropdown.
    Superusers retain full visibility.
    """
    list_display  = ['email', 'first_name', 'last_name', 'primary_role', 'department', 'is_active', 'is_activated']
    list_filter   = ['is_active', 'is_activated', 'department', 'groups']
    search_fields = ['email', 'first_name', 'last_name', 'employee_id', 'public_id']
    readonly_fields = BaseUserAdmin.readonly_fields + ('public_id',)
    ordering      = ['email']
    filter_horizontal = ('groups', 'user_permissions')

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Account fields', {
            'fields': (
                'public_id', 'employee_id', 'department', 'manager',
                'preferred_locale', 'must_change_password',
                'is_activated', 'activation_token',
            ),
            'description': 'Assign reusable roles. Internally, roles are Django Groups, so users can have multiple roles.',
        }),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'email', 'first_name', 'last_name',
                'password1', 'password2',
                'employee_id', 'department', 'manager', 'preferred_locale',
                'groups',
            ),
        }),
    )

    def has_module_permission(self, request):
        # Django Admin normally exposes a model only when the user has one of
        # Django's built-in add/change/delete/view model permissions. Our
        # business permission is custom, so explicitly map it to User admin
        # access.
        return _can_manage_users_in_admin(request.user)

    def get_model_perms(self, request):
        if not _can_manage_users_in_admin(request.user):
            return {}
        if request.user.is_superuser:
            return {"add": True, "change": True, "delete": True, "view": True}
        return {
            "add": True,
            "change": True,
            "delete": request.user.has_perm("accounts.delete_user"),
            "view": True,
        }

    def has_view_permission(self, request, obj=None):
        return _can_manage_users_in_admin(request.user)

    def has_add_permission(self, request):
        return _can_manage_users_in_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return _can_manage_users_in_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        # The custom manage_users permission does not silently grant destructive
        # deletion. Superusers can delete; other staff need Django's explicit
        # delete_user permission as well.
        return bool(
            request.user
            and request.user.is_authenticated
            and (
                request.user.is_superuser
                or (
                    request.user.has_perm(MANAGE_USERS_PERMISSION)
                    and request.user.has_perm("accounts.delete_user")
                )
            )
        )

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            # A Store Manager may manage normal accounts, but may never turn an
            # account into a superuser or grant direct permissions. Role/group
            # assignment remains available below with privileged roles filtered.
            readonly.extend(["is_superuser", "user_permissions"])
        return tuple(dict.fromkeys(readonly))

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        return queryset.filter(is_superuser=False)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Do not expose superuser accounts in the optional Manager selector to
        # non-superuser staff. Superusers keep the normal full queryset.
        if db_field.name == 'manager' and not request.user.is_superuser:
            kwargs['queryset'] = User.objects.filter(is_superuser=False).order_by('email')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        field = super().formfield_for_manytomany(db_field, request, **kwargs)
        if db_field.name == 'groups':
            if not request.user.is_superuser:
                # Match the API's privilege-escalation protection: non-superusers
                # cannot assign the Administrator/admin role through Django Admin.
                field.queryset = (
                    field.queryset
                    .exclude(name__iexact='Administrator')
                    .exclude(name__iexact='admin')
                )
            field.label = 'Roles'
            field.help_text = 'Select one or more roles for this user. Roles are stored using Django Groups.'
        elif db_field.name == 'user_permissions':
            field.label = 'Direct user permissions'
            field.help_text = 'Usually assign permissions to roles instead of directly to users.'
        return field

    def save_model(self, request, obj, form, change):
        # The reusable framework keeps username as an internal Django-compatibility
        # field. Admin forms may save a model instance directly instead of using
        # UserManager.create_user(), so ensure username is populated on creation.
        if obj.email and not obj.username:
            obj.email = obj.email.strip().lower()
            obj.username = obj.email
        if not request.user.is_superuser:
            # Defense in depth in case a forged POST attempts to bypass the
            # readonly admin field.
            obj.is_superuser = False
        super().save_model(request, obj, form, change)

