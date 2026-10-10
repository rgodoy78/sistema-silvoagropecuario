import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts import otp
from accounts.apps import ADMIN_ROLE
from accounts.tokens import make_email_token
from accounts.validators import validate_rut

User = get_user_model()
PASSWORD = "una-clave-larga-segura"


def current_code(device):
    return f"{totp(device.bin_key, device.step, device.t0, device.digits, device.drift):06d}"


def make_user(email="ana@example.com", status=User.Status.ACTIVE, **extra):
    return User.objects.create_user(
        email=email, password=PASSWORD, first_name="Ana", last_name="Pérez", status=status, **extra
    )


def enable_2fa(user):
    device = TOTPDevice.objects.create(user=user, name="t", confirmed=True)
    otp.new_recovery_codes(user)
    return device


@override_settings(
    ALLOWED_HOSTS=["testserver"],
    SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    AXES_ENABLED=False,
)
class BaseTestCase(TestCase):
    pass


class UserModelTests(BaseTestCase):
    def test_email_is_login_and_lowercased(self):
        user = make_user(email="Ana@Example.COM")
        self.assertEqual(user.email, "ana@example.com")
        self.assertEqual(User.USERNAME_FIELD, "email")

    def test_password_is_hashed_with_argon2(self):
        self.assertTrue(make_user().password.startswith("argon2"))

    def test_is_active_follows_status(self):
        self.assertFalse(make_user(status=User.Status.APPROVAL_PENDING).is_active)
        self.assertTrue(make_user(email="b@example.com").is_active)

    def test_rut_validation(self):
        validate_rut("11.111.111-1")
        validate_rut("76.086.428-5")
        with self.assertRaises(ValidationError):
            validate_rut("11.111.111-2")

    def test_admin_role_created_with_permission(self):
        role = Group.objects.get(name=ADMIN_ROLE)
        self.assertTrue(role.permissions.filter(codename="manage_users").exists())


class SignupFlowTests(BaseTestCase):
    def signup(self, email="nuevo@example.com"):
        return self.client.post(
            reverse("accounts:signup"),
            {"email": email, "first_name": "Nuevo", "last_name": "Usuario", "rut": "", "phone": "", "position": "",
             "password1": PASSWORD, "password2": PASSWORD},
        )

    def test_full_signup_confirm_and_approval(self):
        admin = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)

        response = self.signup()
        self.assertRedirects(response, reverse("accounts:signup_done"))
        user = User.objects.get(email="nuevo@example.com")
        self.assertEqual(user.status, User.Status.EMAIL_PENDING)
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"https?://\S+", mail.outbox[0].body).group(0)

        # GET no confirma (protección contra escáneres de enlaces); POST sí.
        self.client.get(link)
        user.refresh_from_db()
        self.assertEqual(user.status, User.Status.EMAIL_PENDING)
        self.client.post(link)
        user.refresh_from_db()
        self.assertEqual(user.status, User.Status.APPROVAL_PENDING)
        self.assertIn(admin.email, mail.outbox[-1].to)

        # Pendiente de aprobación: no puede ingresar.
        self.assertFalse(self.client.login(username=user.email, password=PASSWORD))

        # Un administrador (con 2FA) aprueba.
        device = enable_2fa(admin)
        self.client.post(reverse("accounts:login"), {"username": admin.email, "password": PASSWORD})
        self.client.post(reverse("accounts:login_otp"), {"token": current_code(device)})
        self.client.post(reverse("management:user_action", args=[user.pk]), {"accion": "aprobar"})
        user.refresh_from_db()
        self.assertEqual(user.status, User.Status.ACTIVE)
        self.assertEqual(user.reviewed_by, admin)
        self.assertIn("aprobada", mail.outbox[-1].body)

    def test_signup_does_not_reveal_existing_email(self):
        make_user(email="existe@example.com")
        response = self.signup(email="existe@example.com")
        self.assertRedirects(response, reverse("accounts:signup_done"))
        self.assertEqual(User.objects.filter(email="existe@example.com").count(), 1)
        self.assertIn("ya tienes una cuenta", mail.outbox[0].body)

    def test_invalid_token_rejected(self):
        response = self.client.post(reverse("accounts:confirm_email", args=["manipulado"]))
        self.assertEqual(response.status_code, 400)

    def test_token_for_old_email_rejected(self):
        user = make_user(status=User.Status.EMAIL_PENDING)
        token = make_email_token(user)
        user.email = "otro@example.com"
        user.save()
        self.assertEqual(self.client.post(reverse("accounts:confirm_email", args=[token])).status_code, 400)


