"""Operaciones de ganadería que cambian el estado de los animales.

Cada ingreso, traslado o salida deja un Movement como historial; las vistas
no modifican predio, potrero ni estado de un animal por otro camino.
"""

import csv
import io
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from django.db import models, transaction
from django.db.models import Count

from livestock.models import (
    Animal,
    Calving,
    CostAllocation,
    Movement,
    PregnancyCheck,
    PriceReference,
    Service,
    Treatment,
    Weaning,
    Weighing,
)

ORIGIN_TO_KIND = {
    Animal.Origin.BORN: Movement.Kind.BIRTH,
    Animal.Origin.PURCHASED: Movement.Kind.PURCHASE,
    Animal.Origin.INITIAL: Movement.Kind.INITIAL,
}
EXIT_TO_STATUS = {
    Movement.Kind.SALE: Animal.Status.SOLD,
    Movement.Kind.DEATH: Animal.Status.DEAD,
    Movement.Kind.OTHER_EXIT: Animal.Status.OTHER_EXIT,
}


@transaction.atomic
def register_animal(animal, user, *, entry_weight=None, counterparty="", counterparty_rut="", price=None, fma=""):
    """Guarda un animal nuevo con su movimiento de ingreso (y su primer pesaje, si se indica)."""
    animal.save()
    Movement.objects.create(
        organization=animal.organization, animal=animal, kind=ORIGIN_TO_KIND[animal.origin], date=animal.entry_date,
        to_farm=animal.farm, to_paddock=animal.paddock, counterparty=counterparty, counterparty_rut=counterparty_rut,
        price_clp=price, fma=fma, weight_kg=entry_weight, created_by=user,
    )
    if entry_weight:
        Weighing.objects.create(
            organization=animal.organization, animal=animal, date=animal.entry_date, weight_kg=entry_weight,
            created_by=user,
        )
    return animal


@transaction.atomic
def transfer(animals, user, *, on, to_farm, to_paddock=None, lot=None, fma="", notes=""):
    """Traslada animales activos a otro predio/potrero; opcionalmente los cambia de lote."""
    moved = 0
    for animal in animals:
        if not animal.is_active:
            continue
        Movement.objects.create(
            organization=animal.organization, animal=animal, kind=Movement.Kind.TRANSFER, date=on,
            from_farm_id=animal.farm_id, from_paddock_id=animal.paddock_id, to_farm=to_farm, to_paddock=to_paddock,
            fma=fma, notes=notes, created_by=user,
        )
        animal.farm, animal.paddock = to_farm, to_paddock
        if lot is not None:
            animal.lot = lot
        animal.save(update_fields=["farm", "paddock", "lot"])
        moved += 1
    return moved


@transaction.atomic
def register_exit(animal, movement, user):
    """Venta, muerte u otra salida: el animal deja de estar en existencia."""
    movement.organization = animal.organization
    movement.animal = animal
    movement.from_farm_id, movement.from_paddock_id = animal.farm_id, animal.paddock_id
    movement.created_by = user
    movement.save()
    if movement.weight_kg:
        Weighing.objects.create(
            organization=animal.organization, animal=animal, date=movement.date, weight_kg=movement.weight_kg,
            notes=f"Peso de {movement.get_kind_display().lower()}", created_by=user,
        )
    animal.status = EXIT_TO_STATUS[movement.kind]
    animal.exit_date = movement.date
    animal.save(update_fields=["status", "exit_date"])
    return movement


# --- Ganancia diaria de peso (GDP) ------------------------------------------


def daily_gain(first, last):
    """kg/día entre dos pesajes (fecha, kg). None si no hay días entre ellos."""
    days = (last[0] - first[0]).days
    if days <= 0:
        return None
    return float(last[1] - first[1]) / days


def weighing_history(animal):
    """Pesajes del más antiguo al más reciente, cada uno con la GDP respecto del anterior."""
    rows, previous = [], None
    for w in animal.weighings.order_by("date", "created_at"):
        gain = daily_gain(previous, (w.date, w.weight_kg)) if previous else None
        rows.append({"weighing": w, "gain": gain})
        previous = (w.date, w.weight_kg)
    return rows


