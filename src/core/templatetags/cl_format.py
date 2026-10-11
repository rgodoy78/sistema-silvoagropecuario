"""Formato numérico chileno en plantillas: punto para miles (950.000)."""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def miles(value):
    """Entero redondeado con punto de miles: 1234567.8 -> '1.234.568'. Vacío si no es número."""
    if value is None or value == "":
        return ""
    try:
        number = Decimal(value).quantize(Decimal("1"))
    except (InvalidOperation, TypeError, ValueError):
        return ""
    return f"{int(number):,}".replace(",", ".")
