"""Envío de correos del módulo de cuentas (texto plano, plantillas en templates/accounts/email/)."""

import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.mail import send_mail
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse

from accounts.tokens import make_email_token

logger = logging.getLogger(__name__)


def _send(template, to, context):
    subject = render_to_string(f"accounts/email/{template}_subject.txt", context).strip()
    body = render_to_string(f"accounts/email/{template}.txt", context)
    try:
        send_mail(subject, body, None, to)
    except Exception:
        # Un fallo de SMTP no debe romper el flujo ni revelar información al usuario.
        logger.exception("No se pudo enviar el correo '%s'", template)


def send_email_confirmation(request, user):
    url = request.build_absolute_uri(reverse("accounts:confirm_email", args=[make_email_token(user)]))
    _send("confirm_email", [user.email], {"user": user, "url": url})


def send_already_registered(request, email):
    """Aviso a quien ya tiene cuenta (evita revelar en pantalla qué correos existen)."""
    url = request.build_absolute_uri(reverse("accounts:password_reset"))
    _send("already_registered", [email], {"url": url})


def notify_admins_pending(request, user):
    User = get_user_model()
    perm = Permission.objects.get(codename="manage_users", content_type__app_label="accounts")
    admins = (
        User.objects.filter(status=User.Status.ACTIVE)
        .filter(Q(is_superuser=True) | Q(groups__permissions=perm) | Q(user_permissions=perm))
        .distinct()
    )
    to = [admin.email for admin in admins]
    if to:
        url = request.build_absolute_uri(reverse("management:user_edit", args=[user.pk]))
        _send("pending_approval", to, {"user": user, "url": url})


def send_review_result(request, user):
    url = request.build_absolute_uri(reverse("accounts:login"))
    _send("review_result", [user.email], {"user": user, "url": url})
