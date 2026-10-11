"""Ganadería bovina: cría y engorda.

Predios (con su RUP del SAG) y potreros, lotes de manejo, animales
identificados por DIIO, pesajes y movimientos (ingresos, traslados y salidas).
Todo pertenece a una organización (cliente) salvo el catálogo de razas.
"""

from datetime import date

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
