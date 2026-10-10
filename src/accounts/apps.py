from django.apps import AppConfig
from django.db.models.signals import post_migrate

ADMIN_ROLE = "Administrador"


def ensure_admin_role(sender, **kwargs):
    """Crea el rol 'Administrador' con el permiso de gestionar usuarios."""
    from django.contrib.auth.models import Group, Permission

    perm = Permission.objects.filter(codename="manage_users", content_type__app_label="accounts").first()
    if perm:
        group, _ = Group.objects.get_or_create(name=ADMIN_ROLE)
        group.permissions.add(perm)


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Cuentas"

    def ready(self):
        post_migrate.connect(ensure_admin_role, sender=self)
