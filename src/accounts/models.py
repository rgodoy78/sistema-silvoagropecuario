from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Usuario del sistema.

    Modelo propio desde el inicio para poder agregar campos (RUT, teléfono,
    etc.) sin migraciones complejas. La gestión de usuarios y perfiles la
    hace la aplicación, no el admin de Django.
    """

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
