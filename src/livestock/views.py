from datetime import date, timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core import charts
from livestock import services
from livestock.forms import (
    AnimalCreateForm,
    AnimalEditForm,
    ExitForm,
    FarmForm,
    LotForm,
    PaddockForm,
    TransferForm,
    WeighingForm,
    WeighingImportForm,
)
from livestock.models import Animal, Farm, Lot, Movement, Paddock, Weaning, Weighing
from organizations.decorators import organization_required, organization_write_required


def _get(model, request, pk, **filters):
    """Objeto de la organización activa; un id de otra organización da 404."""
    return get_object_or_404(model.objects.for_org(request.organization), pk=pk, **filters)


def selected_animals(request, **filters):
    """Animales activos elegidos en el listado (?animal=1&animal=2) o un lote completo (?lote=3)."""
    source = request.POST if request.method == "POST" else request.GET
    animals = Animal.objects.for_org(request.organization).filter(status=Animal.Status.ACTIVE, **filters)
    ids = [i for i in source.getlist("animal") if i.isdigit()]
    lot_id = source.get("lote", "")
    if ids:
        animals = animals.filter(pk__in=ids)
    elif lot_id.isdigit():
        animals = animals.filter(lot_id=lot_id)
    else:
        return []
    return list(animals.select_related("farm", "paddock"))


# --- Panel ------------------------------------------------------------------


@organization_required
def dashboard(request):
    org = request.organization
    active = Animal.objects.for_org(org).filter(status=Animal.Status.ACTIVE)
    year_ago = date.today() - timedelta(days=365)
    moves = dict(
        Movement.objects.for_org(org).filter(date__gte=year_ago).order_by().values_list("kind").annotate(n=Count("id"))
    )
    gain = services.herd_daily_gain(org)
    by_category = services.stock_by_category(org)
    by_farm = list(active.order_by().values_list("farm__name").annotate(n=Count("id")).order_by("-n"))
    total, females = active.count(), active.filter(sex=Animal.Sex.FEMALE).count()
    context = {
        "total": total,
        "females": females,
        "males": total - females,
        "gain": gain,
        "weighed_30": Weighing.objects.for_org(org).filter(date__gte=date.today() - timedelta(days=30)).count(),
        "moves": {kind.label: moves.get(kind.value, 0) for kind in Movement.Kind if kind != Movement.Kind.INITIAL},
        "by_category": charts.hbar_chart([c for c, _ in by_category], [n for _, n in by_category]),
        "by_farm": charts.hbar_chart([f for f, _ in by_farm], [n for _, n in by_farm]),
        "gain_by_lot": charts.hbar_chart(
            [lot for lot, _, _ in gain["by_lot"]], [round(g, 2) for _, g, _ in gain["by_lot"]]
        ),
        "has_farms": Farm.objects.for_org(org).exists(),
        "recent": Movement.objects.for_org(org).select_related("animal").order_by("-date", "-created_at")[:8],
    }
    return render(request, "livestock/dashboard.html", context)


# --- Animales ---------------------------------------------------------------


@organization_required
def animal_list(request):
    org = request.organization
    animals = Animal.objects.for_org(org).select_related("breed", "farm", "paddock", "lot")
    f = {k: request.GET.get(k, "") for k in ("q", "predio", "lote", "categoria", "sexo", "estado")}
    f["estado"] = f["estado"] or Animal.Status.ACTIVE
    if f["estado"] != "todos":
        animals = animals.filter(status=f["estado"])
    if f["q"]:
        animals = animals.filter(Q(diio__icontains=f["q"]) | Q(tag__icontains=f["q"]) | Q(sire__icontains=f["q"]))
    if f["predio"].isdigit():
        animals = animals.filter(farm_id=f["predio"])
    if f["lote"].isdigit():
        animals = animals.filter(lot_id=f["lote"])
    if f["categoria"] in Animal.Category.values:
        animals = animals.filter(category=f["categoria"])
    if f["sexo"] in Animal.Sex.values:
        animals = animals.filter(sex=f["sexo"])
    page = Paginator(animals.order_by("diio", "tag"), 50).get_page(request.GET.get("pagina"))
    query = request.GET.copy()
    query.pop("pagina", None)
    context = {
        "page": page,
        "f": f,
        "querystring": query.urlencode(),
        "farms": Farm.objects.for_org(org),
        "lots": Lot.objects.for_org(org),
        "categories": Animal.Category.choices,
        "sexes": Animal.Sex.choices,
        "statuses": Animal.Status.choices,
    }
    return render(request, "livestock/animal_list.html", context)


