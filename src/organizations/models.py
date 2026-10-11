"""Clientes del servicio (multi-organización).

Cada cliente es una Organization. Los usuarios son globales (un mismo
veterinario o contador puede trabajar para varios clientes) y se vinculan a
cada organización mediante una Membership con un rol.

Todo dato productivo hereda de OrganizationScopedModel y se consulta siempre
filtrado por la organización activa (request.organization).
"""

from django.conf import settings
from django.db import models

from accounts.validators import validate_rut


class Organization(models.Model):
    name = models.CharField("nombre", max_length=150)
    rut = models.CharField("RUT", max_length=12, blank=True, validators=[validate_rut])
    is_active = models.BooleanField("activa", default=True, help_text="Una organización inactiva no es accesible.")
    created_at = models.DateTimeField("creada el", auto_now_add=True)

    class Meta:
        verbose_name = "organización"
        verbose_name_plural = "organizaciones"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["rut"], condition=~models.Q(rut=""), name="organizations_organization_rut_unique"
            ),
        ]

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrador"
        MANAGER = "manager", "Gerencia"
        OFFICE = "office", "Administrativo"
        ACCOUNTANT = "accountant", "Contador"
        FIELD_BOSS = "field_boss", "Jefe de campo"
        OPERATOR = "operator", "Operario"
        VIEWER = "viewer", "Externo (solo lectura)"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="usuario", on_delete=models.CASCADE, related_name="memberships"
    )
    organization = models.ForeignKey(
        Organization, verbose_name="organización", on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField("rol", max_length=20, choices=Role.choices, default=Role.OPERATOR)
    created_at = models.DateTimeField("agregado el", auto_now_add=True)

    class Meta:
        verbose_name = "miembro"
        verbose_name_plural = "miembros"
        ordering = ["organization__name", "user__email"]
        constraints = [
            models.UniqueConstraint(fields=["user", "organization"], name="organizations_membership_unique"),
        ]

    def __str__(self):
        return f"{self.user} · {self.organization} ({self.get_role_display()})"

    # Roles que registran y modifican datos productivos; el resto solo consulta.
    WRITE_ROLES = {Role.ADMIN, Role.MANAGER, Role.OFFICE, Role.FIELD_BOSS, Role.OPERATOR}

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def can_write(self):
        return self.role in self.WRITE_ROLES


class OrganizationScopedQuerySet(models.QuerySet):
    def for_org(self, organization):
        return self.filter(organization=organization)


class OrganizationScopedModel(models.Model):
    """Base de todo dato que pertenece a un cliente."""

    organization = models.ForeignKey(
        Organization, verbose_name="organización", on_delete=models.PROTECT, related_name="+", editable=False
    )

    objects = OrganizationScopedQuerySet.as_manager()

    class Meta:
        abstract = True
