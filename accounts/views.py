from django.conf import settings as django_settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import Group, Permission
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from .identifiers import parse_public_id
from .models import User, PasswordResetToken
from .password_validation import password_errors
from django.utils import timezone
from django.db import transaction
from .serializers import UserSerializer, UserCreateSerializer, RegisterSerializer, PreferredLocaleUpdateSerializer
from .email_utils import send_activation_email, send_password_reset_email, send_welcome_email, accounts_setting, ACTIVATION_TOKEN_EXPIRY_HOURS
from .services.permission_service import user_has_permission


PERMISSION_USER_MANAGE = "accounts.manage_users"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_superuser(user):
    """True only for authenticated Django superusers."""
    return bool(user and user.is_authenticated and user.is_superuser)


def _permission_code(permission):
    """Return a Django permission as app_label.codename."""
    return f"{permission.content_type.app_label}.{permission.codename}"


def _permission_to_dict(permission, include_groups=False):
    """Serialize a Django auth Permission for API responses."""
    data = {
        "code": _permission_code(permission),
        "app_label": permission.content_type.app_label,
        "model": permission.content_type.model,
        "codename": permission.codename,
        "name": permission.name,
    }
    if include_groups:
        data["groups"] = [
            {"name": group.name}
            for group in permission.group_set.all().order_by("name")
        ]
    return data


def _group_to_dict(group, include_permissions=True):
    """Serialize a Django auth Group used as a business role."""
    data = {
        "name": group.name,
    }
    if include_permissions:
        permissions = group.permissions.select_related("content_type").order_by(
            "content_type__app_label", "codename"
        )
        data["permissions"] = [_permission_to_dict(permission) for permission in permissions]
        data["permission_codes"] = [_permission_code(permission) for permission in permissions]
        data["permission_count"] = len(data["permissions"])
    return data


def _get_group_by_query(value):
    """Find a Group by its exact (unique) name."""
    if not value:
        return None
    return Group.objects.filter(name=str(value).strip()).first()


def _get_permission_by_query(value):
    """Find a Permission by app_label.codename (or a bare codename)."""
    if not value:
        return None
    value = str(value).strip()
    qs = Permission.objects.select_related("content_type")
    if "." in value:
        app_label, codename = value.split(".", 1)
        return qs.filter(content_type__app_label=app_label, codename=codename).first()
    return qs.filter(codename=value).first()


def _can_manage_users(user):
    """True if user has reusable user-management permission."""
    return user_has_permission(user, PERMISSION_USER_MANAGE)


def _manageable_users_for(user):
    """Return users the requesting account is allowed to see/manage.

    Superusers can see and manage every account, including other superusers.
    Non-superusers with user-management permission never receive superuser
    accounts from this queryset. Keeping this rule in one helper also prevents
    privileged actions from bypassing the list-page visibility restriction by
    submitting a superuser's id directly.
    """
    queryset = User.objects.all()
    if _is_superuser(user):
        return queryset
    return queryset.filter(is_superuser=False)


def _get_manageable_user(user, user_public_id):
    """Return a visible/manageable target account, or None.

    The target is identified by its public_id (UUID). For non-superusers, a superuser's
    public_id is intentionally treated the same as an unknown one so the API does not
    disclose that a hidden superuser exists.
    """
    public_id = parse_public_id(user_public_id)
    if public_id is None:
        return None
    return _manageable_users_for(user).filter(public_id=public_id).first()


# ── Auth views ────────────────────────────────────────────────────────────────

class CsrfView(APIView):
    """GET auth/csrf/ — sets the csrftoken cookie."""
    permission_classes = [AllowAny]

    def get(self, request):
        from django.middleware.csrf import get_token
        csrf_token = get_token(request)
        return Response({'csrfToken': csrf_token})


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    """POST auth/login/ — accepts { email, password }."""
    permission_classes = [AllowAny]

    def post(self, request):
        email    = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')

        if not email or not password:
            return Response({'error': 'Email and password are required.'}, status=400)

        user = authenticate(request, username=email, password=password)

        if user is None:
            return Response({'error': 'Invalid email or password.'}, status=401)

        if not user.is_activated:
            return Response(
                {'error': 'Please activate your account via the link sent to your email.'},
                status=403
            )

        if not user.is_active:
            return Response({'error': 'This account has been disabled.'}, status=403)

        login(request, user)

        data = UserSerializer(user).data
        data['must_change_password'] = user.must_change_password
        return Response(data)


