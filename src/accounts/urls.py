from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("ingresar/", views.LoginView.as_view(), name="login"),
    path("ingresar/verificar/", views.login_otp, name="login_otp"),
    path("salir/", views.LogoutView.as_view(), name="logout"),
    path("registro/", views.signup, name="signup"),
    path("registro/enviado/", views.signup_done, name="signup_done"),
    path("registro/confirmar/<str:token>/", views.confirm_email, name="confirm_email"),
    path("perfil/", views.profile, name="profile"),
    path("perfil/clave/", views.PasswordChangeView.as_view(), name="password_change"),
    path("2fa/", views.otp_setup, name="otp_setup"),
    path("2fa/codigos/", views.otp_recovery_codes, name="otp_recovery_codes"),
    path("2fa/desactivar/", views.otp_disable, name="otp_disable"),
    path("recuperar/", views.PasswordResetView.as_view(), name="password_reset"),
    path("recuperar/enviado/", views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("recuperar/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("recuperar/listo/", views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
]
