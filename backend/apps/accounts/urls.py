from django.urls import path

from . import views

urlpatterns = [
    path("auth/csrf", views.CsrfView.as_view(), name="auth-csrf"),
    path("auth/me", views.MeView.as_view(), name="auth-me"),
    path("auth/signup", views.SignupView.as_view(), name="auth-signup"),
    path("auth/login", views.LoginView.as_view(), name="auth-login"),
    path("auth/account", views.AccountView.as_view(), name="auth-account"),
    path("auth/password-change", views.PasswordChangeView.as_view(), name="auth-password-change"),
    path("auth/logout", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/verify-email", views.VerifyEmailView.as_view(), name="auth-verify-email"),
    path(
        "auth/resend-verification",
        views.ResendVerificationView.as_view(),
        name="auth-resend-verification",
    ),
    path("auth/password-reset", views.PasswordResetView.as_view(), name="auth-password-reset"),
    path("auth/password-set", views.PasswordSetView.as_view(), name="auth-password-set"),
    path("staff", views.StaffListView.as_view(), name="staff-list"),
    path("staff/<uuid:pk>", views.StaffDetailView.as_view(), name="staff-detail"),
]