def herd_daily_gain(organization, days=180):
    """GDP promedio por lote de los animales activos con 2 o más pesajes en el período."""
    since = date.today() - timedelta(days=days)
    series = defaultdict(list)
    rows = (
        Weighing.objects.for_org(organization)
        .filter(date__gte=since, animal__status=Animal.Status.ACTIVE)
        .order_by("animal_id", "date", "created_at")
        .values_list("animal_id", "animal__lot__name", "date", "weight_kg")
    )
    lot_of = {}
    for animal_id, lot_name, on, kg in rows:
        series[animal_id].append((on, kg))
        lot_of[animal_id] = lot_name or "Sin lote"
    by_lot = defaultdict(list)
    for animal_id, points in series.items():
        gain = daily_gain(points[0], points[-1]) if len(points) > 1 else None
        if gain is not None:
            by_lot[lot_of[animal_id]].append(gain)
    all_gains = [g for gains in by_lot.values() for g in gains]
    return {
        "average": sum(all_gains) / len(all_gains) if all_gains else None,
        "animals": len(all_gains),
        "by_lot": sorted(((lot, sum(g) / len(g), len(g)) for lot, g in by_lot.items()), key=lambda r: -r[1]),
    }


def stock_by_category(organization):
    counts = dict(
        Animal.objects.for_org(organization)
        .filter(status=Animal.Status.ACTIVE)
        .order_by()
        .values_list("category")
        .annotate(n=Count("id"))
    )
    return [(label, counts[value]) for value, label in Animal.Category.choices if counts.get(value)]


# --- Importación de pesajes desde la balanza --------------------------------

ID_COLUMNS = {"diio", "eid", "rfid", "caravana", "crotal", "id", "vid", "identificacion", "animal"}
WEIGHT_COLUMNS = {"peso", "weight", "kg", "pesokg"}
DATE_COLUMNS = {"fecha", "date", "dia"}
DATE_FORMATS = ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%d/%m/%y", "%Y/%m/%d"]


def _norm(header):
    header = header.strip().lower()
    for a, b in zip("áéíóú", "aeiou", strict=True):
        header = header.replace(a, b)
    return re.sub(r"[^a-z]", "", header)