class LogoutView(APIView):
    """POST auth/logout/"""
    def post(self, request):
        logout(request)
        return Response({'status': 'logged out'})


class MeView(APIView):
    """GET/PATCH auth/me/ — read the profile or update preferred locale."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        data = UserSerializer(request.user).data
        data['must_change_password'] = request.user.must_change_password
        return Response(data)

    def patch(self, request):
        serializer = PreferredLocaleUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request.user.preferred_locale = serializer.validated_data['preferred_locale']
        request.user.save(update_fields=['preferred_locale'])
        data = UserSerializer(request.user).data
        data['must_change_password'] = request.user.must_change_password
        return Response(data)


# ── Self-registration ─────────────────────────────────────────────────────────

class RegisterView(APIView):
    """
    POST auth/register/
    Body: { email, password, confirm_password, first_name, last_name }

    Creates an active but unactivated account and sends an activation email.
    Self-registered users are not assigned any default roles/groups.
    Roles can be assigned later by users with the accounts.manage_users permission.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        if not accounts_setting("ENABLE_SELF_REGISTRATION", True):
            return Response({'error': 'Self-registration is disabled.'}, status=403)

        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        data = serializer.validated_data

        require_activation = bool(accounts_setting("REQUIRE_EMAIL_ACTIVATION", True))
        token = User.generate_activation_token() if require_activation else ""

        user = User.objects.create_user(
            email=data['email'],
            password=data['password'],
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            is_active=True,
            is_activated=not require_activation,
            activation_token=token,
            activation_token_created_at=timezone.now() if require_activation else None,
        )
        if require_activation:
            try:
                send_activation_email(user, token)
            except Exception:
                # Don't fail registration if email sends fails — admin can resend
                pass
            detail = 'Registration successful. Please check your email to activate your account.'
        else:
            if accounts_setting("SEND_WELCOME_EMAIL", False):
                try:
                    send_welcome_email(user)
                except Exception:
                    pass
            detail = 'Registration successful. You can now log in.'

        return Response({'detail': detail}, status=201)


class ActivateAccountView(APIView):
    """
    GET auth/activate/?token=<token>
    Called when the user clicks the activation link in their email.
    Sets is_activated=True and clears the activation_token.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        token = request.query_params.get('token', '').strip()
        if not token:
            return Response({'error': 'Activation token is required.'}, status=400)

        try:
            user = User.objects.get(activation_token=token, is_activated=False)
        except User.DoesNotExist:
            return Response(
                {'error': 'Invalid or already-used activation link.'},
                status=400
            )

        if not user.activation_token_is_valid:
            return Response(
                {'error': 'This activation link has expired. Please request a new one.'},
                status=400
            )

        user.is_activated    = True
        user.activation_token = ''
        user.activation_token_created_at = None
        user.save()

        if accounts_setting("SEND_WELCOME_EMAIL", False):
            try:
                send_welcome_email(user)
            except Exception:
                pass

        return Response({'detail': 'Account activated. You can now log in.'})


class ResendActivationView(APIView):
    """
    POST auth/activate/resend/
    Body: { email }

    Resends the activation email only for eligible accounts:
    - the account exists,
    - is_active=True,
    - is_activated=False.

    Always returns the same 200 response to prevent email enumeration.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if email:
            try:
                user = User.objects.get(email=email, is_active=True, is_activated=False)
                token = User.generate_activation_token()
                user.activation_token = token
                user.activation_token_created_at = timezone.now()
                user.save(update_fields=['activation_token', 'activation_token_created_at'])
                try:
                    send_activation_email(user, token)
                except Exception:
                    # Do not reveal email delivery failures to the public endpoint.
                    pass
            except User.DoesNotExist:
                pass
        return Response({
            'detail': 'If an eligible account exists for this email, an activation email has been sent.'
        })


# ── Self-service password reset ───────────────────────────────────────────────

