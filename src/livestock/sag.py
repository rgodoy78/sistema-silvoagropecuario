"""Apoyo a los trámites del SAG: existencias para la DEA, planilla del FMA y DIIO pendientes.

Los trámites se hacen en SIPECweb; aquí se preparan los datos en el formato
que piden (categorías oficiales del FMA: vaca, vaquilla, ternera, ternero,
novillo, toro y buey).
"""

from collections import Counter
from datetime import date

from livestock.models import Animal

C = Animal.Category
SAG_CATEGORIES = ["Vaca", "Vaquilla", "Ternera", "Ternero", "Novillo", "Toro", "Buey"]
# El SAG no distingue torete: se informa como toro.
TO_SAG = {
    C.COW: "Vaca", C.HEIFER: "Vaquilla", C.CALF_F: "Ternera", C.CALF_M: "Ternero",
    C.STEER: "Novillo", C.YOUNG_BULL: "Toro", C.BULL: "Toro", C.OX: "Buey",
}
DIIO_DEADLINE_MONTHS = 12
DIIO_WARNING_MONTHS = 10


def count_by_sag_category(animals):
    counts = Counter(TO_SAG[a.category] for a in animals)
    return [counts.get(name, 0) for name in SAG_CATEGORIES]


def stock_by_rup(organization):
    """Existencias actuales por predio (RUP) y categoría SAG, para la DEA."""
    animals = Animal.objects.for_org(organization).filter(status=Animal.Status.ACTIVE).select_related("farm")
    by_farm = {}
    for a in animals:
        by_farm.setdefault(a.farm, []).append(a)
    rows = []
    for farm in sorted(by_farm, key=lambda f: f.name):
        counts = count_by_sag_category(by_farm[farm])
        rows.append({"farm": farm, "counts": counts, "total": sum(counts)})
    totals = [sum(r["counts"][i] for r in rows) for i in range(len(SAG_CATEGORIES))]
    return rows, totals


def diio_pending(organization, today=None):
    """Animales en existencia sin DIIO: vencidos (12+ meses), por vencer (10+) y sin fecha de nacimiento."""
    today = today or date.today()
    overdue, soon, unknown = [], [], []
    animals = Animal.objects.for_org(organization).filter(status=Animal.Status.ACTIVE, diio="").select_related("farm")
    for a in animals.order_by("birth_date"):
        months = a.age_months(today)
        if months is None:
            unknown.append(a)
        elif months >= DIIO_DEADLINE_MONTHS:
            overdue.append(a)
        elif months >= DIIO_WARNING_MONTHS:
            soon.append(a)
    return {"overdue": overdue, "soon": soon, "unknown": unknown}
