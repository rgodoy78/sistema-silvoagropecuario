"""Gestión de usuarios y roles. Solo para administradores (con 2FA verificado por middleware)."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from accounts import emails, otp
from accounts.apps import ADMIN_ROLE
from accounts.forms import RoleForm, UserAdminForm

User = get_user_model()


def admin_required(view):
    return login_required(permission_required("accounts.manage_users", raise_exception=True)(view))


def _editable_user(request, pk):
    user = get_object_or_404(User, pk=pk)
    # Solo un superusuario puede modificar a otro superusuario.
    if user.is_superuser and not request.user.is_superuser:
        raise PermissionDenied
    return user


# --- Usuarios ---------------------------------------------------------------


@admin_required
def user_list(request):
    status = request.GET.get("estado", "")
    query = request.GET.get("q", "").strip()
    users = User.objects.prefetch_related("groups")
    if status in User.Status.values:
        users = users.filter(status=status)
    if query:
        users = users.filter(
            Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(rut__icontains=query)
        )
    page = Paginator(users.order_by("-date_joined"), 25).get_page(request.GET.get("pagina"))
    pending = User.objects.filter(status=User.Status.APPROVAL_PENDING).count()
    return render(
        request,
        "management/user_list.html",
        {"page": page, "status": status, "query": query, "statuses": User.Status.choices, "pending": pending},
    )


@admin_required
@require_http_methods(["GET", "POST"])
def user_edit(request, pk):
    user = _editable_user(request, pk)
    form = UserAdminForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        removing_own_admin = (
            user == request.user
            and not user.is_superuser
            and not form.cleaned_data["groups"].filter(name=ADMIN_ROLE).exists()
        )
        if removing_own_admin:
            form.add_error("groups", "No puedes quitarte a ti mismo el rol de administrador.")
        else:
            form.save()
            messages.success(request, "Usuario actualizado.")
            return redirect("management:user_edit", pk=user.pk)
    return render(request, "management/user_edit.html", {"form": form, "target": user, "has_2fa": otp.has_2fa(user)})


# Transiciones de estado permitidas: acción -> (estados de origen, estado destino)
TRANSITIONS = {
    "aprobar": ({User.Status.APPROVAL_PENDING}, User.Status.ACTIVE),
    "rechazar": ({User.Status.APPROVAL_PENDING}, User.Status.REJECTED),
    "deshabilitar": ({User.Status.ACTIVE}, User.Status.DISABLED),
    "reactivar": ({User.Status.DISABLED, User.Status.REJECTED}, User.Status.ACTIVE),
}


@admin_required
@require_POST
def user_action(request, pk):
    user = _editable_user(request, pk)
    action = request.POST.get("accion")
    if user == request.user:
        messages.error(request, "No puedes cambiar el estado de tu propia cuenta.")
        return redirect("management:user_edit", pk=user.pk)

    if action == "reiniciar_2fa":
        otp.remove_2fa(user)
        messages.success(request, f"2FA reiniciado para {user.email}. Deberá configurarlo de nuevo.")
        return redirect("management:user_edit", pk=user.pk)

    if action not in TRANSITIONS or user.status not in TRANSITIONS[action][0]:
        messages.error(request, "Acción no válida para el estado actual.")
        return redirect("management:user_edit", pk=user.pk)

    previous = user.status
    user.status = TRANSITIONS[action][1]
    user.reviewed_by = request.user
    user.reviewed_at = timezone.now()
    user.save()
    if previous == User.Status.APPROVAL_PENDING:
        emails.send_review_result(request, user)
    messages.success(request, f"Cuenta de {user.email}: {user.get_status_display().lower()}.")
    return redirect("management:user_edit", pk=user.pk)


# --- Roles ------------------------------------------------------------------


@admin_required
def role_list(request):
    roles = Group.objects.order_by("name").prefetch_related("permissions")
    return render(request, "management/role_list.html", {"roles": roles, "admin_role": ADMIN_ROLE})


@admin_required
@require_http_methods(["GET", "POST"])
def role_edit(request, pk=None):
    role = get_object_or_404(Group, pk=pk) if pk else None
    form = RoleForm(request.POST or None, instance=role)
    if request.method == "POST" and form.is_valid():
        if role and role.name == ADMIN_ROLE and form.cleaned_data["name"] != ADMIN_ROLE:
            form.add_error("name", "El rol Administrador no se puede renombrar.")
        else:
            role = form.save()
            # El rol Administrador siempre conserva el permiso de gestión.
            if role.name == ADMIN_ROLE:
                from accounts.apps import ensure_admin_role

                ensure_admin_role(sender=None)
            messages.success(request, "Rol guardado.")
            return redirect("management:role_list")
    return render(request, "management/role_edit.html", {"form": form, "role": role})


@admin_required
@require_POST
def role_delete(request, pk):
    role = get_object_or_404(Group, pk=pk)
    if role.name == ADMIN_ROLE:
        messages.error(request, "El rol Administrador no se puede eliminar.")
    else:
        role.delete()
        messages.success(request, "Rol eliminado.")
    return redirect("management:role_list")
