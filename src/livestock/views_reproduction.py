"""Reproducción: servicios (encaste/IA), diagnósticos de preñez, partos y destetes."""

from datetime import date

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from livestock import services
from livestock.forms import CalvingForm, PregnancyCheckForm, ServiceForm, WeaningForm
from livestock.models import Animal, Calving, PregnancyCheck, Service, Weaning
from livestock.views import _get, selected_animals
from organizations.decorators import organization_required, organization_write_required

BREEDING = list(services.BREEDING_CATEGORIES)


@organization_required
def reproduction(request):
    org = request.organization
    context = {
        "summary": services.reproduction_summary(org),
        "recent_calvings": Calving.objects.for_org(org).select_related("mother", "calf")[:10],
        "recent_checks": PregnancyCheck.objects.for_org(org).select_related("female")[:10],
        "today": date.today(),
    }
    return render(request, "livestock/reproduction.html", context)


@organization_write_required
@require_http_methods(["GET", "POST"])
def service_add(request):
    """Servicio de una o varias hembras (?animal=… o ?lote=…)."""
    females = selected_animals(request, category__in=BREEDING)
    if not females:
        messages.error(request, "Selecciona vacas o vaquillas en existencia para registrar el servicio.")
        return redirect("livestock:animal_list")
    form = ServiceForm(request.POST or None, organization=request.organization)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        n = services.register_services(
            females, request.user, kind=data["kind"], on=data["date"], bull=data["bull"], semen=data["semen"],
            technician=data["technician"], notes=data["notes"],
        )
        messages.success(request, f"Servicio registrado a {n} hembra{'s' if n != 1 else ''}.")
        if len(females) == 1:
            return redirect("livestock:animal_detail", pk=females[0].pk)
        return redirect("livestock:reproduction")
    return render(
        request, "livestock/bulk_form.html",
        {"form": form, "animals": females, "title": "Registrar servicio", "submit": "Registrar servicio"},
    )


@organization_write_required
@require_http_methods(["GET", "POST"])
def check_add(request, pk):
    female = _get(Animal, request, pk, status=Animal.Status.ACTIVE, category__in=BREEDING)
    form = PregnancyCheckForm(request.POST or None, organization=request.organization)
    if request.method == "POST" and form.is_valid():
        check = form.save(commit=False)
        check.female, check.created_by = female, request.user
        check.save()
        extra = f" · parto probable {check.expected_calving:%d-%m-%Y}" if check.expected_calving else ""
        messages.success(request, f"Diagnóstico: {check.get_result_display().lower()}{extra}.")
        return redirect("livestock:animal_detail", pk=female.pk)
    return render(
        request, "livestock/event_form.html",
        {"form": form, "animal": female, "title": f"Diagnóstico de preñez · {female}"},
    )


@organization_write_required
@require_http_methods(["GET", "POST"])
def calving_add(request, pk):
    mother = _get(Animal, request, pk, status=Animal.Status.ACTIVE, category__in=BREEDING)
    form = CalvingForm(request.POST or None, mother=mother)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        calving = services.register_calving(
            mother, request.user, on=d["date"], ease=d["ease"], stillborn=d["stillborn"], calf_sex=d["calf_sex"],
            calf_diio=d["calf_diio"], calf_tag=d["calf_tag"], calf_breed=d["calf_breed"],
            birth_weight=d["birth_weight"], notes=d["notes"],
        )
        if calving.calf:
            messages.success(request, f"Parto registrado. Cría {calving.calf} ingresada al rebaño.")
            return redirect("livestock:animal_detail", pk=calving.calf.pk)
        messages.success(request, "Parto registrado (cría nacida muerta).")
        return redirect("livestock:animal_detail", pk=mother.pk)
    return render(request, "livestock/event_form.html", {"form": form, "animal": mother, "title": f"Parto de {mother}"})


@organization_write_required
@require_http_methods(["GET", "POST"])
def weaning_add(request, pk):
    calf = _get(
        Animal, request, pk, status=Animal.Status.ACTIVE, category__in=[Animal.Category.CALF_F, Animal.Category.CALF_M]
    )
    if Weaning.objects.filter(calf=calf).exists():
        messages.error(request, "Esta cría ya tiene destete registrado.")
        return redirect("livestock:animal_detail", pk=calf.pk)
    form = WeaningForm(request.POST or None, calf=calf)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        weaning = services.register_weaning(
            calf, request.user, on=d["date"], weight=d["weight"], new_category=d["new_category"], notes=d["notes"]
        )
        adjusted = weaning.adjusted_205
        extra = f" · peso ajustado a 205 días: {adjusted:.0f} kg" if adjusted else ""
        messages.success(request, f"Destete registrado{extra}.")
        return redirect("livestock:animal_detail", pk=calf.pk)
    return render(request, "livestock/event_form.html", {"form": form, "animal": calf, "title": f"Destete de {calf}"})


EVENT_MODELS = {"servicio": Service, "diagnostico": PregnancyCheck}


@organization_write_required
@require_http_methods(["POST"])
def event_delete(request, kind, pk):
    """Elimina un registro hecho por error (servicios y diagnósticos; partos y destetes crean otros datos)."""
    model = EVENT_MODELS.get(kind)
    if model is None:
        return redirect("livestock:reproduction")
    event = _get(model, request, pk)
    event.delete()
    messages.success(request, f"{model._meta.verbose_name.capitalize()} eliminado.")
    return redirect("livestock:animal_detail", pk=event.female_id)