@organization_write_required
@require_http_methods(["GET", "POST"])
def animal_create(request):
    org = request.organization
    if not Farm.objects.for_org(org).exists():
        messages.info(request, "Primero registra un predio.")
        return redirect("livestock:farm_create")
    form = AnimalCreateForm(request.POST or None, organization=org)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        animal = services.register_animal(
            form.instance, request.user, entry_weight=data["entry_weight"], counterparty=data["counterparty"],
            counterparty_rut=data["counterparty_rut"], price=data["price"], fma=data["fma"],
        )
        messages.success(request, f"Animal {animal} registrado.")
        if "otro" in request.POST:
            return redirect("livestock:animal_create")
        return redirect("livestock:animal_detail", pk=animal.pk)
    return render(request, "livestock/animal_form.html", {"form": form})


@organization_required
def animal_detail(request, pk):
    animal = _get(Animal, request, pk)
    history = services.weighing_history(animal)
    chart = None
    if len(history) > 1:
        points = history[-24:]
        chart = charts.line_chart(
            [r["weighing"].date.strftime("%d-%m-%y") for r in points],
            [("Peso", [float(r["weighing"].weight_kg) for r in points])],
            zero_based=False,
        )
    first_last = [(r["weighing"].date, r["weighing"].weight_kg) for r in (history[0], history[-1])] if history else None
    context = {
        "animal": animal,
        "history": list(reversed(history)),
        "chart": chart,
        "total_gain": services.daily_gain(*first_last) if first_last and len(history) > 1 else None,
        "last_weight": history[-1]["weighing"] if history else None,
        "movements": animal.movements.select_related("from_farm", "to_farm", "from_paddock", "to_paddock"),
        "offspring": animal.offspring.all(),
        "weighing_form": WeighingForm(organization=request.organization),
        "age": animal.age_months(),
        "is_breeding": animal.category in services.BREEDING_CATEGORIES,
        "is_calf": animal.category in (Animal.Category.CALF_F, Animal.Category.CALF_M),
        "services": animal.services.select_related("bull"),
        "checks": animal.pregnancy_checks.all(),
        "calvings": animal.calvings.select_related("calf"),
        "weaning": Weaning.objects.filter(calf=animal).first(),
        "treatments": animal.treatments.select_related("product"),
        "withdrawal": services.active_withdrawal(animal),
    }
    return render(request, "livestock/animal_detail.html", context)


@organization_write_required
@require_http_methods(["GET", "POST"])
def animal_edit(request, pk):
    animal = _get(Animal, request, pk)
    form = AnimalEditForm(request.POST or None, instance=animal, organization=request.organization)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Ficha actualizada.")
        return redirect("livestock:animal_detail", pk=animal.pk)
    return render(request, "livestock/animal_form.html", {"form": form, "animal": animal})


@organization_write_required
@require_http_methods(["GET", "POST"])
def animal_exit(request, pk):
    animal = _get(Animal, request, pk, status=Animal.Status.ACTIVE)
    form = ExitForm(request.POST or None, animal=animal, organization=request.organization)
    if request.method == "POST" and form.is_valid():
        movement = services.register_exit(animal, form.instance, request.user)
        messages.success(request, f"{movement.get_kind_display()} de {animal} registrada.")
        return redirect("livestock:animal_detail", pk=animal.pk)
    return render(request, "livestock/exit_form.html", {"form": form, "animal": animal})


# --- Pesajes ----------------------------------------------------------------


@organization_write_required
@require_POST
def weighing_add(request, pk):
    animal = _get(Animal, request, pk, status=Animal.Status.ACTIVE)
    form = WeighingForm(request.POST, organization=request.organization)
    if form.is_valid():
        weighing = form.save(commit=False)
        weighing.animal, weighing.created_by = animal, request.user
        weighing.save()
        messages.success(request, f"Pesaje de {weighing.weight_kg} kg registrado.")
    else:
        messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
    return redirect("livestock:animal_detail", pk=animal.pk)


@organization_write_required
@require_POST
def weighing_delete(request, pk):
    weighing = _get(Weighing, request, pk)
    weighing.delete()
    messages.success(request, "Pesaje eliminado.")
    return redirect("livestock:animal_detail", pk=weighing.animal_id)


@organization_write_required
@require_http_methods(["GET", "POST"])
def weighing_import(request):
    form = WeighingImportForm(request.POST or None, request.FILES or None)
    result = None
    if request.method == "POST" and form.is_valid():
        rows, error = services.read_scale_file(form.cleaned_data["file"].read())
        if error:
            form.add_error("file", error)
        else:
            result = services.import_weighings(
                request.organization, request.user, rows, default_date=form.cleaned_data["date"],
                method=form.cleaned_data["method"],
            )
            if result.created:
                messages.success(request, f"{result.created} pesajes importados.")
    return render(request, "livestock/weighing_import.html", {"form": form, "result": result})


