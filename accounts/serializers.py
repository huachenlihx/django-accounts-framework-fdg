from rest_framework import serializers
from .models import User
from .services.permission_service import get_user_permission_codes


class UserSerializer(serializers.ModelSerializer):
    permissions = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()

    def get_permissions(self, obj):
        return sorted(get_user_permission_codes(obj))

    def get_roles(self, obj):
        return sorted(obj.groups.values_list('name', flat=True))

    class Meta:
        model  = User
        fields = [
            'public_id', 'email', 'first_name', 'last_name',
            'roles', 'department', 'employee_id', 'preferred_locale',
            'is_active', 'is_activated', 'permissions', 'must_change_password',
        ]
        # username is internal and auto-populated from email by UserManager.


SUPPORTED_LOCALES = ('en', 'fr', 'de', 'zh-Hans-CN')


class PreferredLocaleUpdateSerializer(serializers.Serializer):
    preferred_locale = serializers.ChoiceField(choices=SUPPORTED_LOCALES)



class UserCreateSerializer(serializers.ModelSerializer):
    """Used by admin when creating a new user account."""
    password = serializers.CharField(write_only=True, min_length=8)
    # The manager is referenced by public_id, never by database id.
    manager = serializers.SlugRelatedField(
        slug_field='public_id', queryset=User.objects.all(), required=False, allow_null=True,
    )

    class Meta:
        model  = User
        fields = [
            'email', 'first_name', 'last_name',
            'department', 'employee_id',
            'manager', 'preferred_locale', 'password',
        ]

    def validate_email(self, value):
        return value.strip().lower()

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User.objects.create_user(
            password=password,
            is_activated=True,      # admin-created accounts are pre-activated
            is_active=True,
            **validated_data,
        )
        # Do not assign any default role/group here.
        # Roles are Django Groups and should be assigned explicitly
        # by an administrator or another authorized workflow.
        return user


class RegisterSerializer(serializers.Serializer):
    """Used for self-registration (email + password only)."""
    email            = serializers.EmailField()
    password         = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)
    first_name       = serializers.CharField(max_length=150, default='', allow_blank=True)
    last_name        = serializers.CharField(max_length=150, default='', allow_blank=True)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def validate(self, data):
        if data['password'] != data['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        return data
