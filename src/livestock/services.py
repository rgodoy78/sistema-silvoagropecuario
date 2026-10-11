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
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count

from livestock.models import Animal, Movement, Weighing

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
