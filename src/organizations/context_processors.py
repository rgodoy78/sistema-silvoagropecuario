from django.utils.functional import SimpleLazyObject

from organizations.middleware import active_memberships


def organization(request):
    user = getattr(request, "user", None)
    return {
        "current_organization": getattr(request, "organization", None),
        "current_membership": getattr(request, "membership", None),
        # Para el selector de organización; solo se consulta si la plantilla lo usa.
        "user_memberships": SimpleLazyObject(
            lambda: list(active_memberships(user).order_by("organization__name"))
            if user and user.is_authenticated
            else []
        ),
    }