class PasswordResetRequestView(APIView):
    """
    POST auth/password-reset/request/
    Body: { email }
    Always returns 200 — never reveals whether email exists (prevents enumeration).
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if email:
            try:
                user = User.objects.get(email=email, is_active=True, is_activated=True)
                token_obj = PasswordResetToken.create_for_user(user)
                send_password_reset_email(user, token_obj)
            except User.DoesNotExist:
                pass   # silent — do not reveal whether email exists
        return Response({'detail': 'If an eligible account exists for this email, a password reset link has been sent.'})


class PasswordResetConfirmView(APIView):
    """
    POST auth/password-reset/confirm/
    Body: { token, new_password, confirm_password }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        token_str        = request.data.get('token', '').strip()
        new_password     = request.data.get('new_password', '')
        confirm_password = request.data.get('confirm_password', '')

        if not token_str:
            return Response({'error': 'Token is required.'}, status=400)

        if not new_password or len(new_password) < 8:
            return Response({'error': 'Password must be at least 8 characters.'}, status=400)

        if new_password != confirm_password:
            return Response({'error': 'Passwords do not match.'}, status=400)

        # Lock the user first to serialize concurrent reset requests across
        # tokens for the same user; then lock the token and check again inside
        # the transaction. PostgreSQL/MySQL row locks enforce single use.
        with transaction.atomic():
            try:
                token_owner_id = PasswordResetToken.objects.filter(token=token_str).values_list(
                    'user_id', flat=True
                ).get()
            except PasswordResetToken.DoesNotExist:
                return Response({'error': 'Invalid or expired reset link.'}, status=400)

            user = User.objects.select_for_update().get(pk=token_owner_id)
            token_obj = PasswordResetToken.objects.select_for_update().get(token=token_str)
            if not token_obj.is_valid:
                return Response({'error': 'This reset link has expired or already been used.'}, status=400)

            problems = password_errors(new_password, user)
            if problems:
                return Response({'error': ' '.join(problems)}, status=400)
            user.set_password(new_password)
            user.must_change_password = False
            user.save(update_fields=['password', 'must_change_password'])
            token_obj.used = True
            token_obj.save(update_fields=['used'])

        return Response({'detail': 'Password updated. You can now log in.'})


class PasswordResetTokenCheckView(APIView):
    """
    GET auth/password-reset/check/?token=<token>
    Front-end calls this on mount of /reset-password page to validate the token.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        token_str = request.query_params.get('token', '').strip()
        try:
            token_obj = PasswordResetToken.objects.get(token=token_str)
            if token_obj.is_valid:
                return Response({'valid': True})
            return Response({'valid': False, 'reason': 'expired_or_used'}, status=400)
        except PasswordResetToken.DoesNotExist:
            return Response({'valid': False, 'reason': 'not_found'}, status=400)


# ── Logged-in user: change own password ──────────────────────────────────────

class ChangePasswordView(APIView):
    """
    POST auth/change-password/
    Body: { current_password, new_password, confirm_password }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current_password = request.data.get('current_password', '')
        new_password     = request.data.get('new_password', '')
        confirm_password = request.data.get('confirm_password', '')

        if not current_password:
            return Response({'error': 'Current password is required.'}, status=400)

        if not new_password or len(new_password) < 8:
            return Response({'error': 'New password must be at least 8 characters.'}, status=400)

        if new_password != confirm_password:
            return Response({'error': 'Passwords do not match.'}, status=400)

        if not request.user.check_password(current_password):
            return Response({'error': 'Current password is incorrect.'}, status=400)

        if current_password == new_password:
            return Response({'error': 'New password must differ from the current password.'}, status=400)

        problems = password_errors(new_password, request.user)
        if problems:
            return Response({'error': ' '.join(problems)}, status=400)

        request.user.set_password(new_password)
        request.user.must_change_password = False
        request.user.save()

        # Re-login to refresh the session (set_password invalidates it)
        user = authenticate(request, username=request.user.email, password=new_password)
        if user:
            login(request, user)

        return Response({'detail': 'Password changed successfully.'})


# ── Admin: set temporary password for an employee ────────────────────────────