class LoginTwoFactorTests(BaseTestCase):
    def login(self, user):
        return self.client.post(reverse("accounts:login"), {"username": user.email, "password": PASSWORD})

    def test_login_without_2fa(self):
        user = make_user()
        self.assertRedirects(self.login(user), reverse("home"))

    def test_login_with_2fa_requires_code(self):
        user = make_user()
        device = enable_2fa(user)
        self.assertRedirects(self.login(user), reverse("accounts:login_otp"))
        # Aún no hay sesión iniciada.
        self.assertRedirects(self.client.get(reverse("home")), f"{reverse('accounts:login')}?next=/")

        response = self.client.post(reverse("accounts:login_otp"), {"token": "000000"})
        self.assertContains(response, "Código incorrecto")

        device.refresh_from_db()
        device.throttling_failure_count = 0
        device.throttling_failure_timestamp = None
        device.save()
        response = self.client.post(reverse("accounts:login_otp"), {"token": current_code(device)})
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_recovery_code_works_once(self):
        user = make_user()
        TOTPDevice.objects.create(user=user, name="t", confirmed=True)
        code = otp.new_recovery_codes(user)[0]
        self.login(user)
        self.assertRedirects(self.client.post(reverse("accounts:login_otp"), {"token": code}), reverse("home"))
        self.client.post(reverse("accounts:logout"))
        self.login(user)
        self.assertContains(self.client.post(reverse("accounts:login_otp"), {"token": code}), "Código incorrecto")

    def test_too_many_otp_attempts_restart_login(self):
        user = make_user()
        enable_2fa(user)
        self.login(user)
        for _ in range(5):
            response = self.client.post(reverse("accounts:login_otp"), {"token": "000000"})
        self.assertRedirects(response, reverse("accounts:login"))

    def test_admin_without_2fa_forced_to_setup(self):
        admin = User.objects.create_superuser(email="admin@example.com", password=PASSWORD)
        self.login(admin)
        self.assertRedirects(self.client.get(reverse("management:user_list")), reverse("accounts:otp_setup"))
        self.assertRedirects(self.client.get(reverse("home")), reverse("accounts:otp_setup"))

    def test_otp_setup_flow(self):
        user = make_user()
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:otp_setup"))
        self.assertContains(response, "<svg")
        device = TOTPDevice.objects.get(user=user, confirmed=False)
        response = self.client.post(reverse("accounts:otp_setup"), {"token": current_code(device)})
        self.assertContains(response, "Códigos de recuperación")
        self.assertTrue(otp.has_2fa(user))
        self.assertEqual(otp.remaining_recovery_codes(user), otp.RECOVERY_CODES)

    def test_admin_cannot_disable_2fa(self):
        role = Group.objects.get(name=ADMIN_ROLE)
        user = make_user()
        user.groups.add(role)
        device = enable_2fa(user)
        self.login(user)
        self.client.post(reverse("accounts:login_otp"), {"token": current_code(device)})
        self.client.post(reverse("accounts:otp_disable"), {"password": PASSWORD})
        self.assertTrue(otp.has_2fa(user))


class ManagementPermissionTests(BaseTestCase):
    def test_regular_user_forbidden(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(reverse("management:user_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("management:role_list")).status_code, 403)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("management:user_list"))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('management:user_list')}")

    def _verified_admin(self):
        admin = make_user(email="admin@example.com")
        admin.groups.add(Group.objects.get(name=ADMIN_ROLE))
        device = enable_2fa(admin)
        self.client.post(reverse("accounts:login"), {"username": admin.email, "password": PASSWORD})
        self.client.post(reverse("accounts:login_otp"), {"token": current_code(device)})
        return admin

    def test_admin_can_list_and_create_role(self):
        self._verified_admin()
        self.assertEqual(self.client.get(reverse("management:user_list")).status_code, 200)
        perm = Permission.objects.get(codename="manage_users")
        self.client.post(reverse("management:role_create"), {"name": "Contador", "permissions": []})
        self.assertTrue(Group.objects.filter(name="Contador").exists())
        self.assertNotIn(perm, Group.objects.get(name="Contador").permissions.all())

    def test_admin_role_cannot_be_deleted(self):
        self._verified_admin()
        role = Group.objects.get(name=ADMIN_ROLE)
        self.client.post(reverse("management:role_delete", args=[role.pk]))
        self.assertTrue(Group.objects.filter(name=ADMIN_ROLE).exists())

    def test_admin_cannot_edit_superuser(self):
        self._verified_admin()
        root = User.objects.create_superuser(email="root@example.com", password=PASSWORD)
        self.assertEqual(self.client.get(reverse("management:user_edit", args=[root.pk])).status_code, 403)

    def test_admin_cannot_change_own_status(self):
        admin = self._verified_admin()
        self.client.post(reverse("management:user_action", args=[admin.pk]), {"accion": "deshabilitar"})
        admin.refresh_from_db()
        self.assertEqual(admin.status, User.Status.ACTIVE)

    def test_disabled_user_session_ends(self):
        self._verified_admin()
        other = make_user(email="otro@example.com")
        other_client = self.client_class()
        other_client.force_login(other)
        self.client.post(reverse("management:user_action", args=[other.pk]), {"accion": "deshabilitar"})
        self.assertEqual(other_client.get(reverse("home")).status_code, 302)


class PasswordResetTests(BaseTestCase):
    def test_reset_sends_email_only_for_active(self):
        make_user()
        make_user(email="pend@example.com", status=User.Status.APPROVAL_PENDING)
        self.client.post(reverse("accounts:password_reset"), {"email": "ana@example.com"})
        self.client.post(reverse("accounts:password_reset"), {"email": "pend@example.com"})
        self.client.post(reverse("accounts:password_reset"), {"email": "nadie@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/cuentas/recuperar/", mail.outbox[0].body)
