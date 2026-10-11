"""Organización activa y equipo del cliente (lo gestiona el administrador de cada organización)."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from organizations.decorators import organization_admin_required
from organizations.forms import MemberRoleForm
from organizations.middleware import SESSION_KEY, active_memberships
from organizations.models import Membership


@login_required
@require_POST
def switch(request):
    membership = active_memberships(request.user).filter(organization_id=request.POST.get("organizacion")).first()
    if membership is None:
        raise Http404
    request.session[SESSION_KEY] = membership.organization_id
    messages.success(request, f"Trabajando en {membership.organization}.")
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}, require_https=request.is_secure()):
        next_url = "home"
    return redirect(next_url)


def apply_member_action(request, membership):
    """Cambia el rol o quita a un miembro según request.POST. Devuelve un mensaje de error o None."""
    action = request.POST.get("accion")
    if action == "quitar":
        membership.delete()
        messages.success(request, f"{membership.user} ya no pertenece a {membership.organization}.")
        return None
    if action == "rol":
        form = MemberRoleForm(request.POST)
        if not form.is_valid():
            return "Rol no válido."
        membership.role = form.cleaned_data["role"]
        membership.save(update_fields=["role"])
        messages.success(request, f"Rol de {membership.user}: {membership.get_role_display()}.")
        return None
    return "Acción no válida."


@organization_admin_required
@require_GET
def team(request):
    members = list(request.organization.memberships.select_related("user").order_by("user__first_name", "user__email"))
    for m in members:
        m.editable = m.user_id != request.user.pk
    return render(request, "organizations/team.html", {"members": members, "roles": Membership.Role.choices})


@organization_admin_required
@require_POST
def team_member(request, pk):
    # Solo miembros de la organización activa: un id de otra organización da 404.
    membership = get_object_or_404(Membership, pk=pk, organization=request.organization)
    if membership.user_id == request.user.pk:
        messages.error(request, "No puedes cambiar tu propio rol ni quitarte de la organización.")
    elif error := apply_member_action(request, membership):
        messages.error(request, error)
    return redirect("organizations:team")
