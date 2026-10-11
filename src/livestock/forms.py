from datetime import date

from django import forms

from accounts.validators import normalize_rut, validate_rut
from livestock.models import Animal, Farm, Lot, Movement, Paddock, Weighing
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
