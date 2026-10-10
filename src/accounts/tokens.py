from django.core import signing

EMAIL_CONFIRM_SALT = "accounts.email-confirm"
EMAIL_CONFIRM_MAX_AGE = 60 * 60 * 48  # 48 horas


def make_email_token(user):
    return signing.dumps({"u": user.pk, "e": user.email}, salt=EMAIL_CONFIRM_SALT)


def read_email_token(token):
    """Devuelve (user_id, email) o None si el token es inválido o expiró."""
    try:
        data = signing.loads(token, salt=EMAIL_CONFIRM_SALT, max_age=EMAIL_CONFIRM_MAX_AGE)
    except signing.BadSignature:
        return None
    return data["u"], data["e"]
