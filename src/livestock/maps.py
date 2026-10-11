"""Datos de mapas para static/js/map.js (predio, potreros y polígono en edición)."""

from django.conf import settings
from django.db.models import Count, Q

from livestock.models import Animal


def map_data(farm, editing=None):
    """Datos para static/js/map.js: el predio, sus potreros y (opcional) el polígono en edición."""
    paddocks = farm.paddocks.annotate(heads=Count("animals", filter=Q(animals__status=Animal.Status.ACTIVE)))
    data = {
        "farm": {"name": farm.name, "boundary": farm.boundary} if farm.boundary and editing != farm else None,
        "paddocks": [
            {"name": p.name, "boundary": p.boundary, "heads": p.heads, "area": float(p.area_ha) if p.area_ha else None}
            for p in paddocks
            if p.boundary and p != editing
        ],
    }
    if editing is not None:
        data["edit"] = {"boundary": editing.boundary}
    return data


def map_context(farm, editing=None):
    return {"map_data": map_data(farm, editing), "esri_key": settings.ESRI_API_KEY}
