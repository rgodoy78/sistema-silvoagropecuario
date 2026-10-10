import re

from django.core.exceptions import ValidationError

RUT_RE = re.compile(r"^(\d{1,8})-?([\dkK])$")


def normalize_rut(value):
    """'12.345.678-k' -> '12345678-K'."""
    return value.replace(".", "").replace(" ", "").upper()


def rut_check_digit(number):
    total, factor = 0, 2
    for digit in reversed(str(number)):
        total += int(digit) * factor
        factor = 2 if factor == 7 else factor + 1
    remainder = 11 - total % 11
    return {11: "0", 10: "K"}.get(remainder, str(remainder))


def validate_rut(value):
    if not value:
        return
    match = RUT_RE.match(normalize_rut(value))
    if not match or rut_check_digit(match.group(1)) != match.group(2).upper():
        raise ValidationError("RUT inválido.", code="invalid_rut")