def _parse_date(text):
    text = text.strip().split(" ")[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_weight(text):
    text = text.strip().replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if 0 < value < 5000 else None


@dataclass
class ImportResult:
    created: int = 0
    unknown: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def read_scale_file(data):
    """Lee el CSV exportado por la balanza: columnas de identificación, peso y (opcional) fecha.

    Acepta separador coma, punto y coma o tabulación; decimales con coma o punto.
    Devuelve (filas, error) con filas = [(nro_linea, identificacion, peso_texto, fecha_texto)].
    """
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    header = next(reader, None)
    if not header:
        return [], "El archivo está vacío."
    names = [_norm(h) for h in header]
    id_col, weight_col, date_col = (
        next((i for i, n in enumerate(names) if n in options), None)
        for options in (ID_COLUMNS, WEIGHT_COLUMNS, DATE_COLUMNS)
    )
    if id_col is None or weight_col is None:
        return [], "No se encontraron las columnas de identificación (DIIO/EID) y peso en la primera fila."
    rows = []
    for number, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        cells = [row[i].strip() if i is not None and i < len(row) else "" for i in (id_col, weight_col, date_col)]
        rows.append((number, *cells))
    return rows, None


@transaction.atomic
def import_weighings(organization, user, rows, *, default_date, method=Weighing.Method.SCALE):
    """Crea los pesajes de animales activos encontrados por DIIO o identificación visual."""
    result = ImportResult()
    animals = Animal.objects.for_org(organization).filter(status=Animal.Status.ACTIVE)
    by_diio = {a.diio: a for a in animals if a.diio}
    by_tag = {a.tag.lower(): a for a in animals if a.tag}
    to_create = []
    for number, ident, weight_text, date_text in rows:
        digits = re.sub(r"\D", "", ident)
        # Las balanzas suelen anteponer el código de país (152) y ceros al EID de 15 dígitos.
        animal = by_diio.get(digits) or by_diio.get(digits.lstrip("0")) or by_tag.get(ident.lower())
        if animal is None and len(digits) == 15:
            animal = by_diio.get(digits[3:].lstrip("0"))
        if animal is None:
            result.unknown.append(ident or f"línea {number}")
            continue
        weight = _parse_weight(weight_text)
        on = _parse_date(date_text) if date_text else default_date
        if weight is None or on is None:
            result.errors.append(f"Línea {number}: peso o fecha no válidos ({weight_text!r}, {date_text!r}).")
            continue
        to_create.append(
            Weighing(organization=organization, animal=animal, date=on, weight_kg=weight, method=method,
                     created_by=user)
        )
    Weighing.objects.bulk_create(to_create)
    result.created = len(to_create)
    return result


# --- Reproducción -----------------------------------------------------------

BREEDING_CATEGORIES = {Animal.Category.HEIFER, Animal.Category.COW}


def register_services(females, user, *, kind, on, bull=None, semen="", technician="", notes=""):
    """Registra el servicio (encaste o IA) de varias hembras en edad reproductiva."""
    services = [
        Service(organization=f.organization, female=f, kind=kind, date=on, bull=bull, semen=semen,
                technician=technician, notes=notes, created_by=user)
        for f in females
        if f.is_active and f.category in BREEDING_CATEGORIES
    ]
    Service.objects.bulk_create(services)
    return len(services)


@transaction.atomic
def register_calving(mother, user, *, on, ease, stillborn, calf_sex=None, calf_diio="", calf_tag="",
                     calf_breed=None, birth_weight=None, notes=""):
    """Parto: crea la cría (si nació viva) con su nacimiento, y la vaquilla pasa a vaca."""
    calf = None
    if not stillborn:
        calf = Animal(
            organization=mother.organization, diio=calf_diio, tag=calf_tag, sex=calf_sex,
            category=Animal.Category.CALF_F if calf_sex == Animal.Sex.FEMALE else Animal.Category.CALF_M,
            breed=calf_breed or mother.breed, birth_date=on, mother=mother, origin=Animal.Origin.BORN,
            entry_date=on, farm=mother.farm, paddock=mother.paddock,
        )
        sire = mother.services.filter(date__lte=on).order_by("-date").first()
        if sire:
            calf.sire = sire.sire_label[:60]
        register_animal(calf, user, entry_weight=birth_weight)
    calving = Calving.objects.create(
        organization=mother.organization, mother=mother, date=on, ease=ease, calf=calf, stillborn=stillborn,
        birth_weight_kg=birth_weight, notes=notes, created_by=user,
    )
    if mother.category == Animal.Category.HEIFER:
        mother.category = Animal.Category.COW
        mother.save(update_fields=["category"])
    return calving


WEANED_CATEGORY = {Animal.Category.CALF_F: Animal.Category.HEIFER, Animal.Category.CALF_M: Animal.Category.YOUNG_BULL}


@transaction.atomic
def register_weaning(calf, user, *, on, weight, new_category=None, notes=""):
    weaning = Weaning.objects.create(
        organization=calf.organization, calf=calf, date=on, weight_kg=weight, notes=notes, created_by=user
    )
    Weighing.objects.create(
        organization=calf.organization, animal=calf, date=on, weight_kg=weight, notes="Peso al destete",
        created_by=user,
    )
    calf.category = new_category or WEANED_CATEGORY.get(calf.category, calf.category)
    calf.save(update_fields=["category"])
    return weaning


def latest_checks(organization):
    """Último diagnóstico de cada hembra activa: {female_id: PregnancyCheck}."""
    checks = (
        PregnancyCheck.objects.for_org(organization)
        .filter(female__status=Animal.Status.ACTIVE)
        .select_related("female")
        .order_by("female_id", "-date", "-created_at")
        .distinct("female_id")
    )
    return {c.female_id: c for c in checks}


def reproduction_summary(organization, today=None):
    today = today or date.today()
    year_ago = today - timedelta(days=365)
    females = Animal.objects.for_org(organization).filter(
        status=Animal.Status.ACTIVE, category__in=BREEDING_CATEGORIES
    )
    latest = latest_checks(organization)
    # Partos posteriores al diagnóstico cierran la preñez.
    last_calving = dict(
        Calving.objects.for_org(organization).order_by().values_list("mother_id").annotate(d=models.Max("date"))
    )
    open_pregnancies = [
        c for c in latest.values()
        if c.result == PregnancyCheck.Result.PREGNANT and not (last_calving.get(c.female_id, date.min) >= c.date)
    ]
    recent = [c for c in latest.values() if c.date >= year_ago]
    pregnant_recent = [c for c in recent if c.result == PregnancyCheck.Result.PREGNANT]

    last_service = dict(
        Service.objects.for_org(organization).order_by().values_list("female_id").annotate(d=models.Max("date"))
    )
    pending = [
        f for f in females.select_related("farm")
        if (served := last_service.get(f.pk)) and served <= today - timedelta(days=35)
        and (f.pk not in latest or latest[f.pk].date < served)
        and last_calving.get(f.pk, date.min) < served
    ]
    calvings = Calving.objects.for_org(organization).filter(date__gte=year_ago)
    weanings = list(
        Weaning.objects.for_org(organization).filter(date__gte=year_ago).select_related("calf__birth_record")
    )
    adjusted = [w.adjusted_205 for w in weanings if w.adjusted_205]
    return {
        "females": females.count(),
        "checked": len(recent),
        "pregnancy_rate": len(pregnant_recent) / len(recent) * 100 if recent else None,
        "upcoming": sorted(
            (c for c in open_pregnancies if c.expected_calving and c.expected_calving <= today + timedelta(days=90)),
            key=lambda c: c.expected_calving,
        ),
        "pregnant_now": len(open_pregnancies),
        "pending": pending,
        "calvings": calvings.count(),
        "live_calvings": calvings.filter(stillborn=False).count(),
        "weanings": len(weanings),
        "weaning_avg": sum(float(w.weight_kg) for w in weanings) / len(weanings) if weanings else None,
        "adjusted_205": sum(adjusted) / len(adjusted) if adjusted else None,
    }


# --- Sanidad ----------------------------------------------------------------


def apply_treatment(animals, user, *, product, on, dose="", reason="", applied_by="", notes=""):
    until = on + timedelta(days=product.withdrawal_days) if product.withdrawal_days else None
    treatments = [
        Treatment(organization=a.organization, animal=a, product=product, date=on, dose=dose, reason=reason,
                  applied_by=applied_by, notes=notes, withdrawal_until=until, created_by=user)
        for a in animals
        if a.is_active
    ]
    Treatment.objects.bulk_create(treatments)
    return len(treatments)


def active_withdrawal(animal, on=None):
    """Tratamiento con el resguardo más largo vigente a la fecha, o None."""
    on = on or date.today()
    return animal.treatments.filter(withdrawal_until__gte=on).select_related("product").order_by(
        "-withdrawal_until"
    ).first()


def animals_in_withdrawal(organization, on=None):
    on = on or date.today()
    return (
        Treatment.objects.for_org(organization)
        .filter(withdrawal_until__gte=on, animal__status=Animal.Status.ACTIVE)
        .select_related("animal", "product")
        .order_by("animal_id", "-withdrawal_until")
        .distinct("animal_id")
    )


# --- Costos y márgenes ------------------------------------------------------


@transaction.atomic
def register_cost(cost, animals, user):
    """Guarda el costo y lo reparte en partes iguales entre los animales (el último absorbe el redondeo)."""
    cost.amount = Decimal(cost.amount)
    cost.created_by = user
    cost.heads = len(animals)
    cost.save()
    if animals:
        share = (cost.amount / len(animals)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        allocations = [
            CostAllocation(organization=cost.organization, cost=cost, animal=a, amount=share) for a in animals
        ]
        allocations[-1].amount = cost.amount - share * (len(animals) - 1)
        CostAllocation.objects.bulk_create(allocations)
    return cost


def latest_prices(organization):
    """{categoría: precio por kg} con el precio vigente más reciente de cada categoría."""
    prices = {}
    refs = PriceReference.objects.for_org(organization).filter(date__lte=date.today()).order_by("category", "-date")
    for ref in refs:
        prices.setdefault(ref.category, ref.price_per_kg)
    return prices


@dataclass
class Economics:
    purchase: Decimal = Decimal(0)
    costs: Decimal = Decimal(0)
    sale: Decimal | None = None
    first_weight: Decimal | None = None
    last_weight: Decimal | None = None
    value: Decimal | None = None  # valor estimado si sigue en existencia

    @property
    def kg_gained(self):
        if self.first_weight is None or self.last_weight is None:
            return None
        return self.last_weight - self.first_weight

    @property
    def income(self):
        return self.sale if self.sale is not None else self.value

    @property
    def margin(self):
        return None if self.income is None else self.income - self.purchase - self.costs

    @property
    def cost_per_kg(self):
        gained = self.kg_gained
        return self.costs / gained if gained and gained > 0 and self.costs else None


def herd_economics(organization, animals):
    """Economía de cada animal: {animal_id: Economics}. Pocas consultas, sirve para rebaños grandes."""
    animals = list(animals)
    ids = [a.pk for a in animals]
    result = {pk: Economics() for pk in ids}
    allocations = (
        CostAllocation.objects.for_org(organization).filter(animal_id__in=ids)
        .order_by().values_list("animal_id").annotate(total=models.Sum("amount"))
    )
    for pk, total in allocations:
        result[pk].costs = total
    money = (
        Movement.objects.for_org(organization)
        .filter(animal_id__in=ids, kind__in=[Movement.Kind.PURCHASE, Movement.Kind.SALE], price_clp__isnull=False)
        .order_by().values_list("animal_id", "kind").annotate(total=models.Sum("price_clp"))
    )
    for pk, kind, total in money:
        if kind == Movement.Kind.PURCHASE:
            result[pk].purchase = total
        else:
            result[pk].sale = total
    weights = (
        Weighing.objects.for_org(organization).filter(animal_id__in=ids)
        .order_by("animal_id", "date", "created_at").values_list("animal_id", "weight_kg")
    )
    for pk, kg in weights:
        econ = result[pk]
        if econ.first_weight is None:
            econ.first_weight = kg
        econ.last_weight = kg
    prices = latest_prices(organization)
    for a in animals:
        econ = result[a.pk]
        if a.is_active and econ.last_weight and a.category in prices:
            econ.value = econ.last_weight * prices[a.category]
    return result


def sum_present(values):
    values = [v for v in values if v is not None]
    return sum(values, Decimal(0)) if values else None


def lot_economics(organization):
    """Resumen por lote de los animales en existencia: costo acumulado, kg ganados, $/kg y margen estimado."""
    animals = list(
        Animal.objects.for_org(organization).filter(status=Animal.Status.ACTIVE).select_related("lot")
    )
    econ = herd_economics(organization, animals)
    groups = defaultdict(list)
    for a in animals:
        groups[a.lot.name if a.lot else "Sin lote"].append(econ[a.pk])
    rows = []
    for name, items in sorted(groups.items()):
        costs = sum_present(e.costs for e in items) or Decimal(0)
        gained = sum_present(e.kg_gained for e in items if e.kg_gained and e.kg_gained > 0)
        value = sum_present(e.value for e in items)
        purchase = sum_present(e.purchase for e in items) or Decimal(0)
        rows.append({
            "lot": name, "heads": len(items), "costs": costs, "kg_gained": gained,
            "cost_per_kg": costs / gained if gained and costs else None,
            "value": value, "purchase": purchase,
            "margin": value - purchase - costs if value is not None and all(e.value for e in items) else None,
        })
    return rows, econ


def sold_economics(organization, since):
    sales = (
        Movement.objects.for_org(organization).filter(kind=Movement.Kind.SALE, date__gte=since)
        .select_related("animal__lot").order_by("-date")
    )
    animals = [m.animal for m in sales]
    econ = herd_economics(organization, animals)
    return [{"movement": m, "animal": m.animal, "econ": econ[m.animal_id],
             "days": (m.date - m.animal.entry_date).days} for m in sales]
