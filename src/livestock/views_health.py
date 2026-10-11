"""Sanidad: productos veterinarios, tratamientos y períodos de resguardo."""

from datetime import date

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from livestock import services
from livestock.forms import HealthProductForm, TreatmentForm
from livestock.models import HealthProduct, Treatment
from livestock.views import _get, selected_animals
from organizations.decorators import organization_required, organization_write_required


@organization_required
def health(request):
    org = request.organization
    today = date.today()
    withdrawal = sorted(services.animals_in_withdrawal(org, today), key=lambda t: t.withdrawal_until)
    for t in withdrawal:
        t.days_left = (t.withdrawal_until - today).days
    context = {
        "withdrawal": withdrawal,
        "products": HealthProduct.objects.for_org(org),
        "recent": Treatment.objects.for_org(org).select_related("animal", "product")[:15],
        "product_form": HealthProductForm(organization=org),
    }
    return render(request, "livestock/health.html", context)


@organization_write_required
@require_POST
def product_add(request):
    form = HealthProductForm(request.POST, organization=request.organization)
    if form.is_valid():
        form.save()
        messages.success(request, f"Producto {form.instance} agregado.")
    else:
        messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
    return redirect("livestock:health")


@organization_write_required
@require_http_methods(["GET", "POST"])
def product_edit(request, pk):
    product = _get(HealthProduct, request, pk)
    form = HealthProductForm(request.POST or None, instance=product, organization=request.organization)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Producto actualizado. El resguardo nuevo se aplica a tratamientos futuros.")
        return redirect("livestock:health")
    return render(
        request, "livestock/simple_form.html",
        {"form": form, "title": str(product), "back": ("livestock:health", None), "back_label": "Sanidad"},
    )


@organization_write_required
@require_http_methods(["GET", "POST"])
def treatment_add(request):
    """Tratamiento de uno o varios animales (?animal=… o ?lote=…), p. ej. una vacunación del lote."""
    animals = selected_animals(request)
    if not animals:
        messages.error(request, "Selecciona al menos un animal en existencia.")
        return redirect("livestock:animal_list")
    org = request.organization
    if not HealthProduct.objects.for_org(org).filter(is_active=True).exists():
        messages.info(request, "Primero agrega el producto veterinario en Sanidad.")
        return redirect("livestock:health")
    form = TreatmentForm(request.POST or None, organization=org)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        n = services.apply_treatment(
            animals, request.user, product=d["product"], on=d["date"], dose=d["dose"], reason=d["reason"],
            applied_by=d["applied_by"], notes=d["notes"],
        )
        messages.success(request, f"{d['product']} aplicado a {n} animal{'es' if n != 1 else ''}.")
        if len(animals) == 1:
            return redirect("livestock:animal_detail", pk=animals[0].pk)
        return redirect("livestock:health")
    return render(
        request, "livestock/bulk_form.html",
        {"form": form, "animals": animals, "title": "Aplicar tratamiento", "submit": "Registrar tratamiento"},
    )


@organization_write_required
@require_POST
def treatment_delete(request, pk):
    treatment = _get(Treatment, request, pk)
    treatment.delete()
    messages.success(request, "Tratamiento eliminado.")
    return redirect("livestock:animal_detail", pk=treatment.animal_id)