# --- Traslados --------------------------------------------------------------


@organization_write_required
@require_http_methods(["GET", "POST"])
def transfer(request):
    org = request.organization
    animals = selected_animals(request)
    if not animals:
        messages.error(request, "Selecciona al menos un animal en existencia para trasladar.")
        return redirect("livestock:animal_list")

    form = TransferForm(request.POST or None, organization=org)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        to_farm = data["to_farm"]
        needs_fma = any(a.farm_id != to_farm.pk and (a.farm.rup or to_farm.rup) and a.farm.rup != to_farm.rup
                        for a in animals)
        if needs_fma and not data["fma"]:
            form.add_error("fma", "El traslado a otro RUP requiere el N° de FMA del SAG.")
        else:
            moved = services.transfer(
                animals, request.user, on=data["date"], to_farm=to_farm, to_paddock=data["to_paddock"],
                lot=data["lot"], fma=data["fma"], notes=data["notes"],
            )
            plural = moved != 1
            messages.success(request, f"{moved} animal{'es' if plural else ''} trasladado{'s' if plural else ''}.")
            if len(animals) == 1:
                return redirect("livestock:animal_detail", pk=animals[0].pk)
            return redirect("livestock:animal_list")
    return render(request, "livestock/transfer_form.html", {"form": form, "animals": animals})


# --- Predios y potreros -----------------------------------------------------


@organization_required
def farm_list(request):
    farms = (
        Farm.objects.for_org(request.organization)
        .annotate(
            heads=Count("animals", filter=Q(animals__status=Animal.Status.ACTIVE)),
            paddock_count=Count("paddocks", distinct=True),
        )
    )
    return render(request, "livestock/farm_list.html", {"farms": farms})


@organization_write_required
@require_http_methods(["GET", "POST"])
def farm_edit(request, pk=None):
    farm = _get(Farm, request, pk) if pk else None
    form = FarmForm(request.POST or None, instance=farm, organization=request.organization)
    if request.method == "POST" and form.is_valid():
        farm = form.save()
        messages.success(request, f"Predio {farm} guardado.")
        return redirect("livestock:farm_detail", pk=farm.pk)
    back = ("livestock:farm_detail", farm.pk) if farm else ("livestock:farm_list", None)
    return render(
        request, "livestock/simple_form.html",
        {"form": form, "title": str(farm) if farm else "Nuevo predio", "back": back, "back_label": "Predios"},
    )


@organization_required
def farm_detail(request, pk):
    farm = _get(Farm, request, pk)
    paddocks = farm.paddocks.annotate(heads=Count("animals", filter=Q(animals__status=Animal.Status.ACTIVE)))
    context = {
        "farm": farm,
        "paddocks": paddocks,
        "heads": farm.animals.filter(status=Animal.Status.ACTIVE).count(),
        "paddock_form": PaddockForm(organization=request.organization, farm=farm),
    }
    return render(request, "livestock/farm_detail.html", context)


@organization_write_required
@require_POST
def paddock_add(request, pk):
    farm = _get(Farm, request, pk)
    form = PaddockForm(request.POST, organization=request.organization, farm=farm)
    if form.is_valid():
        form.save()
        messages.success(request, f"Potrero {form.instance.name} agregado.")
    else:
        messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
    return redirect("livestock:farm_detail", pk=farm.pk)


@organization_write_required
@require_POST
def paddock_delete(request, pk):
    paddock = _get(Paddock, request, pk)
    if paddock.animals.filter(status=Animal.Status.ACTIVE).exists():
        messages.error(request, "No se puede eliminar un potrero con animales. Trasládalos primero.")
    else:
        paddock.delete()
        messages.success(request, f"Potrero {paddock.name} eliminado.")
    return redirect("livestock:farm_detail", pk=paddock.farm_id)


# --- Lotes ------------------------------------------------------------------


@organization_required
def lot_list(request):
    lots = Lot.objects.for_org(request.organization).annotate(
        heads=Count("animals", filter=Q(animals__status=Animal.Status.ACTIVE))
    )
    return render(request, "livestock/lot_list.html", {"lots": lots})


@organization_write_required
@require_http_methods(["GET", "POST"])
def lot_edit(request, pk=None):
    lot = _get(Lot, request, pk) if pk else None
    form = LotForm(request.POST or None, instance=lot, organization=request.organization)
    if request.method == "POST" and form.is_valid():
        lot = form.save()
        messages.success(request, f"Lote {lot} guardado.")
        return redirect("livestock:lot_list")
    return render(
        request, "livestock/simple_form.html",
        {"form": form, "title": str(lot) if lot else "Nuevo lote", "back": ("livestock:lot_list", None),
         "back_label": "Lotes"},
    )
