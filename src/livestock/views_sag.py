"""Trámites SAG (DEA, FMA, DIIO pendientes) e importación de animales."""

import csv
import logging
from datetime import date

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from livestock import importer, sag
from livestock.forms import DATE_INPUT
from livestock.models import Farm
from livestock.views import selected_animals
from organizations.decorators import organization_required, organization_write_required

logger = logging.getLogger(__name__)


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")  # BOM: Excel reconoce UTF-8 (tildes y ñ)
    writer = csv.writer(response, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    return response


@organization_required
def sag_overview(request):
    org = request.organization
    rows, totals = sag.stock_by_rup(org)
    if request.GET.get("formato") == "csv":
        data = [[r["farm"].name, r["farm"].rup, *r["counts"], r["total"]] for r in rows]
        return _csv_response(
            f"existencias-dea-{date.today():%Y%m%d}.csv", ["Predio", "RUP", *sag.SAG_CATEGORIES, "Total"], data
        )
    context = {
        "rows": rows,
        "totals": totals,
        "grand_total": sum(totals),
        "categories": sag.SAG_CATEGORIES,
        "pending": sag.diio_pending(org),
        "today": date.today(),
        "missing_rup": [r["farm"] for r in rows if not r["farm"].rup],
    }
    return render(request, "livestock/sag.html", context)


class FMAForm(forms.Form):
    date = forms.DateField(label="Fecha de salida", initial=date.today, widget=DATE_INPUT)
    to_farm = forms.ModelChoiceField(
        label="Destino propio", queryset=Farm.objects.none(), required=False,
        help_text="O completa el RUP y nombre de un destino externo.",
    )
    to_rup = forms.CharField(label="RUP de destino", required=False, max_length=20)
    to_name = forms.CharField(label="Establecimiento de destino", required=False, max_length=120)
    carrier = forms.CharField(label="Transportista", required=False, max_length=120)
    carrier_rut = forms.CharField(label="RUT transportista", required=False, max_length=12)
    plate = forms.CharField(label="Patente vehículo / acoplado", required=False, max_length=30)

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_farm"].queryset = Farm.objects.for_org(organization)

    def clean(self):
        cleaned = super().clean()
        farm = cleaned.get("to_farm")
        if farm:
            cleaned["to_rup"], cleaned["to_name"] = farm.rup, farm.name
        if not cleaned.get("to_rup"):
            self.add_error("to_rup", "Indica el RUP de destino.")
        return cleaned


@organization_required
def fma_sheet(request):
    """Planilla para emitir el FMA en SIPECweb: un origen, un destino, conteo por categoría y DIIO."""
    animals = selected_animals(request)
    if not animals:
        messages.error(request, "Selecciona en el listado los animales que se trasladarán.")
        return redirect("livestock:animal_list")
    origins = {a.farm for a in animals}
    if len(origins) > 1:
        messages.error(
            request, "El SAG exige un FMA por establecimiento de origen: selecciona animales de un solo predio."
        )
        return redirect("livestock:animal_list")
    form = FMAForm(request.GET if "date" in request.GET else None, organization=request.organization)
    sheet = None
    if form.is_bound and form.is_valid():
        sheet = {
            **form.cleaned_data,
            "origin": origins.pop(),
            "counts": list(zip(sag.SAG_CATEGORIES, sag.count_by_sag_category(animals), strict=True)),
            "without_diio": [a for a in animals if not a.diio],
        }
    return render(request, "livestock/fma.html", {"form": form, "animals": animals, "sheet": sheet})


class AnimalImportForm(forms.Form):
    file = forms.FileField(label="Planilla de animales (.xlsx o .csv)", help_text="Máximo 5 MB y 5.000 filas.")

    MAX_BYTES = 5 * 1024 * 1024

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > self.MAX_BYTES:
            raise forms.ValidationError("El archivo supera los 5 MB.")
        if not upload.name.lower().endswith((".xlsx", ".csv", ".txt")):
            raise forms.ValidationError("Sube un archivo .xlsx (Excel) o .csv.")
        return upload


@organization_write_required
@require_http_methods(["GET", "POST"])
def animal_import(request):
    if request.GET.get("plantilla"):
        return _csv_response("plantilla-animales.csv", importer.TEMPLATE_HEADER, importer.TEMPLATE_ROWS)
    form = AnimalImportForm(request.POST or None, request.FILES or None)
    report = None
    if request.method == "POST" and form.is_valid():
        try:
            report = importer.import_animals(request.organization, request.user, form.cleaned_data["file"])
        except Exception:  # archivo corrupto o con un formato que openpyxl/csv no puede leer
            logger.warning("Importación de animales fallida", exc_info=True)
            form.add_error("file", "No se pudo leer el archivo. Verifica que sea un .xlsx o .csv válido.")
        else:
            if report.created:
                messages.success(request, f"{report.created} animales importados.")
    has_farms = Farm.objects.for_org(request.organization).exists()
    return render(request, "livestock/animal_import.html", {"form": form, "report": report, "has_farms": has_farms})
