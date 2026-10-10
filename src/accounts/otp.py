"""Utilidades de 2FA (TOTP + códigos de recuperación) sobre django-otp."""

import base64

import qrcode
import qrcode.image.svg
from django_otp import match_token
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

RECOVERY_CODES = 10


def has_2fa(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def pending_totp_device(user):
    """Dispositivo TOTP sin confirmar para el proceso de configuración."""
    device = TOTPDevice.objects.filter(user=user, confirmed=False).first()
    return device or TOTPDevice.objects.create(user=user, name="Autenticador", confirmed=False)


def totp_secret(device):
    return base64.b32encode(device.bin_key).decode()


def qr_svg(data):
    image = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    return image.to_string(encoding="unicode")


def new_recovery_codes(user):
    """Reemplaza los códigos de recuperación y devuelve los nuevos (se muestran una sola vez)."""
    device, _ = StaticDevice.objects.get_or_create(user=user, name="Recuperación", defaults={"confirmed": True})
    device.token_set.all().delete()
    codes = [StaticToken.random_token() for _ in range(RECOVERY_CODES)]
    StaticToken.objects.bulk_create(StaticToken(device=device, token=code) for code in codes)
    return codes


def remaining_recovery_codes(user):
    return StaticToken.objects.filter(device__user=user, device__confirmed=True).count()


def verify(user, token):
    """Valida un código TOTP o de recuperación. Incluye limitación de intentos de django-otp."""
    return match_token(user, token)


def remove_2fa(user):
    TOTPDevice.objects.filter(user=user).delete()
    StaticDevice.objects.filter(user=user).delete()
