"""Mapas: límites de predios y potreros (dibujo en el mapa o importación KML/KMZ de Google Earth)."""

from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from livestock import geo
from livestock.forms import BoundaryForm, KmlForm
from livestock.maps import map_context
from livestock.models import Farm, Paddock
from livestock.views import _get
from organizations.decorators import organization_write_required


@organization_write_required
@require_http_methods(["GET", "POST"])
def boundary_edit(request, kind, pk):
    """Dibujar o importar el límite de un predio (kind='predio') o potrero (kind='potrero')."""
    model = {"predio": Farm, "potrero": Paddock}.get(kind)
    if model is None:
        return redirect("livestock:farm_list")
    obj = _get(model, request, pk)
    farm = obj if model is Farm else obj.farm
    form = BoundaryForm(request.POST if "geojson" in request.POST else None)
    kml_form = KmlForm(request.POST if "file" in request.FILES else None, request.FILES or None)

    if request.method == "POST" and request.POST.get("accion") == "borrar":
        obj.boundary = None
        obj.save(update_fields=["boundary"])
        messages.success(request, "Límite eliminado.")
        return redirect("livestock:farm_detail", pk=farm.pk)

    if kml_form.is_bound and kml_form.is_valid():
        try:
            polygons = geo.polygons_from_kml(kml_form.cleaned_data["file"].read())
        except geo.GeometryError as e:
            kml_form.add_error("file", str(e))
        else:
            # Se carga en el editor para revisarlo antes de guardar.
            name, polygon = max(polygons, key=lambda p: geo.area_ha(p[1]))
            obj.boundary = polygon
            messages.info(request, f"Polígono «{name or 'sin nombre'}» cargado ({geo.area_ha(polygon)} ha). "
                                   "Revísalo y presiona Guardar.")

    if form.is_bound and form.is_valid():
        obj.boundary = form.cleaned_data["geojson"]
        fields = ["boundary"]
        if form.cleaned_data["update_area"]:
            obj.area_ha = Decimal(str(geo.area_ha(obj.boundary)))
            fields.append("area_ha")
        obj.save(update_fields=fields)
        messages.success(request, f"Límite de {obj.name} guardado ({geo.area_ha(obj.boundary)} ha).")
        return redirect("livestock:farm_detail", pk=farm.pk)

    context = {
        "obj": obj, "farm": farm, "kind": kind, "form": form,
        "kml_form": kml_form if kml_form.is_bound else KmlForm(),
        **map_context(farm, editing=obj),
    }
    return render(request, "livestock/boundary_edit.html", context)


@organization_write_required
@require_POST
def paddocks_from_kml(request, pk):
    """Crea o actualiza los potreros de un predio desde un KML con un polígono por potrero."""
    farm = _get(Farm, request, pk)
    form = KmlForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
        return redirect("livestock:farm_detail", pk=farm.pk)
    try:
        polygons = geo.polygons_from_kml(form.cleaned_data["file"].read())
    except geo.GeometryError as e:
        messages.error(request, str(e))
        return redirect("livestock:farm_detail", pk=farm.pk)
    existing = {p.name.lower(): p for p in farm.paddocks.all()}
    created = updated = 0
    with transaction.atomic():
        for n, (name, polygon) in enumerate(polygons, start=1):
            name = (name or f"Potrero {n}")[:80]
            area = Decimal(str(geo.area_ha(polygon)))
            paddock = existing.get(name.lower())
            if paddock:
                paddock.boundary, paddock.area_ha = polygon, area
                paddock.save(update_fields=["boundary", "area_ha"])
                updated += 1
            else:
                existing[name.lower()] = Paddock.objects.create(
                    organization=request.organization, farm=farm, name=name, boundary=polygon, area_ha=area
                )
                created += 1
    messages.success(request, f"Potreros desde el KML: {created} creados, {updated} actualizados.")
    return redirect("livestock:farm_detail", pk=farm.pk)

