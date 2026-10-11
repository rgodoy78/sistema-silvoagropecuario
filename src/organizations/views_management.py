"""Gestión de organizaciones (clientes). Solo para administradores del sistema."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.views_management import admin_required
from organizations.forms import MemberAddForm, OrganizationForm
from organizations.models import Membership, Organization
from organizations.views import apply_member_action

User = get_user_model()


@admin_required
def organization_list(request):
    query = request.GET.get("q", "").strip()
    organizations = Organization.objects.annotate(members=Count("memberships"))
    if query:
        organizations = organizations.filter(Q(name__icontains=query) | Q(rut__icontains=query))
    page = Paginator(organizations.order_by("name"), 25).get_page(request.GET.get("pagina"))
    return render(request, "organizations/management/list.html", {"page": page, "query": query})


@admin_required
@require_http_methods(["GET", "POST"])
def organization_create(request):
    """Crea un cliente. Con ?usuario=<id> usa la empresa que indicó al registrarse y lo deja como administrador."""
    owner = None
    if user_id := request.GET.get("usuario"):
        owner = get_object_or_404(User, pk=user_id)
    form = OrganizationForm(request.POST or None, initial={"name": owner.company if owner else ""})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            organization = form.save()
            if owner:
                Membership.objects.create(user=owner, organization=organization, role=Membership.Role.ADMIN)
        messages.success(request, f"Organización {organization} creada.")
        if owner:
            return redirect("management:user_edit", pk=owner.pk)
        return redirect("org_management:detail", pk=organization.pk)
    return render(request, "organizations/management/create.html", {"form": form, "owner": owner})


@admin_required
@require_http_methods(["GET", "POST"])
def organization_detail(request, pk):
    organization = get_object_or_404(Organization, pk=pk)
    form = OrganizationForm(request.POST or None, instance=organization)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Organización actualizada.")
        return redirect("org_management:detail", pk=organization.pk)
    members = list(organization.memberships.select_related("user").order_by("user__first_name", "user__email"))
    for m in members:
        m.editable = True
    context = {
        "organization": organization,
        "form": form,
        "add_form": MemberAddForm(organization),
        "members": members,
        "roles": Membership.Role.choices,
    }
    return render(request, "organizations/management/detail.html", context)


@admin_required
@require_POST
def member_add(request, pk):
    organization = get_object_or_404(Organization, pk=pk)
    form = MemberAddForm(organization, request.POST)
    if form.is_valid():
        Membership.objects.create(user=form.user, organization=organization, role=form.cleaned_data["role"])
        messages.success(request, f"{form.user} agregado a {organization}.")
    else:
        messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
    return redirect("org_management:detail", pk=organization.pk)


@admin_required
@require_POST
def member_update(request, pk):
    membership = get_object_or_404(Membership.objects.select_related("organization", "user"), pk=pk)
    if error := apply_member_action(request, membership):
        messages.error(request, error)
    return redirect("org_management:detail", pk=membership.organization_id)
