import json
from datetime import date, timedelta
from decimal import Decimal

from django import forms

from accounts.validators import normalize_rut, validate_rut
from livestock import services
from livestock.geo import GeometryError, clean_polygon
from livestock.models import (
    Animal,
    Breed,
    Calving,
    Cost,
    Farm,
    FeedItem,
    HealthProduct,
    Lot,
    Movement,
    Paddock,
    PregnancyCheck,
    PriceReference,
    Service,
    Weighing,
    diio_validator,
)
from organizations.forms import OrganizationScopedForm

C = Animal.Category
FEMALE_CATEGORIES = {C.CALF_F, C.HEIFER, C.COW}
DATE_INPUT = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


def clean_rut_value(value):
    rut = normalize_rut(value or "")
    if not rut:
        return ""
    if "-" not in rut:
        rut = f"{rut[:-1]}-{rut[-1]}"
    validate_rut(rut)
    return rut


def not_in_future(value):
    if value and value > date.today():
        raise forms.ValidationError("La fecha no puede ser futura.")
    return value


class FarmForm(OrganizationScopedForm):
    class Meta:
        model = Farm
        fields = ["name", "rup", "commune", "area_ha", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class PaddockForm(OrganizationScopedForm):
    validate_assigned = ("organization", "farm")

    class Meta:
        model = Paddock
        fields = ["name", "area_ha"]

    def __init__(self, *args, farm, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.farm = farm


class LotForm(OrganizationScopedForm):
    class Meta:
        model = Lot
        fields = ["name", "purpose", "is_active", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class AnimalFieldsMixin:
    """Validaciones comunes de la ficha del animal."""

    def clean_birth_date(self):
        return not_in_future(self.cleaned_data.get("birth_date"))

    def clean(self):
        cleaned = super().clean()
        sex, category = cleaned.get("sex"), cleaned.get("category")
        if sex and category and (category in FEMALE_CATEGORIES) != (sex == Animal.Sex.FEMALE):
            self.add_error("category", "La categoría no corresponde al sexo del animal.")
        if not cleaned.get("diio") and not cleaned.get("tag"):
            self.add_error("diio", "Indica el DIIO o una identificación visual.")
        mother = cleaned.get("mother")
        if mother and self.instance.pk and mother.pk == self.instance.pk:
            self.add_error("mother", "Un animal no puede ser su propia madre.")
        farm, paddock = cleaned.get("farm", getattr(self.instance, "farm", None)), cleaned.get("paddock")
        if paddock and farm and paddock.farm_id != farm.pk:
            self.add_error("paddock", "El potrero no pertenece al predio seleccionado.")
        return cleaned


class AnimalCreateForm(AnimalFieldsMixin, OrganizationScopedForm):
    entry_weight = forms.DecimalField(
        label="Peso al ingreso (kg)", required=False, min_value=1, max_digits=6, decimal_places=1
    )
    counterparty = forms.CharField(label="Vendedor", required=False, max_length=120)
    counterparty_rut = forms.CharField(label="RUT vendedor", required=False, max_length=12)
    price = forms.DecimalField(label="Precio de compra ($)", required=False, min_value=0, decimal_places=0)
    fma = forms.CharField(label="N° FMA", required=False, max_length=30)

    class Meta:
        model = Animal
        fields = [
            "diio", "tag", "sex", "category", "breed", "birth_date", "birth_date_estimated", "mother", "sire",
            "origin", "entry_date", "farm", "paddock", "lot", "notes",
        ]
        widgets = {"birth_date": DATE_INPUT, "entry_date": DATE_INPUT, "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["mother"].queryset = self.fields["mother"].queryset.filter(status=Animal.Status.ACTIVE)
        self.fields["lot"].queryset = self.fields["lot"].queryset.filter(is_active=True)

    def clean_entry_date(self):
        return not_in_future(self.cleaned_data.get("entry_date"))

    def clean_counterparty_rut(self):
        return clean_rut_value(self.cleaned_data.get("counterparty_rut"))

    def clean(self):
        cleaned = super().clean()
        birth, entry = cleaned.get("birth_date"), cleaned.get("entry_date")
        if birth and entry and birth > entry:
            self.add_error("entry_date", "El ingreso no puede ser anterior al nacimiento.")
        if cleaned.get("origin") == Animal.Origin.BORN and not birth:
            self.add_error("birth_date", "Indica la fecha de nacimiento.")
        return cleaned


class AnimalEditForm(AnimalFieldsMixin, OrganizationScopedForm):
    """Edición de la ficha. Predio y potrero cambian solo con un traslado (queda en el historial)."""

    class Meta:
        model = Animal
        fields = [
            "diio", "tag", "sex", "category", "breed", "birth_date", "birth_date_estimated", "mother", "sire", "lot",
            "notes",
        ]
        widgets = {"birth_date": DATE_INPUT, "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["mother"].queryset = self.fields["mother"].queryset.exclude(pk=self.instance.pk)


class WeighingForm(OrganizationScopedForm):
    class Meta:
        model = Weighing
        fields = ["date", "weight_kg", "method", "notes"]
        widgets = {"date": DATE_INPUT}

    def clean_date(self):
        return not_in_future(self.cleaned_data.get("date"))


class TransferForm(forms.Form):
    date = forms.DateField(label="Fecha", initial=date.today, widget=DATE_INPUT, validators=[not_in_future])
    to_farm = forms.ModelChoiceField(label="Predio de destino", queryset=Farm.objects.none())
    to_paddock = forms.ModelChoiceField(label="Potrero de destino", queryset=Paddock.objects.none(), required=False)
    lot = forms.ModelChoiceField(
        label="Cambiar a lote", queryset=Lot.objects.none(), required=False, help_text="Déjalo vacío para no cambiarlo."
    )
    fma = forms.CharField(label="N° FMA", required=False, max_length=30, help_text="Obligatorio si cambia de predio.")
    notes = forms.CharField(label="Observación", required=False, max_length=200)

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_farm"].queryset = Farm.objects.for_org(organization)
        self.fields["to_paddock"].queryset = Paddock.objects.for_org(organization).select_related("farm")
        self.fields["lot"].queryset = Lot.objects.for_org(organization).filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        farm, paddock = cleaned.get("to_farm"), cleaned.get("to_paddock")
        if farm and paddock and paddock.farm_id != farm.pk:
            self.add_error("to_paddock", "El potrero no pertenece al predio de destino.")
        return cleaned


class ExitForm(OrganizationScopedForm):
    class Meta:
        model = Movement
        fields = ["kind", "date", "counterparty", "counterparty_rut", "fma", "weight_kg", "price_clp", "cause", "notes"]
        widgets = {"date": DATE_INPUT}
        labels = {"kind": "Tipo de salida"}

    def __init__(self, *args, animal, **kwargs):
        super().__init__(*args, **kwargs)
        self.animal = animal
        self.fields["kind"].choices = [(k.value, k.label) for k in Movement.Kind if k in Movement.EXIT_KINDS]

    def clean_date(self):
        on = not_in_future(self.cleaned_data.get("date"))
        if on and on < self.animal.entry_date:
            raise forms.ValidationError("La salida no puede ser anterior al ingreso del animal.")
        return on

    def clean_counterparty_rut(self):
        return clean_rut_value(self.cleaned_data.get("counterparty_rut"))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("kind") == Movement.Kind.DEATH and not cleaned.get("cause"):
            self.add_error("cause", "Indica la causa de muerte.")
        if cleaned.get("kind") == Movement.Kind.SALE and cleaned.get("date"):
            treatment = services.active_withdrawal(self.animal, cleaned["date"])
            if treatment:
                self.add_error(
                    "kind",
                    f"El animal está en período de resguardo hasta el {treatment.withdrawal_until:%d-%m-%Y} "
                    f"por {treatment.product}. No puede venderse para faena antes de esa fecha.",
                )
        return cleaned


class WeighingImportForm(forms.Form):
    file = forms.FileField(label="Archivo de la balanza (CSV)", help_text="Máximo 2 MB.")
    date = forms.DateField(
        label="Fecha del pesaje", initial=date.today, widget=DATE_INPUT, validators=[not_in_future],
        help_text="Se usa si el archivo no trae una columna de fecha.",
    )
    method = forms.ChoiceField(label="Método", choices=Weighing.Method.choices, initial=Weighing.Method.SCALE)

    MAX_BYTES = 2 * 1024 * 1024

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > self.MAX_BYTES:
            raise forms.ValidationError("El archivo supera los 2 MB.")
        if not upload.name.lower().endswith((".csv", ".txt")):
            raise forms.ValidationError("Sube un archivo .csv (exporta desde el software de la balanza).")
        return upload


# --- Reproducción -----------------------------------------------------------


class ServiceForm(forms.Form):
    kind = forms.ChoiceField(label="Tipo", choices=Service.Kind.choices)
    date = forms.DateField(label="Fecha", initial=date.today, widget=DATE_INPUT, validators=[not_in_future],
                           help_text="En monta natural, inicio del encaste.")
    bull = forms.ModelChoiceField(label="Toro del predio", queryset=Animal.objects.none(), required=False)
    semen = forms.CharField(label="Pajuela / toro externo", required=False, max_length=60)
    technician = forms.CharField(label="Inseminador / responsable", required=False, max_length=80)
    notes = forms.CharField(label="Observación", required=False, max_length=200)

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bull"].queryset = Animal.objects.for_org(organization).filter(
            status=Animal.Status.ACTIVE, sex=Animal.Sex.MALE, category__in=[C.BULL, C.YOUNG_BULL]
        )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("kind") == Service.Kind.NATURAL and not (cleaned.get("bull") or cleaned.get("semen")):
            self.add_error("bull", "Indica el toro (del predio o externo).")
        if cleaned.get("kind") in (Service.Kind.AI, Service.Kind.ET) and not cleaned.get("semen"):
            self.add_error("semen", "Indica la pajuela o el embrión utilizado.")
        return cleaned


class PregnancyCheckForm(OrganizationScopedForm):
    class Meta:
        model = PregnancyCheck
        fields = ["date", "result", "method", "months_pregnant", "vet", "notes"]
        widgets = {"date": DATE_INPUT}

    def clean_date(self):
        return not_in_future(self.cleaned_data.get("date"))

    def clean(self):
        cleaned = super().clean()
        months = cleaned.get("months_pregnant")
        if months and cleaned.get("result") != PregnancyCheck.Result.PREGNANT:
            self.add_error("months_pregnant", "Solo aplica si el resultado es preñada.")
        if months and months > 9.5:
            self.add_error("months_pregnant", "La gestación bovina dura cerca de 9 meses y medio.")
        return cleaned


class CalvingForm(forms.Form):
    date = forms.DateField(label="Fecha del parto", initial=date.today, widget=DATE_INPUT, validators=[not_in_future])
    ease = forms.ChoiceField(label="Tipo de parto", choices=Calving.Ease.choices)
    stillborn = forms.BooleanField(label="Nació muerto", required=False)
    calf_sex = forms.ChoiceField(label="Sexo de la cría", choices=[("", "---------"), *Animal.Sex.choices],
                                 required=False)
    calf_diio = forms.CharField(label="DIIO de la cría", required=False, max_length=16,
                                help_text="Si aún no tiene crotal, usa la identificación visual.")
    calf_tag = forms.CharField(label="Identificación visual", required=False, max_length=30)
    calf_breed = forms.ModelChoiceField(label="Raza de la cría", queryset=Breed.objects.all(), required=False,
                                        help_text="Vacío: la de la madre.")
    birth_weight = forms.DecimalField(label="Peso al nacer (kg)", required=False, min_value=1, max_value=90,
                                      decimal_places=1)
    notes = forms.CharField(label="Observación", required=False, max_length=200)

    def __init__(self, *args, mother, **kwargs):
        super().__init__(*args, **kwargs)
        self.mother = mother

    def clean_calf_diio(self):
        diio = self.cleaned_data.get("calf_diio", "").strip()
        if diio:
            diio_validator(diio)
            if Animal.objects.for_org(self.mother.organization).filter(diio=diio).exists():
                raise forms.ValidationError("Ya existe un animal con este DIIO.")
        return diio

    def clean_date(self):
        on = self.cleaned_data.get("date")
        if on and self.mother.calvings.filter(date__gt=on - timedelta(days=240), date__lte=on).exists():
            raise forms.ValidationError("Esta hembra ya tiene un parto registrado hace menos de 8 meses.")
        return on

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("stillborn"):
            if not cleaned.get("calf_sex"):
                self.add_error("calf_sex", "Indica el sexo de la cría.")
            if not cleaned.get("calf_diio") and not cleaned.get("calf_tag"):
                self.add_error("calf_tag", "Indica el DIIO o una identificación visual de la cría.")
        return cleaned


class WeaningForm(forms.Form):
    date = forms.DateField(label="Fecha del destete", initial=date.today, widget=DATE_INPUT, validators=[not_in_future])
    weight = forms.DecimalField(label="Peso al destete (kg)", min_value=30, max_value=500, decimal_places=1)
    new_category = forms.ChoiceField(label="Nueva categoría")
    notes = forms.CharField(label="Observación", required=False, max_length=200)

    def __init__(self, *args, calf, **kwargs):
        super().__init__(*args, **kwargs)
        self.calf = calf
        options = [C.HEIFER] if calf.sex == Animal.Sex.FEMALE else [C.YOUNG_BULL, C.STEER]
        self.fields["new_category"].choices = [(c.value, c.label) for c in options]

    def clean_date(self):
        on = self.cleaned_data.get("date")
        if on and self.calf.birth_date and on <= self.calf.birth_date:
            raise forms.ValidationError("El destete debe ser posterior al nacimiento.")
        return on


# --- Sanidad ----------------------------------------------------------------


class HealthProductForm(OrganizationScopedForm):
    class Meta:
        model = HealthProduct
        fields = ["name", "kind", "active_ingredient", "withdrawal_days", "is_active"]


class TreatmentForm(forms.Form):
    product = forms.ModelChoiceField(label="Producto", queryset=HealthProduct.objects.none())
    date = forms.DateField(label="Fecha", initial=date.today, widget=DATE_INPUT, validators=[not_in_future])
    dose = forms.CharField(label="Dosis", required=False, max_length=40, help_text="Ej.: 5 ml subcutáneo.")
    reason = forms.CharField(label="Motivo / diagnóstico", required=False, max_length=120)
    applied_by = forms.CharField(label="Aplicado por", required=False, max_length=80)
    notes = forms.CharField(label="Observación", required=False, max_length=200)

    def __init__(self, *args, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = HealthProduct.objects.for_org(organization).filter(is_active=True)


# --- Alimentación y costos --------------------------------------------------


class FeedItemForm(OrganizationScopedForm):
    class Meta:
        model = FeedItem
        fields = ["name", "kind", "unit", "unit_cost", "is_active"]
        help_texts = {"unit": ""}


class PriceReferenceForm(OrganizationScopedForm):
    class Meta:
        model = PriceReference
        fields = ["category", "price_per_kg", "date"]
        widgets = {"date": DATE_INPUT}


class CostForm(OrganizationScopedForm):
    """Costo del rebaño. Con alimento y cantidad, el monto se calcula si se deja vacío."""

    class Meta:
        model = Cost
        fields = ["date", "category", "feed_item", "quantity", "amount", "description", "target", "lot"]
        widgets = {"date": DATE_INPUT}
        help_texts = {"amount": "Si eliges un alimento e indicas la cantidad, puedes dejarlo vacío."}

    def __init__(self, *args, preselected=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.preselected = preselected
        self.fields["amount"].required = False
        self.fields["feed_item"].queryset = self.fields["feed_item"].queryset.filter(is_active=True)
        self.fields["lot"].queryset = self.fields["lot"].queryset.filter(is_active=True)
        targets = Cost.Target.choices
        if preselected:
            self.fields["target"].initial = Cost.Target.SELECTED
            self.fields["target"].widget = forms.HiddenInput()
        else:
            targets = [t for t in targets if t[0] != Cost.Target.SELECTED]
        self.fields["target"].choices = targets

    def clean_date(self):
        return not_in_future(self.cleaned_data.get("date"))

    def clean(self):
        cleaned = super().clean()
        item, qty, amount = cleaned.get("feed_item"), cleaned.get("quantity"), cleaned.get("amount")
        if item and cleaned.get("category") != Cost.Category.FEED:
            self.add_error("feed_item", "El alimento solo aplica a costos de alimentación.")
        if amount is None:
            if item and qty:
                cleaned["amount"] = self.instance.amount = (item.unit_cost * qty).quantize(Decimal("1"))
            else:
                self.add_error("amount", "Indica el monto, o el alimento y la cantidad.")
        target = cleaned.get("target")
        if target == Cost.Target.LOT and not cleaned.get("lot"):
            self.add_error("lot", "Elige el lote.")
        if target == Cost.Target.SELECTED and not self.preselected:
            self.add_error("target", "Selecciona los animales en el listado.")
        return cleaned


# --- Mapas ------------------------------------------------------------------


class BoundaryForm(forms.Form):
    geojson = forms.CharField(widget=forms.HiddenInput, required=False)
    update_area = forms.BooleanField(label="Usar la superficie calculada del polígono", required=False, initial=True)

    def clean_geojson(self):
        text = self.cleaned_data["geojson"].strip()
        if not text:
            raise forms.ValidationError("Dibuja el polígono en el mapa (al menos 3 puntos) o importa un KML.")
        try:
            return clean_polygon(json.loads(text))
        except (ValueError, GeometryError) as e:
            raise forms.ValidationError(str(e) if isinstance(e, GeometryError) else "Polígono no válido.") from e


class KmlForm(forms.Form):
    file = forms.FileField(label="Archivo de Google Earth (.kml o .kmz)", help_text="Máximo 5 MB.")

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if upload.size > 5 * 1024 * 1024:
            raise forms.ValidationError("El archivo supera los 5 MB.")
        if not upload.name.lower().endswith((".kml", ".kmz")):
            raise forms.ValidationError("Sube un archivo .kml o .kmz exportado desde Google Earth.")
        return upload