class AdminSetPasswordView(APIView):
    """
    POST auth/admin-set-password/
    Body: { user_public_id, new_password }
    Requires accounts.manage_users (superusers always allowed).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _can_manage_users(request.user):
            return Response({'error': 'Forbidden'}, status=403)

        user_public_id = request.data.get('user_public_id')
        new_password   = request.data.get('new_password', '')

        if not user_public_id:
            return Response({'error': 'user_public_id is required.'}, status=400)

        if not new_password or len(new_password) < 8:
            return Response({'error': 'Password must be at least 8 characters.'}, status=400)

        target_user = _get_manageable_user(request.user, user_public_id)
        if target_user is None:
            return Response({'error': 'User not found.'}, status=404)

        problems = password_errors(new_password, target_user)
        if problems:
            return Response({'error': ' '.join(problems)}, status=400)

        target_user.set_password(new_password)
        target_user.must_change_password = True   # force change on next login
        target_user.save()

        return Response({
            'detail': f'Temporary password set for {target_user.email}. '
                      f'They will be required to change it on next login.'
        })


# ── Admin: assign role to a user ──────────────────────────────────────────────

class AssignRoleView(APIView):
    """
    POST auth/assign-role/
    Backward compatible bodies:
      { user_public_id, role }                       -> replace all groups with one role
      { user_public_id, roles: [..], action: replace } -> replace all groups
      { user_public_id, roles: [..], action: add }     -> add groups
      { user_public_id, roles: [..], action: remove }  -> remove groups

    Roles are Django Groups. Users can hold multiple group-based roles.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _can_manage_users(request.user):
            return Response({'error': 'Forbidden'}, status=403)

        user_public_id = request.data.get('user_public_id')
        action = request.data.get('action', 'replace')

        role_codes = request.data.get('roles')
        if role_codes is None:
            role = request.data.get('role', '')
            role_codes = [role] if role else []
        if isinstance(role_codes, str):
            role_codes = [role_codes]
        if not isinstance(role_codes, (list, tuple)) or not all(
            isinstance(code, str) for code in role_codes
        ):
            return Response({'error': 'roles must be a list of role names.'}, status=400)
        role_codes = [code.strip() for code in role_codes if code.strip()]

        if not user_public_id or not role_codes:
            return Response({'error': 'user_public_id and role/roles are required.'}, status=400)

        if action not in {'replace', 'add', 'remove'}:
            return Response({'error': "action must be 'replace', 'add', or 'remove'."}, status=400)

        target_user = _get_manageable_user(request.user, user_public_id)
        if target_user is None:
            return Response({'error': 'User not found.'}, status=404)

        groups = list(Group.objects.filter(name__in=role_codes))
        found_codes = {group.name for group in groups}
        missing = sorted(set(role_codes) - found_codes)
        if missing:
            return Response({'error': f'Unknown groups/roles: {missing}. Create them in Django admin or use the Role Setup Wizard.'}, status=400)

        if any(code.lower() in {'admin', 'administrator'} for code in found_codes) and not request.user.is_superuser:
            return Response({'error': 'Only superusers can assign or remove the Administrator group.'}, status=403)

        if not request.user.is_superuser:
            # Managers may assign only the low-privilege roles the project explicitly lists in
            # ACCOUNTS_FRAMEWORK["MANAGER_ASSIGNABLE_ROLES"] (none by default). Do not trust
            # other groups: they can contain administrative permissions.
            allowed_groups = {str(name) for name in accounts_setting("MANAGER_ASSIGNABLE_ROLES", ())}
            if not found_codes.issubset(allowed_groups):
                return Response({'error': 'Only superusers may assign privileged or custom roles.'}, status=403)
            if target_user.groups.exclude(name__in=allowed_groups).exists() or target_user.is_staff:
                return Response({'error': 'Only superusers may change privileged users.'}, status=403)

        if action == 'replace':
            if target_user.groups.filter(name__iexact='administrator').exists() and not request.user.is_superuser:
                return Response({'error': 'Only superusers can replace groups for an Administrator.'}, status=403)
            target_user.groups.set(groups)
        elif action == 'add':
            target_user.groups.add(*groups)
        elif action == 'remove':
            target_user.groups.remove(*groups)

        return Response({
            'detail': f"Roles for {target_user.email} updated.",
            'user': UserSerializer(target_user).data,
        })


