import time

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from django_otp import login as otp_login
from django_otp.plugins.otp_static.models import StaticDevice

from accounts import emails, otp
from accounts.forms import LoginForm, OTPTokenForm, PasswordConfirmForm, ProfileForm, SignupForm
from accounts.tokens import read_email_token

User = get_user_model()

PENDING_2FA = "accounts_pending_2fa"
PENDING_2FA_TTL = 300  # segundos para ingresar el código
PENDING_2FA_MAX_ATTEMPTS = 5


# --- Inicio de sesión -------------------------------------------------------


class LoginView(auth_views.LoginView):
    """Paso 1: correo + contraseña. Si el usuario tiene 2FA, pasa al paso 2."""

    form_class = LoginForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        if otp.has_2fa(user):
            # Aún no se inicia sesión: se guarda el usuario pendiente de verificar.
            self.request.session.cycle_key()
            self.request.session[PENDING_2FA] = {
                "uid": user.pk,
                "backend": user.backend,
                "ts": time.time(),
                "next": self.get_success_url(),
                "attempts": 0,
            }
            return redirect("accounts:login_otp")
        return super().form_valid(form)


@never_cache
@sensitive_post_parameters("token")
@require_http_methods(["GET", "POST"])
def login_otp(request):
    """Paso 2: código TOTP o de recuperación."""
    pending = request.session.get(PENDING_2FA)
    if not pending or time.time() - pending["ts"] > PENDING_2FA_TTL:
        request.session.pop(PENDING_2FA, None)
        messages.error(request, "La verificación expiró. Inicia sesión nuevamente.")
        return redirect("accounts:login")

    user = User.objects.filter(pk=pending["uid"], status=User.Status.ACTIVE).first()
    if user is None:
        request.session.pop(PENDING_2FA, None)
        return redirect("accounts:login")

    form = OTPTokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        device = otp.verify(user, form.cleaned_data["token"])
        if device:
            request.session.pop(PENDING_2FA)
            user.backend = pending["backend"]
            login(request, user)
            otp_login(request, device)
            if isinstance(device, StaticDevice):
                left = otp.remaining_recovery_codes(user)
                messages.warning(request, f"Usaste un código de recuperación. Te quedan {left}.")
            return redirect(pending["next"])

        pending["attempts"] += 1
        request.session[PENDING_2FA] = pending
        if pending["attempts"] >= PENDING_2FA_MAX_ATTEMPTS:
            request.session.pop(PENDING_2FA)
            messages.error(request, "Demasiados intentos. Inicia sesión nuevamente.")
            return redirect("accounts:login")
        form.add_error("token", "Código incorrecto.")

    return render(request, "accounts/login_otp.html", {"form": form})


class LogoutView(auth_views.LogoutView):
    template_name = "accounts/logged_out.html"


# --- Registro ---------------------------------------------------------------


@never_cache
@sensitive_post_parameters("password1", "password2")
@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("home")

    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        existing = User.objects.filter(email__iexact=email).first()
        if existing is None:
            user = form.save()
            emails.send_email_confirmation(request, user)
        elif existing.status == User.Status.EMAIL_PENDING:
            emails.send_email_confirmation(request, existing)
        else:
            emails.send_already_registered(request, email)
        # Misma respuesta en todos los casos: no revela qué correos existen.
        return redirect("accounts:signup_done")

    return render(request, "accounts/signup.html", {"form": form})


def signup_done(request):
    return render(request, "accounts/signup_done.html")


@never_cache
@require_http_methods(["GET", "POST"])
def confirm_email(request, token):
    """GET muestra un botón; POST confirma (evita que escáneres de enlaces confirmen solos)."""
    data = read_email_token(token)
    user = User.objects.filter(pk=data[0], email=data[1]).first() if data else None
    if user is None:
        return render(request, "accounts/confirm_email.html", {"invalid": True}, status=400)

    if request.method == "POST":
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user.pk)
            confirmed_now = user.status == User.Status.EMAIL_PENDING
            if confirmed_now:
                user.status = User.Status.APPROVAL_PENDING
                user.save(update_fields=["status", "is_active"])
        if confirmed_now:
            emails.notify_admins_pending(request, user)
        return render(request, "accounts/confirm_email.html", {"done": True})

    return render(request, "accounts/confirm_email.html", {"token": token})


# --- Perfil -----------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Perfil actualizado.")
        return redirect("accounts:profile")
    context = {
        "form": form,
        "has_2fa": otp.has_2fa(request.user),
        "recovery_left": otp.remaining_recovery_codes(request.user),
    }
    return render(request, "accounts/profile.html", context)


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def form_valid(self, form):
        messages.success(self.request, "Contraseña actualizada.")
        return super().form_valid(form)


# --- 2FA --------------------------------------------------------------------


@login_required
@never_cache
@sensitive_post_parameters("token")
@require_http_methods(["GET", "POST"])
def otp_setup(request):
    user = request.user
    if otp.has_2fa(user):
        return render(request, "accounts/otp_status.html", {"recovery_left": otp.remaining_recovery_codes(user)})

    device = otp.pending_totp_device(user)
    form = OTPTokenForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if device.verify_token(form.cleaned_data["token"]):
            device.confirmed = True
            device.save()
            codes = otp.new_recovery_codes(user)
            otp_login(request, device)
            messages.success(request, "Verificación en dos pasos activada.")
            return render(request, "accounts/otp_recovery_codes.html", {"codes": codes})
        form.add_error("token", "Código incorrecto. Revisa que la hora de tu teléfono sea correcta.")

    return render(
        request,
        "accounts/otp_setup.html",
        {"form": form, "qr_svg": otp.qr_svg(device.config_url), "secret": otp.totp_secret(device)},
    )


@login_required
@never_cache
@sensitive_post_parameters("password")
@require_http_methods(["GET", "POST"])
def otp_recovery_codes(request):
    if not otp.has_2fa(request.user):
        return redirect("accounts:otp_setup")
    form = PasswordConfirmForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        codes = otp.new_recovery_codes(request.user)
        return render(request, "accounts/otp_recovery_codes.html", {"codes": codes})
    return render(request, "accounts/password_confirm.html", {"form": form, "action": "Generar nuevos códigos"})


@login_required
@never_cache
@sensitive_post_parameters("password")
@require_http_methods(["GET", "POST"])
def otp_disable(request):
    if request.user.is_administrator:
        messages.error(request, "Los administradores no pueden desactivar la verificación en dos pasos.")
        return redirect("accounts:otp_setup")
    form = PasswordConfirmForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        otp.remove_2fa(request.user)
        messages.success(request, "Verificación en dos pasos desactivada.")
        return redirect("accounts:profile")
    return render(request, "accounts/password_confirm.html", {"form": form, "action": "Desactivar 2FA", "danger": True})


# --- Recuperación de contraseña --------------------------------------------


class PasswordResetView(auth_views.PasswordResetView):
    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/email/password_reset.txt"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"
