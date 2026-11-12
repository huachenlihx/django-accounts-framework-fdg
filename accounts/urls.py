from django.urls import path
from . import views

urlpatterns = [
    path("permissions/", views.PermissionListView.as_view(), name="account-permissions"),
    # ── CSRF ──────────────────────────────────────────────────────────────
    path('auth/csrf/', views.CsrfView.as_view(), name="accounts-csrf"),

    # ── Session auth ──────────────────────────────────────────────────────
    path('auth/login/', views.LoginView.as_view(), name="accounts-login"),
    path('auth/logout/', views.LogoutView.as_view(), name="accounts-logout"),
    path('auth/me/', views.MeView.as_view(), name="accounts-me"),

    # ── Self-registration & activation ────────────────────────────────────
    path('auth/register/', views.RegisterView.as_view(), name="accounts-register"),
    path('auth/activate/', views.ActivateAccountView.as_view(), name="accounts-activate"),
    path('auth/activate/resend/', views.ResendActivationView.as_view(), name="accounts-activate-resend"),

    # ── Password management ───────────────────────────────────────────────
    path('auth/change-password/', views.ChangePasswordView.as_view(), name="accounts-change-password"),
    path('auth/password-reset/request/', views.PasswordResetRequestView.as_view(), name="accounts-password-reset-request"),
    path('auth/password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name="accounts-password-reset-confirm"),
    path('auth/password-reset/check/', views.PasswordResetTokenCheckView.as_view(), name="accounts-password-reset-check"),

    # ── Admin / privileged operations ─────────────────────────────────────
    path('auth/admin-set-password/', views.AdminSetPasswordView.as_view(), name="accounts-admin-set-password"),
    path('auth/assign-role/', views.AssignRoleView.as_view(), name="accounts-assign-role"),
    path('auth/roles/', views.RoleListView.as_view(), name="accounts-roles"),
    path('auth/admin/groups-permissions/', views.GroupsPermissionsAdminView.as_view(), name="accounts-groups-permissions"),
    path('auth/set-active/', views.SetUserActiveView.as_view(), name="accounts-set-active"),
    path('auth/employees/', views.EmployeeListView.as_view(), name="accounts-employees"),
]
