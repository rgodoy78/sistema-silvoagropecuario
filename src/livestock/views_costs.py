"""Alimentación, costos y márgenes del rebaño."""

from datetime import date, timedelta

from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from core import charts
from livestock import services
from livestock.forms import CostForm, FeedItemForm, PriceReferenceForm
from livestock.models import Animal, Cost, FeedItem, PriceReference
from livestock.views import _get, selected_animals
from organizations.decorators import organization_required, organization_write_required


@organization_required
def economics(request):
    org = request.organization
    year_ago = date.today() - timedelta(days=365)
    costs = Cost.objects.for_org(org).filter(date__gte=year_ago)
    by_category = dict(costs.order_by().values_list("category").annotate(t=Sum("amount")))
    labels = dict(Cost.Category.choices)
    lots, _ = services.lot_economics(org)
    sold = services.sold_economics(org, year_ago)
    sold_margins = [r["econ"].margin for r in sold if r["econ"].margin is not None]
    context = {
        "total_costs": sum(by_category.values(), 0),
        "general_costs": costs.filter(target=Cost.Target.GENERAL).aggregate(t=Sum("amount"))["t"] or 0,
        "herd_value": services.sum_present(row["value"] for row in lots),
        "missing_prices": not services.latest_prices(org),
        "sold_margin": sum(sold_margins) if sold_margins else None,
        "by_category": charts.hbar_chart(
            [labels[c] for c in by_category], [int(v) for v in by_category.values()]
        ),
        "lots": lots,
        "sold": sold,
        "recent": Cost.objects.for_org(org).select_related("lot", "feed_item")[:15],
        "feed_items": FeedItem.objects.for_org(org),
        "prices": PriceReference.objects.for_org(org)[:20],
        "feed_form": FeedItemForm(organization=org),
        "price_form": PriceReferenceForm(organization=org),
    }
    return render(request, "livestock/economics.html", context)


@organization_write_required
@require_http_methods(["GET", "POST"])
def cost_add(request):
    """Registrar un costo. Con ?animal=… se asigna a esos animales; si no, a un lote, al rebaño o general."""
    org = request.organization
    source = request.POST if request.method == "POST" else request.GET
    preselected = selected_animals(request) if source.getlist("animal") else []
    lot_id = request.GET.get("lote", "")
    initial = {"category": request.GET.get("categoria", "")}
    if lot_id.isdigit():
        initial.update(target=Cost.Target.LOT, lot=lot_id)
    form = CostForm(request.POST or None, organization=org, preselected=bool(preselected), initial=initial)
    if request.method == "POST" and form.is_valid():
        cost = form.instance
        active = Animal.objects.for_org(org).filter(status=Animal.Status.ACTIVE)
        animals = {
            Cost.Target.LOT: lambda: list(active.filter(lot=cost.lot)),
            Cost.Target.SELECTED: lambda: preselected,
            Cost.Target.HERD: lambda: list(active),
            Cost.Target.GENERAL: lambda: [],
        }[cost.target]()
        if cost.target != Cost.Target.GENERAL and not animals:
            form.add_error("target", "No hay animales en existencia a los que asignar este costo.")
        else:
            services.register_cost(cost, animals, request.user)
            share = f", ${cost.amount / len(animals):,.0f} por cabeza".replace(",", ".") if animals else ""
            messages.success(request, f"Costo registrado{share}.")
            return redirect("livestock:economics")
    return render(request, "livestock/cost_form.html", {"form": form, "animals": preselected})


@organization_write_required
@require_POST
def cost_delete(request, pk):
    cost = _get(Cost, request, pk)
    cost.delete()
    messages.success(request, "Costo eliminado (y su reparto entre los animales).")
    return redirect("livestock:economics")


@organization_write_required
@require_POST
def feed_item_add(request):
    form = FeedItemForm(request.POST, organization=request.organization)
    if form.is_valid():
        form.save()
        messages.success(request, f"Alimento {form.instance.name} agregado.")
    else:
        messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
    return redirect("livestock:economics")


@organization_write_required
@require_http_methods(["GET", "POST"])
def feed_item_edit(request, pk):
    item = _get(FeedItem, request, pk)
    form = FeedItemForm(request.POST or None, instance=item, organization=request.organization)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Alimento actualizado.")
        return redirect("livestock:economics")
    return render(
        request, "livestock/simple_form.html",
        {"form": form, "title": item.name, "back": ("livestock:economics", None), "back_label": "Costos"},
    )


@organization_write_required
@require_POST
def price_add(request):
    form = PriceReferenceForm(request.POST, organization=request.organization)
    if form.is_valid():
        form.save()
        messages.success(request, f"Precio de referencia: {form.instance}.")
    else:
        messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
    return redirect("livestock:economics")
