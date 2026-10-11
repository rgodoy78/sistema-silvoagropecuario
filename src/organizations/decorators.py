from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render


def organization_required(view):
    """La vista necesita una organización activa (los datos se filtran por ella)."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.organization is None:
            return render(request, "organizations/no_organization.html", status=403)
        return view(request, *args, **kwargs)

    return wrapper


def organization_admin_required(view):
    @organization_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.membership.is_admin:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper
