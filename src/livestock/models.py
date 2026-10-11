"""Ganadería bovina: cría y engorda.

Predios (con su RUP del SAG) y potreros, lotes de manejo, animales
identificados por DIIO, pesajes y movimientos (ingresos, traslados y salidas).
Todo pertenece a una organización (cliente) salvo el catálogo de razas.
"""

from datetime import date, timedelta

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models

from organizations.models import OrganizationScopedModel


class Breed(models.Model):
    """Catálogo común de razas (lo mantiene el sistema, no cada cliente)."""

    class Purpose(models.TextChoices):
        BEEF = "beef", "Carne"
        DAIRY = "dairy", "Leche"
        DUAL = "dual", "Doble propósito"
        OTHER = "other", "Otro"

    name = models.CharField("nombre", max_length=60, unique=True)
    purpose = models.CharField("propósito", max_length=10, choices=Purpose.choices)
    order = models.PositiveSmallIntegerField("orden", default=100)

    class Meta:
        verbose_name = "raza"
        verbose_name_plural = "razas"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class Farm(OrganizationScopedModel):
    name = models.CharField("nombre", max_length=120)
    rup = models.CharField(
        "RUP", max_length=20, blank=True, help_text="Rol Único Pecuario asignado por el SAG (ej.: 08.1.01.0001)."
    )
    commune = models.CharField("comuna", max_length=80, blank=True)
    area_ha = models.DecimalField(
        "superficie (ha)", max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    notes = models.TextField("notas", blank=True)

    class Meta:
        verbose_name = "predio"
        verbose_name_plural = "predios"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="livestock_farm_name_unique"),
        ]

    def __str__(self):
        return self.name


class Paddock(OrganizationScopedModel):
    farm = models.ForeignKey(Farm, verbose_name="predio", on_delete=models.CASCADE, related_name="paddocks")
    name = models.CharField("nombre", max_length=80)
    area_ha = models.DecimalField(
        "superficie (ha)", max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)]
    )

    class Meta:
        verbose_name = "potrero"
        verbose_name_plural = "potreros"
        ordering = ["farm__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["farm", "name"], name="livestock_paddock_name_unique"),
        ]

    def __str__(self):
        return f"{self.farm} · {self.name}"


class Lot(OrganizationScopedModel):
    """Grupo de manejo (ej.: 'Vaquillas 2025', 'Engorda invierno')."""

    class Purpose(models.TextChoices):
        BREEDING = "breeding", "Cría"
        REARING = "rearing", "Recría"
        FATTENING = "fattening", "Engorda"
        OTHER = "other", "Otro"

    name = models.CharField("nombre", max_length=80)
    purpose = models.CharField("propósito", max_length=10, choices=Purpose.choices, default=Purpose.FATTENING)
    is_active = models.BooleanField("activo", default=True)
    notes = models.TextField("notas", blank=True)

    class Meta:
        verbose_name = "lote"
        verbose_name_plural = "lotes"
        ordering = ["-is_active", "name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="livestock_lot_name_unique"),
        ]

    def __str__(self):
        return self.name


diio_validator = RegexValidator(r"^\d{6,16}$", "El DIIO debe tener solo dígitos (entre 6 y 16).")


class Animal(OrganizationScopedModel):
    class Sex(models.TextChoices):
        FEMALE = "F", "Hembra"
        MALE = "M", "Macho"

    class Category(models.TextChoices):
        CALF_F = "ternera", "Ternera"
        CALF_M = "ternero", "Ternero"
        HEIFER = "vaquilla", "Vaquilla"
        COW = "vaca", "Vaca"
        YOUNG_BULL = "torete", "Torete"
        STEER = "novillo", "Novillo"
        BULL = "toro", "Toro"
        OX = "buey", "Buey"

    class Origin(models.TextChoices):
        BORN = "born", "Nacido en el predio"
        PURCHASED = "purchased", "Comprado"
        INITIAL = "initial", "Inventario inicial"

    class Status(models.TextChoices):
        ACTIVE = "active", "En existencia"
        SOLD = "sold", "Vendido"
        DEAD = "dead", "Muerto"
        OTHER_EXIT = "other_exit", "Otra salida"

    diio = models.CharField(
        "DIIO", max_length=16, blank=True, validators=[diio_validator],
        help_text="Número del dispositivo oficial (crotal) del SAG. Déjalo vacío si el animal aún no tiene.",
    )
    tag = models.CharField("identificación visual", max_length=30, blank=True, help_text="Autocrotal, nombre o marca.")
    sex = models.CharField("sexo", max_length=1, choices=Sex.choices)
    category = models.CharField("categoría", max_length=10, choices=Category.choices)
    breed = models.ForeignKey(Breed, verbose_name="raza", on_delete=models.PROTECT, null=True, blank=True)
    birth_date = models.DateField("fecha de nacimiento", null=True, blank=True)
    birth_date_estimated = models.BooleanField("fecha estimada", default=False)
    mother = models.ForeignKey(
        "self", verbose_name="madre", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="offspring", limit_choices_to={"sex": "F"},
    )
    sire = models.CharField(
        "padre", max_length=60, blank=True, help_text="DIIO o nombre del toro, o código de pajuela."
    )
    origin = models.CharField("origen", max_length=10, choices=Origin.choices)
    entry_date = models.DateField("fecha de ingreso", default=date.today)
    status = models.CharField("estado", max_length=10, choices=Status.choices, default=Status.ACTIVE, editable=False)
    exit_date = models.DateField("fecha de salida", null=True, blank=True, editable=False)
    farm = models.ForeignKey(Farm, verbose_name="predio", on_delete=models.PROTECT, related_name="animals")
    paddock = models.ForeignKey(
        Paddock, verbose_name="potrero", on_delete=models.SET_NULL, null=True, blank=True, related_name="animals"
    )
    lot = models.ForeignKey(
        Lot, verbose_name="lote", on_delete=models.SET_NULL, null=True, blank=True, related_name="animals"
    )
    notes = models.TextField("notas", blank=True)
    created_at = models.DateTimeField("creado el", auto_now_add=True)

    class Meta:
        verbose_name = "animal"
        verbose_name_plural = "animales"
        ordering = ["diio", "tag"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "diio"], condition=~models.Q(diio=""), name="livestock_animal_diio_unique"
            ),
            models.CheckConstraint(condition=~models.Q(diio="", tag=""), name="livestock_animal_has_identification"),
        ]
        indexes = [models.Index(fields=["organization", "status", "category"])]

    def __str__(self):
        return self.diio or self.tag

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    def age_months(self, on=None):
        if not self.birth_date:
            return None
        on = on or date.today()
        return (on.year - self.birth_date.year) * 12 + on.month - self.birth_date.month - (on.day < self.birth_date.day)


class Weighing(OrganizationScopedModel):
    class Method(models.TextChoices):
        MANUAL = "manual", "Manual"
        SCALE = "scale", "Balanza electrónica"

    animal = models.ForeignKey(Animal, verbose_name="animal", on_delete=models.CASCADE, related_name="weighings")
    date = models.DateField("fecha", default=date.today)
    weight_kg = models.DecimalField("peso (kg)", max_digits=6, decimal_places=1, validators=[MinValueValidator(1)])
    method = models.CharField("método", max_length=10, choices=Method.choices, default=Method.MANUAL)
    notes = models.CharField("observación", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="registrado por", on_delete=models.SET_NULL, null=True, editable=False,
        related_name="+",
    )
    created_at = models.DateTimeField("registrado el", auto_now_add=True)

    class Meta:
        verbose_name = "pesaje"
        verbose_name_plural = "pesajes"
        ordering = ["-date", "-created_at"]
        indexes = [models.Index(fields=["organization", "date"])]

    def __str__(self):
        return f"{self.animal} · {self.weight_kg} kg ({self.date:%d-%m-%Y})"


class Movement(OrganizationScopedModel):
    """Historial de ingresos, traslados y salidas de cada animal."""

    class Kind(models.TextChoices):
        BIRTH = "birth", "Nacimiento"
        PURCHASE = "purchase", "Compra"
        INITIAL = "initial", "Inventario inicial"
        TRANSFER = "transfer", "Traslado"
        SALE = "sale", "Venta"
        DEATH = "death", "Muerte"
        OTHER_EXIT = "other_exit", "Otra salida"

    ENTRY_KINDS = {Kind.BIRTH, Kind.PURCHASE, Kind.INITIAL}
    EXIT_KINDS = {Kind.SALE, Kind.DEATH, Kind.OTHER_EXIT}

    animal = models.ForeignKey(Animal, verbose_name="animal", on_delete=models.CASCADE, related_name="movements")
    kind = models.CharField("tipo", max_length=10, choices=Kind.choices)
    date = models.DateField("fecha", default=date.today)
    from_farm = models.ForeignKey(
        Farm, verbose_name="predio de origen", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    from_paddock = models.ForeignKey(
        Paddock, verbose_name="potrero de origen", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    to_farm = models.ForeignKey(
        Farm, verbose_name="predio de destino", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    to_paddock = models.ForeignKey(
        Paddock, verbose_name="potrero de destino", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    counterparty = models.CharField("comprador / vendedor", max_length=120, blank=True)
    counterparty_rut = models.CharField("RUT contraparte", max_length=12, blank=True)
    fma = models.CharField("N° FMA", max_length=30, blank=True, help_text="Formulario de Movimiento Animal del SAG.")
    weight_kg = models.DecimalField(
        "peso (kg)", max_digits=6, decimal_places=1, null=True, blank=True, validators=[MinValueValidator(1)]
    )
    price_clp = models.DecimalField(
        "monto total ($)", max_digits=14, decimal_places=0, null=True, blank=True, validators=[MinValueValidator(0)]
    )
    cause = models.CharField("causa", max_length=120, blank=True, help_text="Causa de muerte u otra salida.")
    notes = models.CharField("observación", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="registrado por", on_delete=models.SET_NULL, null=True, editable=False,
        related_name="+",
    )
    created_at = models.DateTimeField("registrado el", auto_now_add=True)

    class Meta:
        verbose_name = "movimiento"
        verbose_name_plural = "movimientos"
        ordering = ["-date", "-created_at"]
        indexes = [models.Index(fields=["organization", "kind", "date"])]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.animal} ({self.date:%d-%m-%Y})"


# --- Reproducción -----------------------------------------------------------

GESTATION_DAYS = 283  # gestación bovina promedio


class Service(OrganizationScopedModel):
    """Servicio reproductivo de una hembra (encaste)."""

    class Kind(models.TextChoices):
        NATURAL = "natural", "Monta natural"
        AI = "ai", "Inseminación artificial"
        ET = "et", "Transferencia de embriones"

    female = models.ForeignKey(Animal, verbose_name="hembra", on_delete=models.CASCADE, related_name="services")
    kind = models.CharField("tipo", max_length=10, choices=Kind.choices, default=Kind.NATURAL)
    date = models.DateField("fecha", default=date.today, help_text="En monta natural, inicio del encaste.")
    bull = models.ForeignKey(
        Animal, verbose_name="toro", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    semen = models.CharField("pajuela / toro externo", max_length=60, blank=True)
    technician = models.CharField("inseminador / responsable", max_length=80, blank=True)
    notes = models.CharField("observación", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "servicio"
        verbose_name_plural = "servicios"
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.female} ({self.date:%d-%m-%Y})"

    @property
    def sire_label(self):
        return str(self.bull) if self.bull_id else self.semen


class PregnancyCheck(OrganizationScopedModel):
    class Result(models.TextChoices):
        PREGNANT = "pregnant", "Preñada"
        EMPTY = "empty", "Vacía"
        DOUBTFUL = "doubtful", "Dudosa"

    class Method(models.TextChoices):
        PALPATION = "palpation", "Palpación rectal"
        ULTRASOUND = "ultrasound", "Ecografía"
        OTHER = "other", "Otro"

    female = models.ForeignKey(
        Animal, verbose_name="hembra", on_delete=models.CASCADE, related_name="pregnancy_checks"
    )
    date = models.DateField("fecha", default=date.today)
    result = models.CharField("resultado", max_length=10, choices=Result.choices)
    method = models.CharField("método", max_length=10, choices=Method.choices, default=Method.ULTRASOUND)
    months_pregnant = models.DecimalField(
        "meses de gestación", max_digits=3, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(1)], help_text="Estimación del veterinario; se usa para la fecha de parto.",
    )
    expected_calving = models.DateField("parto probable", null=True, blank=True, editable=False)
    vet = models.CharField("veterinario", max_length=80, blank=True)
    notes = models.CharField("observación", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "diagnóstico de preñez"
        verbose_name_plural = "diagnósticos de preñez"
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.female}: {self.get_result_display()} ({self.date:%d-%m-%Y})"

    def save(self, *args, **kwargs):
        self.expected_calving = None
        if self.result == self.Result.PREGNANT:
            if self.months_pregnant:
                elapsed = int(float(self.months_pregnant) * 30.4)
                self.expected_calving = self.date + timedelta(days=GESTATION_DAYS - elapsed)
            else:
                service = self.female.services.filter(date__lte=self.date).order_by("-date").first()
                if service:
                    self.expected_calving = service.date + timedelta(days=GESTATION_DAYS)
        super().save(*args, **kwargs)


class Calving(OrganizationScopedModel):
    class Ease(models.TextChoices):
        NORMAL = "normal", "Normal"
        ASSISTED = "assisted", "Asistido"
        DYSTOCIA = "dystocia", "Distócico"
        CESAREAN = "cesarean", "Cesárea"

    mother = models.ForeignKey(Animal, verbose_name="madre", on_delete=models.CASCADE, related_name="calvings")
    date = models.DateField("fecha", default=date.today)
    ease = models.CharField("tipo de parto", max_length=10, choices=Ease.choices, default=Ease.NORMAL)
    calf = models.OneToOneField(
        Animal, verbose_name="cría", on_delete=models.SET_NULL, null=True, blank=True, related_name="birth_record"
    )
    stillborn = models.BooleanField("nacido muerto", default=False)
    birth_weight_kg = models.DecimalField(
        "peso al nacer (kg)", max_digits=5, decimal_places=1, null=True, blank=True, validators=[MinValueValidator(1)]
    )
    notes = models.CharField("observación", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "parto"
        verbose_name_plural = "partos"
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"Parto de {self.mother} ({self.date:%d-%m-%Y})"


class Weaning(OrganizationScopedModel):
    calf = models.OneToOneField(Animal, verbose_name="cría", on_delete=models.CASCADE, related_name="weaning")
    date = models.DateField("fecha", default=date.today)
    weight_kg = models.DecimalField(
        "peso al destete (kg)", max_digits=6, decimal_places=1, validators=[MinValueValidator(1)]
    )
    notes = models.CharField("observación", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "destete"
        verbose_name_plural = "destetes"
        ordering = ["-date"]

    def __str__(self):
        return f"Destete de {self.calf} ({self.date:%d-%m-%Y})"

    @property
    def age_days(self):
        birth = self.calf.birth_date
        return (self.date - birth).days if birth else None

    @property
    def adjusted_205(self):
        """Peso ajustado a 205 días (estándar BIF): compara terneros destetados a distinta edad."""
        days = self.age_days
        if not days or days < 120 or days > 300:
            return None
        record = getattr(self.calf, "birth_record", None)
        birth = float(record.birth_weight_kg) if record and record.birth_weight_kg else 35.0
        return (float(self.weight_kg) - birth) / days * 205 + birth


# --- Sanidad ----------------------------------------------------------------


class HealthProduct(OrganizationScopedModel):
    class Kind(models.TextChoices):
        VACCINE = "vaccine", "Vacuna"
        ANTIPARASITIC = "antiparasitic", "Antiparasitario"
        ANTIBIOTIC = "antibiotic", "Antibiótico"
        ANTIINFLAMMATORY = "antiinflammatory", "Antiinflamatorio"
        VITAMIN = "vitamin", "Vitaminas y minerales"
        HORMONE = "hormone", "Hormonal / reproductivo"
        OTHER = "other", "Otro"

    name = models.CharField("nombre comercial", max_length=100)
    kind = models.CharField("tipo", max_length=20, choices=Kind.choices)
    active_ingredient = models.CharField("principio activo", max_length=120, blank=True)
    withdrawal_days = models.PositiveSmallIntegerField(
        "resguardo carne (días)", default=0, help_text="Días desde la aplicación en que el animal no puede faenarse."
    )
    is_active = models.BooleanField("en uso", default=True)

    class Meta:
        verbose_name = "producto veterinario"
        verbose_name_plural = "productos veterinarios"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="livestock_healthproduct_name_unique"),
        ]

    def __str__(self):
        return self.name


class Treatment(OrganizationScopedModel):
    animal = models.ForeignKey(Animal, verbose_name="animal", on_delete=models.CASCADE, related_name="treatments")
    product = models.ForeignKey(HealthProduct, verbose_name="producto", on_delete=models.PROTECT, related_name="+")
    date = models.DateField("fecha", default=date.today)
    dose = models.CharField("dosis", max_length=40, blank=True)
    reason = models.CharField("motivo / diagnóstico", max_length=120, blank=True)
    applied_by = models.CharField("aplicado por", max_length=80, blank=True)
    withdrawal_until = models.DateField("resguardo hasta", null=True, blank=True, editable=False)
    notes = models.CharField("observación", max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "tratamiento"
        verbose_name_plural = "tratamientos"
        ordering = ["-date", "-created_at"]
        indexes = [models.Index(fields=["organization", "withdrawal_until"])]

    def __str__(self):
        return f"{self.product} · {self.animal} ({self.date:%d-%m-%Y})"

    def save(self, *args, **kwargs):
        days = self.product.withdrawal_days
        self.withdrawal_until = self.date + timedelta(days=days) if days else None
        super().save(*args, **kwargs)


# --- Alimentación y costos --------------------------------------------------


class FeedItem(OrganizationScopedModel):
    class Kind(models.TextChoices):
        CONCENTRATE = "concentrate", "Concentrado"
        FORAGE = "forage", "Forraje (heno, ensilaje)"
        MINERAL = "mineral", "Sales minerales"
        GRAZING = "grazing", "Pradera / talaje"
        OTHER = "other", "Otro"

    name = models.CharField("nombre", max_length=100)
    kind = models.CharField("tipo", max_length=15, choices=Kind.choices)
    unit = models.CharField("unidad", max_length=20, default="kg", help_text="kg, fardo, saco, tonelada, día...")
    unit_cost = models.DecimalField("costo por unidad ($)", max_digits=12, decimal_places=2,
                                    validators=[MinValueValidator(0)])
    is_active = models.BooleanField("en uso", default=True)

    class Meta:
        verbose_name = "alimento"
        verbose_name_plural = "alimentos"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "name"], name="livestock_feeditem_name_unique"),
        ]

    def __str__(self):
        return f"{self.name} ({self.unit})"


class Cost(OrganizationScopedModel):
    """Costo del rebaño. Si se asigna a animales, se reparte en partes iguales (CostAllocation)."""

    class Category(models.TextChoices):
        FEED = "feed", "Alimentación"
        HEALTH = "health", "Sanidad"
        VET = "vet", "Servicios veterinarios"
        LABOR = "labor", "Mano de obra"
        FREIGHT = "freight", "Fletes"
        COMMISSION = "commission", "Comisión de feria"
        LEASE = "lease", "Arriendo / talaje"
        OTHER = "other", "Otros"

    class Target(models.TextChoices):
        LOT = "lot", "Un lote"
        SELECTED = "selected", "Animales seleccionados"
        HERD = "herd", "Todo el rebaño en existencia"
        GENERAL = "general", "Gasto general (no se asigna a animales)"

    date = models.DateField("fecha", default=date.today)
    category = models.CharField("categoría", max_length=12, choices=Category.choices)
    description = models.CharField("descripción", max_length=150, blank=True)
    feed_item = models.ForeignKey(
        FeedItem, verbose_name="alimento", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    quantity = models.DecimalField("cantidad", max_digits=12, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField("monto total ($)", max_digits=14, decimal_places=0, validators=[MinValueValidator(0)])
    target = models.CharField("asignado a", max_length=10, choices=Target.choices)
    lot = models.ForeignKey(Lot, verbose_name="lote", on_delete=models.SET_NULL, null=True, blank=True,
                            related_name="costs")
    heads = models.PositiveIntegerField("cabezas", default=0, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "costo"
        verbose_name_plural = "costos"
        ordering = ["-date", "-created_at"]
        indexes = [models.Index(fields=["organization", "date"])]

    def __str__(self):
        return f"{self.get_category_display()} · ${self.amount:,.0f} ({self.date:%d-%m-%Y})".replace(",", ".")

    @property
    def per_head(self):
        return self.amount / self.heads if self.heads else None


class CostAllocation(OrganizationScopedModel):
    cost = models.ForeignKey(Cost, on_delete=models.CASCADE, related_name="allocations")
    animal = models.ForeignKey(Animal, on_delete=models.CASCADE, related_name="cost_allocations")
    amount = models.DecimalField("monto ($)", max_digits=14, decimal_places=2)

    class Meta:
        verbose_name = "costo asignado"
        verbose_name_plural = "costos asignados"


class PriceReference(OrganizationScopedModel):
    """Precio de referencia por kg vivo para valorizar animales en existencia."""

    category = models.CharField("categoría", max_length=10, choices=Animal.Category.choices)
    price_per_kg = models.DecimalField("precio por kg vivo ($)", max_digits=8, decimal_places=0,
                                       validators=[MinValueValidator(1)])
    date = models.DateField("vigente desde", default=date.today)

    class Meta:
        verbose_name = "precio de referencia"
        verbose_name_plural = "precios de referencia"
        ordering = ["category", "-date"]

    def __str__(self):
        return f"{self.get_category_display()}: ${self.price_per_kg}/kg"
