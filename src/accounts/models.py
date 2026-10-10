from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from accounts.validators import validate_rut


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("El correo es obligatorio")
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        extra_fields["status"] = User.Status.ACTIVE
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, email):
        return self.get(email__iexact=email)


class User(AbstractUser):
    """Usuario del sistema. Inicia sesión con su correo.

    Ciclo de vida de una cuenta auto-registrada:
      EMAIL_PENDING -> (confirma correo) -> APPROVAL_PENDING
      -> (un administrador revisa) -> ACTIVE | REJECTED
    Un administrador puede luego deshabilitarla (DISABLED).
    Solo las cuentas ACTIVE pueden iniciar sesión (is_active se deriva de status).
    """

    class Status(models.TextChoices):
        EMAIL_PENDING = "email_pending", "Correo sin confirmar"
        APPROVAL_PENDING = "approval_pending", "Pendiente de aprobación"
        ACTIVE = "active", "Activa"
        REJECTED = "rejected", "Rechazada"
        DISABLED = "disabled", "Deshabilitada"

    username = None
    email = models.EmailField("correo electrónico", unique=True)
    status = models.CharField("estado", max_length=20, choices=Status.choices, default=Status.EMAIL_PENDING)

    # Datos de perfil.
    rut = models.CharField("RUT", max_length=12, blank=True, validators=[validate_rut])
    phone = models.CharField("teléfono", max_length=20, blank=True)
    position = models.CharField("cargo", max_length=100, blank=True)

    reviewed_by = models.ForeignKey(
        "self", verbose_name="revisado por", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField("revisado el", null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["email"]
        permissions = [("manage_users", "Puede gestionar usuarios y roles")]
        constraints = [
            models.UniqueConstraint(fields=["rut"], condition=~models.Q(rut=""), name="accounts_user_rut_unique"),
        ]

    def __str__(self):
        return self.get_full_name() or self.email

    def save(self, *args, **kwargs):
        self.email = self.email.lower()
        self.is_active = self.status == self.Status.ACTIVE
        super().save(*args, **kwargs)

    @property
    def is_administrator(self):
        """Puede gestionar usuarios y roles. Debe usar 2FA obligatoriamente."""
        return self.is_superuser or self.has_perm("accounts.manage_users")
