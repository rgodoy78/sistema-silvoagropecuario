from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


class Require2FAForAdminsMiddleware:
    """Obliga a los administradores a usar 2FA.

    Un administrador sin sesión verificada con 2FA solo puede acceder a la
    configuración de 2FA y a cerrar sesión. Va después de OTPMiddleware.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and user.is_administrator and not user.is_verified():
            allowed = {reverse("accounts:otp_setup"), reverse("accounts:logout")}
            if request.path not in allowed:
                messages.warning(request, "Como administrador debes configurar la verificación en dos pasos (2FA).")
                return redirect("accounts:otp_setup")
        return self.get_response(request)