class RoleListView(APIView):
    """GET auth/roles/ — list Django Groups used as roles for assignment UIs."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_manage_users(request.user):
            return Response({'error': 'Forbidden'}, status=403)
        groups = Group.objects.all().order_by('name').prefetch_related('permissions__content_type')
        return Response({
            'roles': [
                {
                    'code': group.name,
                    'name': group.name.replace('-', ' ').replace('_', ' ').title(),
                    'description': 'Django Group role',
                    'permissions': sorted(
                        f"{perm.content_type.app_label}.{perm.codename}"
                        for perm in group.permissions.all()
                    ),
                }
                for group in groups
            ]
        })


class GroupsPermissionsAdminView(APIView):
    """
    GET auth/admin/groups-permissions/

    Superuser-only API for inspecting Django Groups and Permissions.

    Query modes:
      - no query params: return all groups with their permissions and all permissions
      - ?group=<exact_group_name>: return one group and its permissions
      - ?permission=<app_label.codename>: return one permission and all groups containing it
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _is_superuser(request.user):
            return Response({"error": "Superuser permission is required."}, status=403)

        group_query = request.query_params.get("group", "").strip()
        permission_query = request.query_params.get("permission", "").strip()

        if group_query and permission_query:
            return Response(
                {"error": "Use either the 'group' parameter or the 'permission' parameter, not both."},
                status=400,
            )

        if group_query:
            group = _get_group_by_query(group_query)
            if not group:
                return Response({"error": "Group not found."}, status=404)
            group = Group.objects.prefetch_related("permissions__content_type").get(pk=group.pk)
            return Response({
                "mode": "group",
                "group": _group_to_dict(group, include_permissions=True),
            })

        if permission_query:
            permission = _get_permission_by_query(permission_query)
            if not permission:
                return Response({"error": "Permission not found."}, status=404)
            permission = Permission.objects.select_related("content_type").prefetch_related("group_set").get(pk=permission.pk)
            return Response({
                "mode": "permission",
                "permission": _permission_to_dict(permission, include_groups=True),
            })

        groups = Group.objects.all().order_by("name").prefetch_related("permissions__content_type")
        permissions = Permission.objects.select_related("content_type").all().order_by(
            "content_type__app_label", "codename"
        )

        return Response({
            "mode": "overview",
            "groups": [_group_to_dict(group, include_permissions=True) for group in groups],
            "permissions": [_permission_to_dict(permission, include_groups=False) for permission in permissions],
            "group_count": groups.count(),
            "permission_count": permissions.count(),
        })


# ── Admin: activate / deactivate a user account ──────────────────────────────

class SetUserActiveView(APIView):
    """
    POST auth/set-active/
    Body: { user_public_id, is_active }   (is_active must be a JSON boolean: true | false)
    Requires accounts.manage_users (superusers always allowed).
    When activating a previously-deactivated user, must_change_password is set to True.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not _can_manage_users(request.user):
            return Response({'error': 'Forbidden'}, status=403)

        user_public_id = request.data.get('user_public_id')
        is_active      = request.data.get('is_active')

        if user_public_id is None or is_active is None:
            return Response({'error': 'user_public_id and is_active are required.'}, status=400)
        if not isinstance(is_active, bool):
            return Response({'error': 'is_active must be a boolean.'}, status=400)

        target_user = _get_manageable_user(request.user, user_public_id)
        if target_user is None:
            return Response({'error': 'User not found.'}, status=404)

        # Prevent admins from deactivating themselves
        if target_user == request.user:
            return Response({'error': 'You cannot change the active status of your own account.'}, status=400)

        previously_active = target_user.is_active
        target_user.is_active = is_active

        if is_active and not previously_active:
            # Re-activating a deactivated account → force password change
            target_user.must_change_password = True

        target_user.save()

        action = 'activated' if target_user.is_active else 'deactivated'
        return Response({
            'detail': f"Account for {target_user.email} has been {action}.",
            'user': UserSerializer(target_user).data,
        })


# ── Admin: list employees ─────────────────────────────────────────────────────

class EmployeeListView(APIView):
    """GET auth/employees/ — requires accounts.manage_users (superusers see everyone)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_manage_users(request.user):
            return Response({'error': 'Forbidden'}, status=403)
        employees = _manageable_users_for(request.user).order_by('email')
        return Response(UserSerializer(employees, many=True).data)


class PermissionListView(APIView):
    """Return all Django permissions and the current user's permissions.

    Permissions are Django's own: they are created from each app's model
    Meta.permissions and the built-in model permissions during migrations.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from accounts.services.permission_service import get_user_permission_codes

        permissions = Permission.objects.select_related("content_type").all().order_by(
            "content_type__app_label", "codename"
        )
        return Response({
            "permissions": [
                {
                    "code": _permission_code(permission),
                    "label": permission.name,
                    "app_label": permission.content_type.app_label,
                    "model": permission.content_type.model,
                    "codename": permission.codename,
                }
                for permission in permissions
            ],
            "user_permissions": sorted(get_user_permission_codes(request.user)),
        })
